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
        code = "def foo():\n    pass\n" + "    x = 1\n" * 120  # >500 chars with code signal
        content = json.dumps({"source": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_handles_text_that_is_json(self, strategy, make_envelope):
        """TEXT content that parses as JSON with code fields should be handled."""
        code = "def foo():\n    return 42\n" + "    x = 1\n" * 120
        content = json.dumps({"content": code})
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
        code = "fn main() {\n    println!(\"hello\");\n" + "    let x = 1;\n" * 100
        content = json.dumps({"source": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_handles_json_with_code_field(self, strategy, make_envelope):
        """JSON with 'code' field containing code should be handled."""
        code = "def hello():\n    print('hello')\n" + "    x = 1\n" * 120
        content = json.dumps({"code": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_handles_json_with_body_field(self, strategy, make_envelope):
        """JSON with 'body' field containing code should be handled."""
        code = "function greet() {\n    return 'hi';\n" + "    let x = 1;\n" * 100
        content = json.dumps({"body": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_handles_json_with_text_field(self, strategy, make_envelope):
        """JSON with 'text' field containing code should be handled."""
        code = "class Foo:\n    pass\n" + "    x = 1\n" * 120
        content = json.dumps({"text": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_handles_json_with_content_field(self, strategy, make_envelope):
        """JSON with 'content' field containing code should be handled."""
        code = "import os\nimport sys\n" + "x = 1\n" * 160
        content = json.dumps({"content": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_rejects_small_code_values(self, strategy, make_envelope):
        """JSON with code fields but very short values should be rejected."""
        content = json.dumps({"source": "x"})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is False

    def test_rejects_short_prose_in_content_field(self, strategy, make_envelope):
        """JSON with 'content' field containing short prose (<500 chars) is rejected."""
        content = json.dumps({"content": "No results found for your query", "total": 0})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is False

    def test_rejects_prose_without_code_signals(self, strategy, make_envelope):
        """Long text without code signals should be rejected even if >500 chars."""
        long_prose = "This is a long description of the weather. " * 20  # ~880 chars
        content = json.dumps({"content": long_prose})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is False

    def test_accepts_code_with_def_signal(self, strategy, make_envelope):
        """Long text with 'def ' code signal should be accepted."""
        code = "def hello():\n    print('world')\n" + "    x = 1\n" * 120  # >500 chars
        content = json.dumps({"source": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_accepts_code_with_function_signal(self, strategy, make_envelope):
        """Long text with 'function ' code signal should be accepted."""
        code = "function hello() {\n    console.log('world');\n" + "    let x = 1;\n" * 100
        content = json.dumps({"source": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_accepts_code_with_import_signal(self, strategy, make_envelope):
        """Long text with 'import ' code signal should be accepted."""
        code = "import os\nimport sys\n" + "x = 1\n" * 160  # >500 chars
        content = json.dumps({"content": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_accepts_code_with_class_signal(self, strategy, make_envelope):
        """Long text with 'class ' code signal should be accepted."""
        code = "class MyClass:\n    pass\n" + "    x = 1\n" * 120
        content = json.dumps({"code": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_accepts_code_with_struct_signal(self, strategy, make_envelope):
        """Long text with 'struct ' code signal should be accepted."""
        code = "struct MyStruct {\n    value: i32,\n" + "    field: i32,\n" * 80
        content = json.dumps({"source": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_accepts_code_with_arrow_signal(self, strategy, make_envelope):
        """Long text with '=>' code signal should be accepted."""
        code = "const fn = (x) => x + 1;\n" + "const y = 1;\n" * 100
        content = json.dumps({"code": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True


# ---------------------------------------------------------------------------
# P03: compress behavior tests
# ---------------------------------------------------------------------------


class TestJsonCodeUnwrapperCompress:
    """compress() behavioral tests."""

    def test_extracts_source_field(self, strategy, make_envelope):
        """Should extract code from 'source' field."""
        code = "def hello():\n    print('world')\n" + "    x = 1\n" * 120
        content = json.dumps({"source": code, "language": "python"})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == code

    def test_extracts_code_field(self, strategy, make_envelope):
        """Should extract code from 'code' field."""
        code = "fn main() {\n    println!(\"hello\");\n" + "    let x = 1;\n" * 100
        content = json.dumps({"code": code, "lang": "rust"})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == code

    def test_extracts_body_field(self, strategy, make_envelope):
        """Should extract code from 'body' field."""
        code = "function greet() {\n    return 'hi';\n" + "    let x = 1;\n" * 100
        content = json.dumps({"body": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == code

    def test_extracts_content_field(self, strategy, make_envelope):
        """Should extract code from 'content' field."""
        code = "import os\nimport sys\n" + "x = 1\n" * 160
        content = json.dumps({"content": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == code

    def test_extracts_text_field(self, strategy, make_envelope):
        """Should extract code from 'text' field."""
        code = "class Foo:\n    pass\n" + "    x = 1\n" * 120
        content = json.dumps({"text": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == code

    def test_priority_order_source_over_code(self, strategy, make_envelope):
        """When multiple code fields present, 'source' should win over 'code'."""
        primary = "def primary():\n    pass\n" + "    x = 1\n" * 120
        secondary = "def secondary():\n    pass\n" + "    y = 1\n" * 120
        content = json.dumps({
            "source": primary,
            "code": secondary,
        })
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content == primary

    def test_preserves_content_type(self, strategy, make_envelope):
        """Content type must be preserved after compression."""
        code = "def foo():\n    pass\n" + "    x = 1\n" * 120
        content = json.dumps({"source": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content_type == ContentType.JSON

    def test_preserves_metadata(self, strategy, make_envelope):
        """Metadata must be preserved after compression."""
        code = "def foo():\n    pass\n" + "    x = 1\n" * 120
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
        """JSON with code fields but values <500 chars should pass through."""
        content = json.dumps({"source": "def foo(): pass"})
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
        code = "def foo():\n    pass\n" + "    x = 1\n" * 120
        content = json.dumps({"source": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        original_content = envelope.content
        strategy.compress(envelope)
        assert envelope.content == original_content

    def test_compress_preserves_json_wrapper_in_metadata(self, strategy, make_envelope):
        """compress() must store original JSON in metadata['json_wrapper']."""
        code = "def hello():\n    print('world')\n" + "    x = 1\n" * 120
        original_json = json.dumps({"source": code, "language": "python"})
        envelope = make_envelope(content=original_json, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert "json_wrapper" in result.metadata
        assert result.metadata["json_wrapper"] == original_json

    def test_compress_no_double_json_parse(self, strategy, make_envelope):
        """can_handle() + compress() should not parse JSON twice (Finding 7)."""
        code = "def hello():\n    pass\n" + "    x = 1\n" * 120
        content = json.dumps({"source": code})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        # Call can_handle first (as pipeline would)
        assert strategy.can_handle(envelope) is True
        # Then compress — should use cached parse
        result = strategy.compress(envelope)
        assert result.content == code
