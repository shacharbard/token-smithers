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


def normalize_pattern_hash(cmd: str) -> str:
    """Return a stable hash for a shell command, ignoring flags.

    Algorithm (D2e):
    1. shlex.split the command into tokens.
    2. The first token is the binary — keep it verbatim.
    3. Drop any token that starts with '-' (flags/options).
    4. Sort the remaining positional arguments.
    5. Join binary + sorted_positionals with spaces and sha256.

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
    positionals = sorted(t for t in tokens[1:] if not t.startswith("-"))
    canonical = " ".join([binary] + positionals)
    return hashlib.sha256(canonical.encode()).hexdigest()


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
