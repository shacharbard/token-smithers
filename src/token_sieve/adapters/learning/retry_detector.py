"""Retry detection for CLI compress subcommand — Decision D2.

Detects when the same logical command is repeated consecutively within
a time window (D2a). Pattern hash ignores flags, normalizes positional
arg order (D2e).

Usage:
    from token_sieve.adapters.learning.retry_detector import RetryDetector, normalize_pattern_hash

    det = RetryDetector()
    is_retry = det.record_command(cmd)
"""
from __future__ import annotations

import hashlib
import shlex
import time
from dataclasses import dataclass, field
from typing import Optional


# Commands where argument order is load-bearing (src before dst, etc.).
# Positional arguments for these MUST NOT be sorted by normalize_pattern_hash.
_ORDER_SENSITIVE_BINARIES: frozenset[str] = frozenset({
    "mv", "cp", "rsync", "ln", "diff", "scp",
})


def normalize_pattern_hash(cmd: str) -> str:
    """Return a stable hash for a shell command.

    Algorithm (M1 fix):
    1. shlex.split the command into tokens.
    2. The first token is the binary — keep verbatim (basename only for
       canonicalization would be nice but is out of scope here).
    3. Flag NAMES are preserved (so `rm -rf foo` ≠ `rm foo`), but flag
       VALUES that follow a `-x` short flag are collapsed to `<VAL>` so
       `-p 80` and `-p 443` hash equal.
    4. Positional arguments are sorted only for commands that are NOT in
       `_ORDER_SENSITIVE_BINARIES`. `mv src dst` must never collide with
       `mv dst src`.
    5. sha256 the canonical form.

    Returns:
        A lowercase hex digest string.
    """
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        # Malformed shell — hash the raw command
        return hashlib.sha256(cmd.encode()).hexdigest()

    if not tokens:
        return hashlib.sha256(b"").hexdigest()

    binary = tokens[0]

    # Walk the remaining tokens once, emitting (a) each flag, (b) a
    # `<VAL>` placeholder where a short flag consumed the next positional
    # as its value, and (c) real positionals.
    flags: list[str] = []
    positionals: list[str] = []
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("--"):
            # Long flag. Keep the whole token (including any =value suffix
            # stripped to the name only so `--port=80` and `--port=443`
            # hash equal).
            if "=" in tok:
                name, _ = tok.split("=", 1)
                flags.append(f"{name}=<VAL>")
            else:
                flags.append(tok)
            i += 1
            continue
        if tok.startswith("-") and len(tok) > 1:
            # Short flag. Keep the flag token and collapse the next token
            # to <VAL> IF the next token is not itself a flag and not the
            # end of argv. This is a coarse heuristic; for precise parsing
            # we'd need a per-binary spec, but this collapses `-p 80` vs
            # `-p 443` without crashing on boolean-only flags like `-r`.
            flags.append(tok)
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                # Peek at next token: if it's the only remaining token AND
                # we're running an order-sensitive binary, it's probably a
                # positional; otherwise treat as a value for the flag.
                # For simplicity, always treat a trailing non-flag after a
                # short flag as a value when the short flag is conventional
                # value-taking (e.g. -p, -o, -f, -n, -u, -c). Fall back to
                # positional.
                next_tok = tokens[i + 1]
                if tok in _SHORT_FLAGS_TAKING_VALUE:
                    flags.append("<VAL>")
                    i += 2
                    continue
                # Not obviously a value — leave as positional.
            i += 1
            continue
        positionals.append(tok)
        i += 1

    if binary not in _ORDER_SENSITIVE_BINARIES:
        positionals.sort()

    # Flags are emitted in first-seen order — this is fine for hashing
    # because any reordering of flags on the CLI is semantically equivalent
    # for the commands we care about (`-xvs` vs `-svx`) only if the user
    # writes the same bundle, which shlex already normalizes.
    canonical_parts = [binary] + flags + positionals
    canonical = " ".join(canonical_parts)
    return hashlib.sha256(canonical.encode()).hexdigest()


# Short flags that conventionally take a VALUE as their next argv token.
# Collapsing the value to `<VAL>` lets `-p 80` and `-p 443` hash equal.
# Conservative allowlist: only flags that are almost always value-taking
# across common CLIs. Boolean-only flags like -r/-f/-v are excluded so we
# don't accidentally eat their following positional.
_SHORT_FLAGS_TAKING_VALUE: frozenset[str] = frozenset({
    "-p", "-o", "-u", "-c", "-C", "-D",
    "-g", "-G", "-i", "-I", "-L", "-P",
    "-T", "-W",
})


@dataclass
class _CommandRecord:
    """Internal record for one observed command invocation."""

    pattern_hash: str
    ts: float
    sequence_id: Optional[int]


class RetryDetector:
    """Detect consecutive retries of the same logical command (D2a + D2e).

    Two-axis rule:
    - Axis 1: consecutive same-pattern_hash with no different-hash command between.
    - Axis 2: elapsed wall-clock time ≤ window_seconds since the previous same-hash call.

    Concurrent invocations (sequence_id overlap) are excluded from the consecutive
    gate: if two calls carry sequence IDs and those IDs overlap (second ID ≤ first ID),
    they are not classified as retries of each other.

    Attributes:
        window_seconds: Time window for the soft cap (default 90).
    """

    _MAX_HISTORY = 50  # Bounded ring to prevent unbounded memory growth

    def __init__(self, window_seconds: float = 90) -> None:
        self.window_seconds = window_seconds
        self._history: list[_CommandRecord] = []
        # Tracks the last active sequence_id to detect overlapping concurrent calls
        self._last_sequence_id: Optional[int] = None

    def record_command(
        self,
        cmd: str,
        ts: Optional[float] = None,
        sequence_id: Optional[int] = None,
    ) -> bool:
        """Record a command invocation and return whether it is a retry.

        Args:
            cmd: The shell command string.
            ts: Monotonic timestamp (defaults to time.monotonic()).
            sequence_id: Optional concurrent-invocation sequence number.
                If two calls with sequence_ids overlap (second_id <= last_id),
                they are treated as concurrent and not counted as retries.

        Returns:
            True if this invocation is classified as a retry, False otherwise.
        """
        if ts is None:
            ts = time.monotonic()

        pattern_hash = normalize_pattern_hash(cmd)

        # Concurrent-invocation guard: if both this call and the previous call
        # carry a sequence_id, they were launched via run_in_background and are
        # running concurrently — do NOT count as retry of each other.
        prev_record = self._history[-1] if self._history else None
        is_concurrent = (
            sequence_id is not None
            and prev_record is not None
            and prev_record.sequence_id is not None
            and prev_record.sequence_id != sequence_id
        )

        # Record the invocation
        record = _CommandRecord(
            pattern_hash=pattern_hash, ts=ts, sequence_id=sequence_id
        )
        if sequence_id is not None:
            self._last_sequence_id = sequence_id
        self._history.append(record)

        # Trim history to bounded size
        if len(self._history) > self._MAX_HISTORY:
            self._history = self._history[-self._MAX_HISTORY :]

        # Need at least 2 records to detect a retry
        if len(self._history) < 2:
            return False

        if is_concurrent:
            return False

        # Look at the previous record
        prev = self._history[-2]

        # Axis 1: consecutive same-hash gate
        if prev.pattern_hash != pattern_hash:
            return False

        # Axis 2: time window gate
        elapsed = ts - prev.ts
        if elapsed > self.window_seconds:
            return False

        return True
