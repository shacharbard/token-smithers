"""Tests for PassthroughStrategy adapter.

Inherits CompressionStrategyContract for uniform protocol compliance.
"""

from __future__ import annotations

import pytest

from tests.unit.adapters.conftest import CompressionStrategyContract
from token_sieve.adapters.compression.passthrough import PassthroughStrategy
from token_sieve.domain.model import ContentEnvelope, ContentType


@pytest.fixture()
def strategy():
    """Provide PassthroughStrategy for contract tests."""
    return PassthroughStrategy()


class TestPassthroughContract(CompressionStrategyContract):
    """PassthroughStrategy must satisfy the CompressionStrategy contract."""


class TestPassthroughSpecific:
    """Passthrough-specific behavioral tests."""

    def test_can_handle_returns_true_for_all_content_types(self, strategy, make_envelope):
        """PassthroughStrategy handles every content type."""
        for ct in ContentType:
            envelope = make_envelope(content_type=ct)
            assert strategy.can_handle(envelope) is True

    def test_compress_returns_identical_content(self, strategy, make_envelope):
        """PassthroughStrategy returns the envelope with identical content."""
        content = "hello world, this is a test"
        envelope = make_envelope(content=content)
        result = strategy.compress(envelope)
        assert result.content == content

    def test_compress_preserves_metadata(self, strategy, make_envelope):
        """PassthroughStrategy preserves all metadata."""
        metadata = {"tool_name": "read_file", "call_id": 42}
        envelope = make_envelope(metadata=metadata)
        result = strategy.compress(envelope)
        assert dict(result.metadata) == metadata

    def test_compress_preserves_content_type(self, strategy, make_envelope):
        """PassthroughStrategy preserves content_type."""
        envelope = make_envelope(content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content_type is ContentType.JSON

    def test_compress_returns_same_envelope_object(self, strategy, make_envelope):
        """PassthroughStrategy returns the exact same envelope (no copy)."""
        envelope = make_envelope()
        result = strategy.compress(envelope)
        assert result is envelope
