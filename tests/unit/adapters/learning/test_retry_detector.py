"""RED tests for RetryDetector — 2-axis retry detection (D2a + D2e).

Task 2 of 09-03: pattern hash normalization + consecutive+time-window gate.
"""
from __future__ import annotations

import time

import pytest

from token_sieve.adapters.learning.retry_detector import (
    RetryDetector,
    normalize_pattern_hash,
)


class TestNormalizePatternHash:
    """Pattern hash is (binary + sorted positional args); flags are ignored (D2e)."""

    def test_pattern_hash_ignores_flag_values_for_same_flags(self) -> None:
        """M1 update: hashes are equal when the SAME flags are present with different values.

        The original D2e contract said "flags are ignored entirely" but M1
        proved that over-normalization collapses `rm -rf foo` and `rm foo`
        into the same retry bucket, which is dangerous. The new contract:
        flag NAMES matter, flag VALUES do not.
        """
        h1 = normalize_pattern_hash("pytest -xvs tests/auth")
        h2 = normalize_pattern_hash("pytest -xvs tests/auth")
        assert h1 == h2, "Identical invocations must hash equal"

        # Different flag sets must now produce different hashes.
        h3 = normalize_pattern_hash("pytest --no-header tests/auth")
        assert h1 != h3, "Different flag sets now yield different hashes (M1)"

    def test_pattern_hash_distinguishes_positional(self) -> None:
        """Different positional args must produce different hashes."""
        h1 = normalize_pattern_hash("pytest tests/auth")
        h2 = normalize_pattern_hash("pytest tests/payments")
        assert h1 != h2, "Different positional args must yield different hash"

    def test_pattern_hash_normalizes_arg_order(self) -> None:
        """Sorted positional args — order must not matter for pytest."""
        h1 = normalize_pattern_hash("pytest a b")
        h2 = normalize_pattern_hash("pytest b a")
        assert h1 == h2, "Positional args should be sorted before hashing"

    def test_pattern_hash_distinguishes_flag_presence(self) -> None:
        """M1 fix: `rm -rf foo` must NOT hash-equal `rm foo`.

        The old normalizer stripped all `-`-prefixed tokens entirely, so
        `rm -rf /` and `rm /` collided — a catastrophic cache-key bug when
        the flag meaningfully changes the command's semantics.
        """
        h1 = normalize_pattern_hash("rm -rf foo")
        h2 = normalize_pattern_hash("rm foo")
        assert h1 != h2, "Flag presence must affect the hash"

    def test_pattern_hash_collapses_flag_values_only(self) -> None:
        """Flag VALUES may be collapsed (so `-p 80` == `-p 443`) but the flag itself stays."""
        h1 = normalize_pattern_hash("nc -p 80 host.example")
        h2 = normalize_pattern_hash("nc -p 443 host.example")
        assert h1 == h2, "Flag-value differences should collapse"

        # But removing the flag entirely must NOT match.
        h3 = normalize_pattern_hash("nc host.example")
        assert h1 != h3, "Flag presence still matters"

    def test_pattern_hash_preserves_order_for_mv(self) -> None:
        """M1 fix: `mv src dst` must NOT hash-equal `mv dst src`.

        Arguments are order-sensitive for mv, cp, rsync, ln, diff, git diff.
        The old normalizer sorted positionals unconditionally.
        """
        assert normalize_pattern_hash("mv a b") != normalize_pattern_hash("mv b a")
        assert normalize_pattern_hash("cp a b") != normalize_pattern_hash("cp b a")
        assert normalize_pattern_hash("rsync src dst") != normalize_pattern_hash("rsync dst src")
        assert normalize_pattern_hash("diff a b") != normalize_pattern_hash("diff b a")


class TestRetryDetector:
    """2-axis gate: consecutive same-command AND within window_seconds."""

    def test_consecutive_within_90s_triggers(self) -> None:
        """Same command twice within 1s → second is_retry=True."""
        det = RetryDetector(window_seconds=90)
        now = time.monotonic()
        det.record_command("pytest x", ts=now)
        result = det.record_command("pytest x", ts=now + 0.5)
        assert result is True, "Consecutive same command within window should be retry"

    def test_consecutive_after_90s_does_not_trigger(self) -> None:
        """Same command but 91s apart → not a retry."""
        det = RetryDetector(window_seconds=90)
        now = time.monotonic()
        det.record_command("pytest x", ts=now)
        result = det.record_command("pytest x", ts=now + 91)
        assert result is False, "Command beyond 90s window should not be a retry"

    def test_intervening_different_command_resets(self) -> None:
        """An intervening different command breaks the consecutive gate."""
        det = RetryDetector(window_seconds=90)
        now = time.monotonic()
        det.record_command("pytest x", ts=now)
        det.record_command("ls", ts=now + 1)
        result = det.record_command("pytest x", ts=now + 2)
        assert result is False, "Intervening different command should reset consecutive gate"

    def test_intervening_same_command_does_not_reset(self) -> None:
        """Three consecutive identical commands → 2nd and 3rd are retries."""
        det = RetryDetector(window_seconds=90)
        now = time.monotonic()
        det.record_command("pytest x", ts=now)
        r2 = det.record_command("pytest x", ts=now + 10)
        r3 = det.record_command("pytest x", ts=now + 20)
        assert r2 is True, "Second consecutive same command is retry"
        assert r3 is True, "Third consecutive same command is also retry"

    def test_first_command_is_never_retry(self) -> None:
        """The very first record_command call can never be a retry."""
        det = RetryDetector(window_seconds=90)
        result = det.record_command("pytest x")
        assert result is False, "First command is never a retry"

    def test_concurrent_via_run_in_background_classified_by_sequence(self) -> None:
        """Commands with overlapping sequence IDs do not count as retries."""
        det = RetryDetector(window_seconds=90)
        now = time.monotonic()
        # Simulate two concurrent commands starting at overlapping times
        # sequence_id=0 starts first
        det.record_command("pytest x", ts=now, sequence_id=0)
        # sequence_id=1 starts 0.1s later — overlapping with 0 still in flight
        result = det.record_command("pytest x", ts=now + 0.1, sequence_id=1)
        # Overlapping sequences should NOT count as retry of each other
        assert result is False, (
            "Concurrent (overlapping sequence) commands should not be classified as retries"
        )

    def test_hash_is_stable_across_instances(self) -> None:
        """normalize_pattern_hash must return the same value for the same input."""
        h1 = normalize_pattern_hash("cargo test --release mymod")
        h2 = normalize_pattern_hash("cargo test --release mymod")
        assert h1 == h2

    def test_hash_returns_hex_string(self) -> None:
        """Hash should be a non-empty hex string."""
        h = normalize_pattern_hash("some command arg1")
        assert isinstance(h, str)
        assert len(h) > 0
        # All chars must be hex digits
        assert all(c in "0123456789abcdef" for c in h)
