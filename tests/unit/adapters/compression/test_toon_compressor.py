"""Tests for ToonCompressor adapter.

Inherits CompressionStrategyContract for uniform protocol compliance.
Verifies TOON columnar encoding for uniform JSON arrays.
"""

from __future__ import annotations

import json

import pytest

from tests.unit.adapters.conftest import CompressionStrategyContract
from token_sieve.adapters.compression.toon_compressor import ToonCompressor
from token_sieve.domain.model import ContentEnvelope, ContentType


@pytest.fixture()
def strategy():
    """Provide ToonCompressor for contract tests."""
    return ToonCompressor()


class TestToonCompressorContract(CompressionStrategyContract):
    """ToonCompressor must satisfy the CompressionStrategy contract."""


class TestToonCompressorSpecific:
    """TOON-specific behavioral tests."""

    def test_can_handle_uniform_json_array(self, strategy, make_envelope):
        """Uniform JSON array (list of dicts with same keys) is handled."""
        data = json.dumps([
            {"name": "foo", "size": 100},
            {"name": "bar", "size": 200},
        ])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_can_handle_rejects_non_uniform_array(self, strategy, make_envelope):
        """Non-uniform array (dicts with different keys) is rejected."""
        data = json.dumps([
            {"name": "foo", "size": 100},
            {"name": "bar", "color": "red"},
        ])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is False

    def test_can_handle_rejects_non_array_json(self, strategy, make_envelope):
        """Non-array JSON (object) is rejected."""
        data = json.dumps({"name": "foo", "size": 100})
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is False

    def test_can_handle_rejects_non_json(self, strategy, make_envelope):
        """Non-JSON content is rejected."""
        envelope = make_envelope(content="just plain text", content_type=ContentType.TEXT)
        assert strategy.can_handle(envelope) is False

    def test_can_handle_rejects_empty_array(self, strategy, make_envelope):
        """Empty array is rejected (no savings possible)."""
        data = json.dumps([])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is False

    def test_can_handle_rejects_single_item_array(self, strategy, make_envelope):
        """Single-item array is rejected (no savings from columnar encoding)."""
        data = json.dumps([{"name": "foo", "size": 100}])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is False

    def test_can_handle_rejects_already_transformed(self, strategy, make_envelope):
        """Already-transformed content (transformed_by set) is skipped."""
        data = json.dumps([
            {"name": "foo", "size": 100},
            {"name": "bar", "size": 200},
        ])
        envelope = make_envelope(
            content=data,
            content_type=ContentType.JSON,
            metadata={"transformed_by": "yaml_transcoder"},
        )
        assert strategy.can_handle(envelope) is False

    def test_can_handle_rejects_array_of_non_dicts(self, strategy, make_envelope):
        """Array of non-dict items (strings, numbers) is rejected."""
        data = json.dumps(["foo", "bar", "baz"])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is False

    def test_compress_produces_columnar_format(self, strategy, make_envelope):
        """Uniform JSON array is converted to tab-separated columnar format."""
        data = json.dumps([
            {"name": "foo", "size": 100},
            {"name": "bar", "size": 200},
        ])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)

        lines = result.content.strip().split("\n")
        assert lines[0] == "name\tsize"  # header row with keys (sorted)
        assert lines[1] == "foo\t100"
        assert lines[2] == "bar\t200"

    def test_compress_sets_transformed_by_metadata(self, strategy, make_envelope):
        """compress() sets transformed_by='toon_compressor' in metadata."""
        data = json.dumps([
            {"name": "foo", "size": 100},
            {"name": "bar", "size": 200},
        ])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.metadata["transformed_by"] == "toon_compressor"

    def test_compress_preserves_existing_metadata(self, strategy, make_envelope):
        """compress() preserves existing metadata while adding transformed_by."""
        data = json.dumps([
            {"name": "foo", "size": 100},
            {"name": "bar", "size": 200},
        ])
        envelope = make_envelope(
            content=data,
            content_type=ContentType.JSON,
            metadata={"tool_name": "list_files"},
        )
        result = strategy.compress(envelope)
        assert result.metadata["tool_name"] == "list_files"
        assert result.metadata["transformed_by"] == "toon_compressor"

    def test_compress_nested_objects_as_json_strings(self, strategy, make_envelope):
        """Nested objects in values are serialized as compact JSON strings."""
        data = json.dumps([
            {"name": "foo", "info": {"a": 1}},
            {"name": "bar", "info": {"b": 2}},
        ])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)

        lines = result.content.strip().split("\n")
        assert lines[0] == "info\tname"  # sorted column order
        # Nested objects become compact JSON strings
        assert "foo" in lines[1]
        assert '{"a": 1}' in lines[1]

    def test_compress_handles_none_values(self, strategy, make_envelope):
        """None/null values are represented correctly."""
        data = json.dumps([
            {"name": "foo", "value": None},
            {"name": "bar", "value": 42},
        ])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)

        lines = result.content.strip().split("\n")
        assert "None" in lines[1] or "null" in lines[1] or lines[1].endswith("\t")

    def test_compress_large_array_achieves_40_percent_savings(self, strategy, make_envelope):
        """10+ row uniform array achieves at least 40% size reduction."""
        rows = [
            {"filename": f"file_{i}.py", "size": i * 100, "modified": f"2024-01-{i:02d}"}
            for i in range(1, 21)
        ]
        data = json.dumps(rows)
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)

        original_size = len(data)
        compressed_size = len(result.content)
        savings = 1.0 - (compressed_size / original_size)
        assert savings >= 0.40, f"Expected >= 40% savings, got {savings:.1%}"

    def test_compress_preserves_content_type(self, strategy, make_envelope):
        """compress() preserves the content_type."""
        data = json.dumps([
            {"name": "foo", "size": 100},
            {"name": "bar", "size": 200},
        ])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content_type is ContentType.JSON

    def test_compress_handles_boolean_values(self, strategy, make_envelope):
        """Boolean values are represented correctly."""
        data = json.dumps([
            {"name": "foo", "active": True},
            {"name": "bar", "active": False},
        ])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)

        lines = result.content.strip().split("\n")
        assert lines[0] == "active\tname"  # sorted column order
        assert "True" in lines[1]
        assert "False" in lines[2]

    def test_compress_handles_pipe_in_values(self, strategy, make_envelope):
        """Tab delimiter avoids ambiguity from pipe characters in values."""
        data = json.dumps([
            {"cmd": "echo foo | grep bar", "exit": 0},
            {"cmd": "ls -la", "exit": 0},
        ])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        lines = result.content.strip().split("\n")
        assert len(lines) == 3  # header + 2 rows

        # Each row must have the same number of columns as the header
        header_cols = lines[0].split("\t")
        for i, line in enumerate(lines[1:]):
            row_cols = line.split("\t")
            assert len(row_cols) == len(header_cols), (
                f"Row {i} has {len(row_cols)} columns but header has "
                f"{len(header_cols)}. Delimiter collision in value."
            )
        # Verify the pipe character is preserved in the value
        assert "echo foo | grep bar" in lines[1]
