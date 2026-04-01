"""Tests for SizeGate adapter and should_compress utility.

Inherits CompressionStrategyContract for uniform protocol compliance.
"""

from __future__ import annotations

import pytest

from tests.unit.adapters.conftest import CompressionStrategyContract
from token_sieve.domain.model import ContentEnvelope, ContentType


@pytest.fixture()
def strategy():
    """Provide SizeGate for contract tests with a low threshold."""
    from token_sieve.adapters.compression.size_gate import SizeGate
    from token_sieve.domain.counters import CharEstimateCounter

    # Use low threshold so contract tests with short content trigger can_handle=True
    return SizeGate(threshold=1, counter=CharEstimateCounter())


class TestSizeGateContract(CompressionStrategyContract):
    """SizeGate must satisfy the CompressionStrategy contract."""


class TestSizeGateSpecific:
    """SizeGate-specific behavioral tests."""

    def test_small_content_not_handled(self, make_envelope):
        """Content below threshold should not be handled (can_handle=False)."""
        from token_sieve.adapters.compression.size_gate import SizeGate
        from token_sieve.domain.counters import CharEstimateCounter

        gate = SizeGate(threshold=2000, counter=CharEstimateCounter())
        # "short" is ~1 token, well below 2000
        envelope = make_envelope(content="short content")
        assert gate.can_handle(envelope) is False

    def test_large_content_handled(self, make_envelope):
        """Content above threshold should be handled (can_handle=True)."""
        from token_sieve.adapters.compression.size_gate import SizeGate
        from token_sieve.domain.counters import CharEstimateCounter

        gate = SizeGate(threshold=5, counter=CharEstimateCounter())
        # 100 chars ~ 25 tokens, above threshold of 5
        envelope = make_envelope(content="x" * 100)
        assert gate.can_handle(envelope) is True

    def test_compress_returns_unchanged(self, make_envelope):
        """compress() should return content unchanged (SizeGate is a gate, not a transform)."""
        from token_sieve.adapters.compression.size_gate import SizeGate
        from token_sieve.domain.counters import CharEstimateCounter

        gate = SizeGate(threshold=1, counter=CharEstimateCounter())
        envelope = make_envelope(content="some content to pass through")
        result = gate.compress(envelope)
        assert result.content == envelope.content

    def test_threshold_configurable(self, make_envelope):
        """Threshold should be configurable via constructor."""
        from token_sieve.adapters.compression.size_gate import SizeGate
        from token_sieve.domain.counters import CharEstimateCounter

        counter = CharEstimateCounter()
        content = "x" * 40  # 40 chars ~ 10 tokens

        gate_low = SizeGate(threshold=5, counter=counter)
        gate_high = SizeGate(threshold=50, counter=counter)

        envelope = make_envelope(content=content)
        assert gate_low.can_handle(envelope) is True   # 10 > 5
        assert gate_high.can_handle(envelope) is False  # 10 < 50

    def test_exact_threshold_not_handled(self, make_envelope):
        """Content at exactly the threshold should not be handled (< not <=)."""
        from token_sieve.adapters.compression.size_gate import SizeGate
        from token_sieve.domain.counters import CharEstimateCounter

        counter = CharEstimateCounter()
        # 40 chars / 4 = 10 tokens
        content = "x" * 40
        gate = SizeGate(threshold=10, counter=counter)
        envelope = make_envelope(content=content)
        # At threshold, not above -- should not handle
        assert gate.can_handle(envelope) is False

    def test_default_threshold(self, make_envelope):
        """Default threshold should be approximately 2000 tokens."""
        from token_sieve.adapters.compression.size_gate import SizeGate

        gate = SizeGate()
        assert gate.threshold == 2000


class TestShouldCompress:
    """Tests for the should_compress() utility function."""

    def test_small_content_returns_false(self, make_envelope):
        """Small content should return False (skip compression)."""
        from token_sieve.adapters.compression.size_gate import should_compress
        from token_sieve.domain.counters import CharEstimateCounter

        envelope = make_envelope(content="tiny")
        assert should_compress(envelope, CharEstimateCounter(), 2000) is False

    def test_large_content_returns_true(self, make_envelope):
        """Large content should return True (proceed with compression)."""
        from token_sieve.adapters.compression.size_gate import should_compress
        from token_sieve.domain.counters import CharEstimateCounter

        envelope = make_envelope(content="x" * 10000)
        assert should_compress(envelope, CharEstimateCounter(), 2000) is True

    def test_custom_threshold(self, make_envelope):
        """Custom threshold should be respected."""
        from token_sieve.adapters.compression.size_gate import should_compress
        from token_sieve.domain.counters import CharEstimateCounter

        envelope = make_envelope(content="x" * 100)  # ~25 tokens
        assert should_compress(envelope, CharEstimateCounter(), 10) is True
        assert should_compress(envelope, CharEstimateCounter(), 100) is False
