"""Tests for TruncationCompressor adapter.

Inherits CompressionStrategyContract for uniform protocol compliance.
"""

from __future__ import annotations

import pytest

from tests.unit.adapters.conftest import CompressionStrategyContract
from token_sieve.adapters.compression.truncation import TruncationCompressor
from token_sieve.domain.counters import CharEstimateCounter
from token_sieve.domain.model import ContentEnvelope, ContentType


@pytest.fixture()
def strategy():
    """Provide TruncationCompressor with small budget for contract tests."""
    return TruncationCompressor(max_tokens=100)


class TestTruncationContract(CompressionStrategyContract):
    """TruncationCompressor must satisfy the CompressionStrategy contract."""


class TestTruncationSpecific:
    """Truncation-specific behavioral tests."""

    def test_can_handle_returns_true_for_all_content_types(self, make_envelope):
        """TruncationCompressor handles every content type."""
        compressor = TruncationCompressor(max_tokens=100)
        for ct in ContentType:
            envelope = make_envelope(content_type=ct)
            assert compressor.can_handle(envelope) is True

    def test_preserves_short_content(self, make_envelope):
        """Content within budget is returned unchanged."""
        compressor = TruncationCompressor(max_tokens=100)
        # 20 chars => 5 tokens (chars//4), well under 100
        envelope = make_envelope(content="short text here!!!!!")
        result = compressor.compress(envelope)
        assert result.content == envelope.content

    def test_truncates_long_content(self, make_envelope):
        """Content over budget is truncated with marker."""
        compressor = TruncationCompressor(max_tokens=10)
        # 200 chars => 50 tokens, well over 10
        long_content = "a" * 200
        envelope = make_envelope(content=long_content)
        result = compressor.compress(envelope)
        assert len(result.content) < len(long_content)
        assert "[truncated:" in result.content

    def test_truncation_marker_shows_token_counts(self, make_envelope):
        """Truncation marker includes original and truncated token counts."""
        compressor = TruncationCompressor(max_tokens=10)
        long_content = "a" * 200
        envelope = make_envelope(content=long_content)
        result = compressor.compress(envelope)
        # Original: 200//4 = 50 tokens
        assert "50 ->" in result.content

    def test_preserves_metadata(self, make_envelope):
        """Metadata is preserved after truncation."""
        compressor = TruncationCompressor(max_tokens=10)
        metadata = {"tool_name": "read_file", "call_id": 7}
        envelope = make_envelope(content="a" * 200, metadata=metadata)
        result = compressor.compress(envelope)
        assert dict(result.metadata) == metadata

    def test_preserves_content_type(self, make_envelope):
        """Content type is preserved after truncation."""
        compressor = TruncationCompressor(max_tokens=10)
        envelope = make_envelope(content="a" * 200, content_type=ContentType.CODE)
        result = compressor.compress(envelope)
        assert result.content_type is ContentType.CODE

    def test_default_max_tokens(self):
        """Default max_tokens is 4096."""
        compressor = TruncationCompressor()
        assert compressor.max_tokens == 4096

    def test_configurable_max_tokens(self):
        """max_tokens can be set via constructor."""
        compressor = TruncationCompressor(max_tokens=500)
        assert compressor.max_tokens == 500

    def test_exactly_at_limit_not_truncated(self, make_envelope):
        """Content exactly at the token limit is not truncated."""
        compressor = TruncationCompressor(max_tokens=10)
        # 40 chars => 10 tokens exactly
        envelope = make_envelope(content="a" * 40)
        result = compressor.compress(envelope)
        assert result.content == envelope.content

    def test_one_token_over_limit_truncated(self, make_envelope):
        """Content one token over the limit is truncated."""
        compressor = TruncationCompressor(max_tokens=10)
        # 44 chars => 11 tokens, one over
        envelope = make_envelope(content="a" * 44)
        result = compressor.compress(envelope)
        assert "[truncated:" in result.content

    def test_keeps_at_least_first_line(self, make_envelope):
        """Even heavy truncation preserves at least the first line."""
        compressor = TruncationCompressor(max_tokens=1)
        content = "first line\nsecond line\nthird line"
        envelope = make_envelope(content=content)
        result = compressor.compress(envelope)
        # Must have some content (ContentEnvelope enforces non-empty)
        assert result.content
        assert "first line" in result.content

    def test_uses_char_estimate_counter_by_default(self):
        """Default counter is CharEstimateCounter."""
        compressor = TruncationCompressor()
        assert isinstance(compressor._counter, CharEstimateCounter)

    @pytest.mark.parametrize(
        "content_len,max_tokens,should_truncate",
        [
            (20, 100, False),   # 5 tokens, under limit
            (400, 100, False),  # 100 tokens, at limit
            (404, 100, True),   # 101 tokens, over limit
            (2000, 50, True),   # 500 tokens, well over
            (4, 1, False),      # 1 token, at limit
            (8, 1, True),       # 2 tokens, over limit
        ],
    )
    def test_boundary_conditions(self, make_envelope, content_len, max_tokens, should_truncate):
        """Parametrized boundary condition tests."""
        compressor = TruncationCompressor(max_tokens=max_tokens)
        envelope = make_envelope(content="x" * content_len)
        result = compressor.compress(envelope)
        if should_truncate:
            assert "[truncated:" in result.content
        else:
            assert "[truncated:" not in result.content
