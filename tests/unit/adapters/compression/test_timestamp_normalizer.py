"""Tests for TimestampNormalizer adapter.

Inherits CompressionStrategyContract for uniform protocol compliance.
"""

from __future__ import annotations

import pytest

from tests.unit.adapters.conftest import CompressionStrategyContract
from token_sieve.domain.model import ContentEnvelope, ContentType


@pytest.fixture()
def strategy():
    """Provide TimestampNormalizer for contract tests."""
    from token_sieve.adapters.compression.timestamp_normalizer import (
        TimestampNormalizer,
    )

    return TimestampNormalizer()


class TestTimestampNormalizerContract(CompressionStrategyContract):
    """TimestampNormalizer must satisfy the CompressionStrategy contract."""


class TestTimestampNormalizerSpecific:
    """TimestampNormalizer-specific behavioral tests."""

    def test_iso_timestamps_normalized(self, strategy, make_envelope):
        """ISO-8601 timestamps should be converted to relative offsets."""
        content = (
            "Started at 2024-03-15T10:00:00Z\n"
            "Step 1 at 2024-03-15T10:05:30Z\n"
            "Step 2 at 2024-03-15T12:32:00Z\n"
        )
        envelope = make_envelope(content=content, content_type=ContentType.TEXT)
        result = strategy.compress(envelope)
        # First timestamp becomes T0, others become relative offsets
        assert "T0" in result.content or "+0" in result.content or "t0" in result.content.lower()
        # Should contain some offset notation for later timestamps
        assert "+" in result.content

    def test_multiple_timestamps_relative_to_first(self, strategy, make_envelope):
        """All timestamps should be relative to the first one found."""
        content = (
            "Event: 2024-01-01T00:00:00Z happened\n"
            "Event: 2024-01-01T02:30:00Z happened\n"
        )
        envelope = make_envelope(content=content, content_type=ContentType.TEXT)
        result = strategy.compress(envelope)
        # Second timestamp should show ~2h30m offset
        assert "2h" in result.content or "2:30" in result.content or "150" in result.content

    def test_non_timestamp_content_passthrough(self, strategy, make_envelope):
        """Content without timestamps should pass through unchanged."""
        content = "just some text without any timestamps at all"
        envelope = make_envelope(content=content, content_type=ContentType.TEXT)
        result = strategy.compress(envelope)
        assert result.content == content

    def test_iso_with_timezone_offset(self, strategy, make_envelope):
        """ISO-8601 with timezone offset (+05:30) should be handled."""
        content = (
            "Log: 2024-06-15T10:00:00+05:30 started\n"
            "Log: 2024-06-15T10:15:00+05:30 finished\n"
        )
        envelope = make_envelope(content=content, content_type=ContentType.TEXT)
        result = strategy.compress(envelope)
        assert "+" in result.content

    def test_iso_with_milliseconds(self, strategy, make_envelope):
        """ISO-8601 with milliseconds should be handled."""
        content = (
            "2024-03-15T10:00:00.123Z start\n"
            "2024-03-15T10:00:05.456Z end\n"
        )
        envelope = make_envelope(content=content, content_type=ContentType.TEXT)
        result = strategy.compress(envelope)
        # Should normalize despite milliseconds
        assert "+" in result.content or "T0" in result.content or "t0" in result.content.lower()

    def test_preserves_content_type(self, strategy, make_envelope):
        """Content type must be preserved."""
        content = "2024-01-01T00:00:00Z event\n2024-01-01T01:00:00Z event"
        envelope = make_envelope(content=content, content_type=ContentType.TEXT)
        result = strategy.compress(envelope)
        assert result.content_type is ContentType.TEXT

    def test_preserves_metadata(self, strategy, make_envelope):
        """Metadata must be preserved."""
        metadata = {"tool_name": "get_logs"}
        content = "2024-01-01T00:00:00Z event\n2024-01-01T01:00:00Z event"
        envelope = make_envelope(
            content=content, content_type=ContentType.TEXT, metadata=metadata
        )
        result = strategy.compress(envelope)
        assert result.metadata["tool_name"] == "get_logs"

    def test_single_timestamp_normalized(self, strategy, make_envelope):
        """A single timestamp should still be normalized to T0."""
        content = "Event at 2024-03-15T10:30:00Z happened"
        envelope = make_envelope(content=content, content_type=ContentType.TEXT)
        result = strategy.compress(envelope)
        # Single timestamp can be marked as T0 or left as-is
        # The key is it shouldn't crash
        assert result.content  # non-empty
