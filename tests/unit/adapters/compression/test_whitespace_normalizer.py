"""Tests for WhitespaceNormalizer adapter.

Inherits CompressionStrategyContract for uniform protocol compliance.
"""

from __future__ import annotations

import json

import pytest

from tests.unit.adapters.conftest import CompressionStrategyContract
from token_sieve.domain.model import ContentEnvelope, ContentType


@pytest.fixture()
def strategy():
    """Provide WhitespaceNormalizer for contract tests."""
    from token_sieve.adapters.compression.whitespace_normalizer import (
        WhitespaceNormalizer,
    )

    return WhitespaceNormalizer()


class TestWhitespaceNormalizerContract(CompressionStrategyContract):
    """WhitespaceNormalizer must satisfy the CompressionStrategy contract."""


class TestWhitespaceNormalizerSpecific:
    """WhitespaceNormalizer-specific behavioral tests."""

    def test_pretty_json_compacted(self, strategy, make_envelope):
        """Pretty-printed JSON should be compacted to minimal separators."""
        pretty = json.dumps({"name": "Alice", "age": 30, "tags": ["a", "b"]}, indent=2)
        envelope = make_envelope(content=pretty, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        # Result should be valid compact JSON
        parsed = json.loads(result.content)
        assert parsed == {"name": "Alice", "age": 30, "tags": ["a", "b"]}
        # No extra whitespace
        assert "\n" not in result.content
        assert "  " not in result.content

    def test_multi_blank_lines_collapsed(self, strategy, make_envelope):
        """Multiple blank lines should collapse to a single blank line."""
        content = "line1\n\n\n\nline2\n\n\n\nline3"
        envelope = make_envelope(content=content, content_type=ContentType.TEXT)
        result = strategy.compress(envelope)
        assert "\n\n\n" not in result.content
        assert "line1" in result.content
        assert "line2" in result.content
        assert "line3" in result.content

    def test_trailing_whitespace_stripped(self, strategy, make_envelope):
        """Trailing whitespace on lines should be stripped."""
        content = "line1   \nline2\t\t\nline3  "
        envelope = make_envelope(content=content, content_type=ContentType.TEXT)
        result = strategy.compress(envelope)
        for line in result.content.split("\n"):
            assert line == line.rstrip(), f"Line has trailing whitespace: {line!r}"

    def test_already_compact_json_unchanged(self, strategy, make_envelope):
        """Already compact JSON should remain unchanged."""
        compact = '{"a":1,"b":2}'
        envelope = make_envelope(content=compact, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == compact

    def test_preserves_content_type(self, strategy, make_envelope):
        """Content type must be preserved after compression."""
        envelope = make_envelope(content='{"x": 1}', content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content_type is ContentType.JSON

    def test_preserves_metadata(self, strategy, make_envelope):
        """Metadata must be preserved after compression."""
        metadata = {"tool_name": "read_file", "call_id": 42}
        envelope = make_envelope(
            content='{\n  "a": 1\n}',
            content_type=ContentType.JSON,
            metadata=metadata,
        )
        result = strategy.compress(envelope)
        assert result.metadata["tool_name"] == "read_file"
        assert result.metadata["call_id"] == 42

    def test_can_handle_text(self, strategy, make_envelope):
        """Should handle TEXT content type."""
        envelope = make_envelope(content="some text", content_type=ContentType.TEXT)
        assert strategy.can_handle(envelope) is True

    def test_can_handle_json(self, strategy, make_envelope):
        """Should handle JSON content type."""
        envelope = make_envelope(content='{"a":1}', content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_can_handle_code(self, strategy, make_envelope):
        """Should handle CODE content type."""
        envelope = make_envelope(content="def foo(): pass", content_type=ContentType.CODE)
        assert strategy.can_handle(envelope) is True

    def test_indented_code_normalized(self, strategy, make_envelope):
        """Excess indentation in code should be normalized."""
        content = "def foo():\n        x = 1\n        y = 2\n        return x + y"
        envelope = make_envelope(content=content, content_type=ContentType.CODE)
        result = strategy.compress(envelope)
        # Should still be valid code structure with trailing ws stripped
        assert "def foo():" in result.content
        assert "x = 1" in result.content

    def test_sort_keys_normalization(self, strategy, make_envelope):
        """Output keys must be sorted for cache-aligned determinism."""
        pretty = json.dumps({"zebra": 1, "alpha": 2}, indent=2)
        envelope = make_envelope(content=pretty, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == '{"alpha":2,"zebra":1}'
