"""Tests for JsonCodeUnwrapper compression adapter.

RED phase: contract tests, can_handle tests, and compress behavior tests.
All tests written before implementation (TDD).
"""

from __future__ import annotations

import json

import pytest

from token_sieve.domain.model import ContentEnvelope, ContentType
from tests.unit.adapters.conftest import CompressionStrategyContract


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def strategy():
    """Provide JsonCodeUnwrapper for contract and behavioral tests."""
    from token_sieve.adapters.compression.json_code_unwrapper import (
        JsonCodeUnwrapper,
    )

    return JsonCodeUnwrapper()


@pytest.fixture()
def make_envelope():
    """Factory fixture for ContentEnvelope instances."""

    def _factory(
        content: str = "test content for adapter",
        content_type: ContentType = ContentType.TEXT,
        metadata: dict | None = None,
    ) -> ContentEnvelope:
        return ContentEnvelope(
            content=content,
            content_type=content_type,
            metadata=metadata or {},
        )

    return _factory


# ---------------------------------------------------------------------------
# P02: Contract tests
# ---------------------------------------------------------------------------


class TestJsonCodeUnwrapperContract(CompressionStrategyContract):
    """JsonCodeUnwrapper must satisfy the CompressionStrategy contract."""


# ---------------------------------------------------------------------------
# P02: can_handle tests
# ---------------------------------------------------------------------------


class TestJsonCodeUnwrapperCanHandle:
    """can_handle() behavioral tests."""

    def test_handles_json_content_type(self, strategy, make_envelope):
        """JSON content type should be handled."""
        content = json.dumps({"source": "def foo(): pass"})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_handles_text_that_is_json(self, strategy, make_envelope):
        """TEXT content that parses as JSON with code fields should be handled."""
        content = json.dumps({"content": "def foo():\n    return 42"})
        envelope = make_envelope(content=content, content_type=ContentType.TEXT)
        assert strategy.can_handle(envelope) is True

    def test_rejects_non_json_text(self, strategy, make_envelope):
        """Plain text that is not JSON should be rejected."""
        envelope = make_envelope(
            content="just some plain text", content_type=ContentType.TEXT
        )
        assert strategy.can_handle(envelope) is False

    def test_rejects_json_without_code_fields(self, strategy, make_envelope):
        """JSON without recognized code field names should be rejected."""
        content = json.dumps({"name": "Alice", "age": 30})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is False

    def test_handles_json_with_source_field(self, strategy, make_envelope):
        """JSON with 'source' field containing code should be handled."""
        content = json.dumps({"source": "fn main() {}"})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_handles_json_with_code_field(self, strategy, make_envelope):
        """JSON with 'code' field containing code should be handled."""
        content = json.dumps({"code": "print('hello')"})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_handles_json_with_body_field(self, strategy, make_envelope):
        """JSON with 'body' field containing code should be handled."""
        content = json.dumps({"body": "function greet() { return 'hi'; }"})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_handles_json_with_text_field(self, strategy, make_envelope):
        """JSON with 'text' field containing code should be handled."""
        content = json.dumps({"text": "class Foo:\n    pass"})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_handles_json_with_content_field(self, strategy, make_envelope):
        """JSON with 'content' field containing code should be handled."""
        content = json.dumps({"content": "import os\nos.listdir('.')"})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_rejects_small_code_values(self, strategy, make_envelope):
        """JSON with code fields but very short values should be rejected."""
        content = json.dumps({"source": "x"})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is False


# ---------------------------------------------------------------------------
# P03: compress behavior tests
# ---------------------------------------------------------------------------


class TestJsonCodeUnwrapperCompress:
    """compress() behavioral tests."""

    def test_extracts_source_field(self, strategy, make_envelope):
        """Should extract code from 'source' field."""
        code = "def hello():\n    print('world')"
        content = json.dumps({"source": code, "language": "python"})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == code

    def test_extracts_code_field(self, strategy, make_envelope):
        """Should extract code from 'code' field."""
        code = "fn main() {\n    println!(\"hello\");\n}"
        content = json.dumps({"code": code, "lang": "rust"})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == code

    def test_extracts_body_field(self, strategy, make_envelope):
        """Should extract code from 'body' field."""
        code = "function greet() { return 'hi'; }"
        content = json.dumps({"body": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == code

    def test_extracts_content_field(self, strategy, make_envelope):
        """Should extract code from 'content' field."""
        code = "import os\nos.listdir('.')"
        content = json.dumps({"content": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == code

    def test_extracts_text_field(self, strategy, make_envelope):
        """Should extract code from 'text' field."""
        code = "class Foo:\n    pass"
        content = json.dumps({"text": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == code

    def test_priority_order_source_over_code(self, strategy, make_envelope):
        """When multiple code fields present, 'source' should win over 'code'."""
        content = json.dumps({
            "source": "def primary(): pass",
            "code": "def secondary(): pass",
        })
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == "def primary(): pass"

    def test_preserves_content_type(self, strategy, make_envelope):
        """Content type must be preserved after compression."""
        code = "def foo(): pass"
        content = json.dumps({"source": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content_type == ContentType.JSON

    def test_preserves_metadata(self, strategy, make_envelope):
        """Metadata must be preserved after compression."""
        code = "def foo(): pass"
        content = json.dumps({"source": code})
        metadata = {"tool_name": "read_file"}
        envelope = make_envelope(
            content=content, content_type=ContentType.JSON, metadata=metadata
        )
        result = strategy.compress(envelope)
        assert result.metadata["tool_name"] == "read_file"

    def test_passthrough_non_json(self, strategy, make_envelope):
        """Non-JSON content should pass through unchanged."""
        content = "just plain text"
        envelope = make_envelope(content=content, content_type=ContentType.TEXT)
        result = strategy.compress(envelope)
        assert result.content == content
        assert result is envelope

    def test_passthrough_small_values(self, strategy, make_envelope):
        """JSON with code fields but very short values should pass through."""
        content = json.dumps({"source": "x"})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == content

    def test_passthrough_json_without_code_fields(self, strategy, make_envelope):
        """JSON without recognized code fields should pass through."""
        content = json.dumps({"name": "Alice", "age": 30})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == content

    def test_nested_json_code_field(self, strategy, make_envelope):
        """Should handle nested JSON where code is in a nested object."""
        code = "def nested(): return True"
        content = json.dumps({"result": {"source": code}})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        # Top-level has no code field, so passthrough
        assert result.content == content

    def test_original_envelope_unchanged(self, strategy, make_envelope):
        """Original envelope must not be mutated (frozen dataclass)."""
        code = "def foo(): pass"
        content = json.dumps({"source": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        original_content = envelope.content
        strategy.compress(envelope)
        assert envelope.content == original_content
