"""Tests for NullFieldElider adapter.

Inherits CompressionStrategyContract for uniform protocol compliance.
"""

from __future__ import annotations

import json

import pytest

from tests.unit.adapters.conftest import CompressionStrategyContract
from token_sieve.domain.model import ContentEnvelope, ContentType


@pytest.fixture()
def strategy():
    """Provide NullFieldElider for contract tests."""
    from token_sieve.adapters.compression.null_field_elider import NullFieldElider

    return NullFieldElider()


class TestNullFieldEliderContract(CompressionStrategyContract):
    """NullFieldElider must satisfy the CompressionStrategy contract."""


class TestNullFieldEliderSpecific:
    """NullFieldElider-specific behavioral tests."""

    def test_null_fields_removed(self, strategy, make_envelope):
        """JSON with null fields should have them removed."""
        content = json.dumps({"name": "Alice", "age": None, "email": None})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        parsed = json.loads(result.content)
        assert parsed == {"name": "Alice"}
        assert "age" not in parsed
        assert "email" not in parsed

    def test_empty_string_fields_removed(self, strategy, make_envelope):
        """JSON with empty string fields should have them removed."""
        content = json.dumps({"name": "Alice", "bio": "", "role": "admin"})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        parsed = json.loads(result.content)
        assert parsed == {"name": "Alice", "role": "admin"}

    def test_empty_list_fields_removed(self, strategy, make_envelope):
        """JSON with empty list fields should have them removed."""
        content = json.dumps({"name": "Alice", "tags": [], "scores": [1, 2]})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        parsed = json.loads(result.content)
        assert parsed == {"name": "Alice", "scores": [1, 2]}

    def test_empty_dict_fields_removed(self, strategy, make_envelope):
        """JSON with empty dict fields should have them removed."""
        content = json.dumps({"name": "Alice", "meta": {}, "config": {"a": 1}})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        parsed = json.loads(result.content)
        assert parsed == {"name": "Alice", "config": {"a": 1}}

    def test_nested_null_removal(self, strategy, make_envelope):
        """Nested null/empty fields should be recursively removed."""
        content = json.dumps({
            "user": {"name": "Alice", "address": None, "prefs": {"theme": None, "lang": "en"}},
            "empty": {},
        })
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        parsed = json.loads(result.content)
        assert parsed == {"user": {"name": "Alice", "prefs": {"lang": "en"}}}

    def test_non_json_passthrough(self, strategy, make_envelope):
        """Non-JSON content should pass through unchanged."""
        content = "just some plain text with no JSON"
        envelope = make_envelope(content=content, content_type=ContentType.TEXT)
        result = strategy.compress(envelope)
        assert result.content == content

    def test_actual_values_preserved(self, strategy, make_envelope):
        """Fields with actual (non-empty) values must be preserved."""
        content = json.dumps({
            "name": "Alice",
            "age": 0,
            "active": False,
            "score": 0.0,
        })
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        parsed = json.loads(result.content)
        assert parsed == {"name": "Alice", "age": 0, "active": False, "score": 0.0}

    def test_preserves_content_type(self, strategy, make_envelope):
        """Content type must be preserved."""
        content = json.dumps({"a": None})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content_type is ContentType.JSON

    def test_preserves_metadata(self, strategy, make_envelope):
        """Metadata must be preserved."""
        metadata = {"tool_name": "list_files"}
        content = json.dumps({"a": None, "b": 1})
        envelope = make_envelope(content=content, content_type=ContentType.JSON, metadata=metadata)
        result = strategy.compress(envelope)
        assert result.metadata["tool_name"] == "list_files"

    def test_json_array_with_null_fields(self, strategy, make_envelope):
        """JSON arrays containing objects with null fields should be cleaned."""
        content = json.dumps([
            {"name": "Alice", "age": None},
            {"name": "Bob", "age": 30},
        ])
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        parsed = json.loads(result.content)
        assert parsed == [{"name": "Alice"}, {"name": "Bob", "age": 30}]

    def test_sort_keys_normalization(self, strategy, make_envelope):
        """Output keys must be sorted for cache-aligned determinism."""
        content = json.dumps({"zebra": 1, "alpha": None, "mango": 2})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        # After elision of alpha(None), remaining keys should be sorted
        assert result.content == '{"mango":2,"zebra":1}'
