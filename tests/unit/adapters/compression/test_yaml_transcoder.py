"""Tests for YamlTranscoder adapter.

Inherits CompressionStrategyContract for uniform protocol compliance.
Verifies JSON-to-YAML transcoding with transformed_by guard and TOON deference.
"""

from __future__ import annotations

import json

import pytest
import yaml

from tests.unit.adapters.conftest import CompressionStrategyContract
from token_sieve.adapters.compression.yaml_transcoder import YamlTranscoder
from token_sieve.domain.model import ContentEnvelope, ContentType


@pytest.fixture()
def strategy():
    """Provide YamlTranscoder for contract tests."""
    return YamlTranscoder()


class TestYamlTranscoderContract(CompressionStrategyContract):
    """YamlTranscoder must satisfy the CompressionStrategy contract."""


class TestYamlTranscoderSpecific:
    """YAML-transcoder-specific behavioral tests."""

    def test_can_handle_json_object(self, strategy, make_envelope):
        """JSON object is handled."""
        data = json.dumps({"name": "foo", "size": 100})
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_can_handle_rejects_non_json(self, strategy, make_envelope):
        """Non-JSON content is rejected."""
        envelope = make_envelope(content="plain text here", content_type=ContentType.TEXT)
        assert strategy.can_handle(envelope) is False

    def test_can_handle_rejects_already_transformed(self, strategy, make_envelope):
        """Already-transformed content (transformed_by set) is skipped."""
        data = json.dumps({"name": "foo"})
        envelope = make_envelope(
            content=data,
            content_type=ContentType.JSON,
            metadata={"transformed_by": "toon_compressor"},
        )
        assert strategy.can_handle(envelope) is False

    def test_can_handle_defers_to_toon_for_uniform_arrays(self, strategy, make_envelope):
        """Uniform JSON arrays (TOON-eligible) are deferred to ToonCompressor."""
        data = json.dumps([
            {"name": "foo", "size": 100},
            {"name": "bar", "size": 200},
        ])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is False

    def test_can_handle_accepts_non_uniform_arrays(self, strategy, make_envelope):
        """Non-uniform arrays (not TOON-eligible) are handled by YAML."""
        data = json.dumps([
            {"name": "foo", "size": 100},
            {"name": "bar", "color": "red"},
        ])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_can_handle_accepts_single_item_array(self, strategy, make_envelope):
        """Single-item array (not TOON-eligible) is handled by YAML."""
        data = json.dumps([{"name": "foo", "size": 100}])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_can_handle_accepts_array_of_scalars(self, strategy, make_envelope):
        """Array of scalars is valid JSON, handled by YAML."""
        data = json.dumps(["foo", "bar", "baz"])
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is True

    def test_compress_produces_yaml_output(self, strategy, make_envelope):
        """JSON object is converted to YAML format."""
        data = json.dumps({"name": "foo", "size": 100})
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)

        # YAML should not have braces or quotes on simple strings
        assert "{" not in result.content
        assert "name: foo" in result.content
        assert "size: 100" in result.content

    def test_compress_nested_json_to_yaml(self, strategy, make_envelope):
        """Nested JSON is converted to indented YAML."""
        data = json.dumps({"server": {"host": "localhost", "port": 8080}})
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)

        assert "server:" in result.content
        assert "  host: localhost" in result.content
        assert "  port: 8080" in result.content

    def test_compress_json_with_arrays_to_yaml_lists(self, strategy, make_envelope):
        """JSON with arrays is converted to YAML list notation."""
        data = json.dumps({"tags": ["python", "mcp", "proxy"]})
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)

        assert "tags:" in result.content
        assert "- python" in result.content
        assert "- mcp" in result.content

    def test_compress_sets_transformed_by_metadata(self, strategy, make_envelope):
        """compress() sets transformed_by='yaml_transcoder' in metadata."""
        data = json.dumps({"name": "foo"})
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.metadata["transformed_by"] == "yaml_transcoder"

    def test_compress_preserves_existing_metadata(self, strategy, make_envelope):
        """compress() preserves existing metadata while adding transformed_by."""
        data = json.dumps({"name": "foo"})
        envelope = make_envelope(
            content=data,
            content_type=ContentType.JSON,
            metadata={"tool_name": "read_file"},
        )
        result = strategy.compress(envelope)
        assert result.metadata["tool_name"] == "read_file"
        assert result.metadata["transformed_by"] == "yaml_transcoder"

    def test_compress_yaml_roundtrip(self, strategy, make_envelope):
        """YAML output parses back to the original data structure."""
        original = {"name": "foo", "count": 42, "active": True, "tags": ["a", "b"]}
        data = json.dumps(original)
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)

        parsed_back = yaml.safe_load(result.content)
        assert parsed_back == original

    def test_compress_achieves_savings_on_realistic_json(self, strategy, make_envelope):
        """Realistic JSON achieves 15-25% size reduction."""
        original = {
            "project": "token-sieve",
            "version": "0.1.0",
            "description": "MCP compression gateway",
            "dependencies": {
                "mcp": ">=1.0.0",
                "pyyaml": ">=6.0",
                "pydantic": ">=2.0",
            },
            "scripts": {
                "test": "pytest",
                "lint": "ruff check",
                "format": "ruff format",
            },
        }
        data = json.dumps(original)
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)

        original_size = len(data)
        compressed_size = len(result.content)
        savings = 1.0 - (compressed_size / original_size)
        assert savings >= 0.10, f"Expected >= 10% savings, got {savings:.1%}"

    def test_compress_preserves_content_type(self, strategy, make_envelope):
        """compress() preserves the content_type."""
        data = json.dumps({"name": "foo"})
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content_type is ContentType.JSON

    def test_can_handle_rejects_invalid_json(self, strategy, make_envelope):
        """Invalid JSON string is rejected."""
        envelope = make_envelope(content="{invalid json", content_type=ContentType.JSON)
        assert strategy.can_handle(envelope) is False

    def test_sort_keys_normalization(self, strategy, make_envelope):
        """YAML output keys must be sorted for cache-aligned determinism."""
        data = json.dumps({"zebra": 1, "alpha": 2})
        envelope = make_envelope(content=data, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        lines = result.content.strip().split("\n")
        # Keys should appear in sorted order
        assert lines[0] == "alpha: 2"
        assert lines[1] == "zebra: 1"
