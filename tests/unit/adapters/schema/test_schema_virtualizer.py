"""Tests for SchemaVirtualizer -- Tier 1 lossless cleanup."""

from __future__ import annotations

import pytest

from token_sieve.adapters.schema.schema_virtualizer import SchemaVirtualizer
from token_sieve.domain.ports_schema import SchemaVirtualizerPort


# --- Sample tool schemas (representative MCP tools) ---

GITHUB_SEARCH_TOOL: dict = {
    "name": "search_repositories",
    "description": "Search for GitHub repositories matching a query.",
    "inputSchema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "title": "search_repositories",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query string",
            },
            "page": {
                "type": "integer",
                "description": "",
            },
            "per_page": {
                "type": "integer",
                "description": "Results per page",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

FILESYSTEM_READ_TOOL: dict = {
    "name": "read_file",
    "description": "Read contents of a file at the given path.",
    "inputSchema": {
        "type": "object",
        "title": "read_file",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute file path to read",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}

SINGLE_ONEOF_TOOL: dict = {
    "name": "get_item",
    "description": "Get an item by ID.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "id": {
                "oneOf": [{"type": "string"}],
                "description": "Item identifier",
            },
        },
        "required": ["id"],
    },
}


class TestSchemaVirtualizerProtocolConformance:
    """SchemaVirtualizer satisfies SchemaVirtualizerPort Protocol."""

    def test_isinstance_check(self) -> None:
        v = SchemaVirtualizer()
        assert isinstance(v, SchemaVirtualizerPort)


class TestTier1LosslessCleanup:
    """Tier 1 removes boilerplate without losing semantic content."""

    def test_removes_dollar_schema(self) -> None:
        """$schema field is stripped from inputSchema."""
        result = SchemaVirtualizer().virtualize([GITHUB_SEARCH_TOOL], tier=1)
        schema = result[0]["inputSchema"]
        assert "$schema" not in schema

    def test_removes_additional_properties_false(self) -> None:
        """additionalProperties: false is stripped (redundant for MCP)."""
        result = SchemaVirtualizer().virtualize([GITHUB_SEARCH_TOOL], tier=1)
        schema = result[0]["inputSchema"]
        assert "additionalProperties" not in schema

    def test_removes_empty_descriptions(self) -> None:
        """Empty description fields on properties are stripped."""
        result = SchemaVirtualizer().virtualize([GITHUB_SEARCH_TOOL], tier=1)
        page_prop = result[0]["inputSchema"]["properties"]["page"]
        assert "description" not in page_prop

    def test_strips_title_matching_name(self) -> None:
        """title field is stripped when it matches the tool name."""
        result = SchemaVirtualizer().virtualize([GITHUB_SEARCH_TOOL], tier=1)
        schema = result[0]["inputSchema"]
        assert "title" not in schema

    def test_flattens_single_item_oneof(self) -> None:
        """oneOf with single item is flattened to the item itself."""
        result = SchemaVirtualizer().virtualize([SINGLE_ONEOF_TOOL], tier=1)
        id_prop = result[0]["inputSchema"]["properties"]["id"]
        assert "oneOf" not in id_prop
        assert id_prop["type"] == "string"

    def test_preserves_semantic_content(self) -> None:
        """Non-empty descriptions, types, required fields preserved."""
        result = SchemaVirtualizer().virtualize([GITHUB_SEARCH_TOOL], tier=1)
        schema = result[0]["inputSchema"]
        assert schema["type"] == "object"
        assert schema["required"] == ["query"]
        query_prop = schema["properties"]["query"]
        assert query_prop["type"] == "string"
        assert query_prop["description"] == "Search query string"

    def test_preserves_tool_name_and_description(self) -> None:
        """Tool-level name and description are unchanged at Tier 1."""
        result = SchemaVirtualizer().virtualize([FILESYSTEM_READ_TOOL], tier=1)
        assert result[0]["name"] == "read_file"
        assert result[0]["description"] == "Read contents of a file at the given path."

    def test_multiple_tools_processed(self) -> None:
        """All tools in the list are processed."""
        tools = [GITHUB_SEARCH_TOOL, FILESYSTEM_READ_TOOL]
        result = SchemaVirtualizer().virtualize(tools, tier=1)
        assert len(result) == 2
        for tool in result:
            assert "$schema" not in tool["inputSchema"]
            assert "additionalProperties" not in tool["inputSchema"]


class TestGetFullSchema:
    """get_full_schema returns original uncompressed schemas."""

    def test_returns_original_after_virtualize(self) -> None:
        """Original schema is retrievable after virtualization."""
        v = SchemaVirtualizer()
        v.virtualize([GITHUB_SEARCH_TOOL], tier=1)
        original = v.get_full_schema("search_repositories")
        assert original is not None
        assert "$schema" in original["inputSchema"]

    def test_returns_none_for_unknown_tool(self) -> None:
        """Unknown tool returns None."""
        v = SchemaVirtualizer()
        assert v.get_full_schema("nonexistent") is None

    def test_original_not_mutated(self) -> None:
        """Virtualization does not mutate the stored original."""
        import copy

        v = SchemaVirtualizer()
        original_copy = copy.deepcopy(GITHUB_SEARCH_TOOL)
        v.virtualize([GITHUB_SEARCH_TOOL], tier=1)
        stored = v.get_full_schema("search_repositories")
        assert stored == original_copy


class TestTier1TokenReduction:
    """Tier 1 achieves measurable token reduction."""

    def test_token_reduction_measurable(self) -> None:
        """Tier 1 output is shorter than input (measured by JSON length)."""
        import json

        v = SchemaVirtualizer()
        original_len = sum(len(json.dumps(t)) for t in [GITHUB_SEARCH_TOOL])
        result = v.virtualize([GITHUB_SEARCH_TOOL], tier=1)
        compressed_len = sum(len(json.dumps(t)) for t in result)
        assert compressed_len < original_len


# --- Tier 2: Description Compression ---

VERBOSE_TOOL: dict = {
    "name": "analyze_code",
    "description": (
        "Analyze source code for potential issues, code smells, and opportunities "
        "for improvement. This tool performs static analysis on the provided code "
        "snippet and returns detailed findings. It supports multiple programming "
        "languages including Python, JavaScript, TypeScript, Go, and Rust. "
        "Example: analyze_code({code: 'def foo(): pass', language: 'python'}) "
        "returns a list of findings. Each finding includes severity, line number, "
        "and a description of the issue. The tool also provides suggestions for "
        "fixing each issue found. e.g. missing type hints, unused imports, etc."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "The source code to analyze. Must be valid syntax for the "
                    "specified language. Example: 'def hello(): print(\"world\")'. "
                    "Can include multiple functions and classes."
                ),
            },
            "language": {
                "type": "string",
                "description": "Programming language of the code.",
                "enum": ["python", "javascript", "typescript", "go", "rust"],
            },
            "severity_threshold": {
                "type": "string",
                "description": (
                    "Minimum severity level for reported findings. Options are "
                    "'info', 'warning', 'error', 'critical'. e.g. set to 'warning' "
                    "to filter out informational findings."
                ),
                "enum": ["info", "warning", "error", "critical"],
            },
        },
        "required": ["code", "language"],
    },
}

SHORT_TOOL: dict = {
    "name": "get_time",
    "description": "Get current UTC time.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "description": "Time format string.",
            },
        },
    },
}


class TestTier2DescriptionCompression:
    """Tier 2 compresses verbose descriptions while preserving semantics."""

    def test_long_tool_description_shortened(self) -> None:
        """Tool description over 100 tokens is compressed."""
        original_word_count = len(VERBOSE_TOOL["description"].split())
        result = SchemaVirtualizer().virtualize([VERBOSE_TOOL], tier=2)
        desc = result[0]["description"]
        compressed_word_count = len(desc.split())
        # Should be meaningfully shorter than original (at least 20% reduction)
        assert compressed_word_count < original_word_count * 0.8

    def test_examples_stripped_from_description(self) -> None:
        """Sentences containing 'Example:' or 'e.g.' are removed."""
        result = SchemaVirtualizer().virtualize([VERBOSE_TOOL], tier=2)
        desc = result[0]["description"]
        assert "Example:" not in desc
        assert "e.g." not in desc

    def test_short_description_unchanged(self) -> None:
        """Short descriptions (under threshold) are not modified."""
        result = SchemaVirtualizer().virtualize([SHORT_TOOL], tier=2)
        assert result[0]["description"] == "Get current UTC time."

    def test_enum_values_preserved(self) -> None:
        """Enum values in properties are never removed."""
        result = SchemaVirtualizer().virtualize([VERBOSE_TOOL], tier=2)
        lang_prop = result[0]["inputSchema"]["properties"]["language"]
        assert lang_prop["enum"] == ["python", "javascript", "typescript", "go", "rust"]

    def test_property_descriptions_compressed(self) -> None:
        """Long property descriptions are also compressed."""
        result = SchemaVirtualizer().virtualize([VERBOSE_TOOL], tier=2)
        code_prop = result[0]["inputSchema"]["properties"]["code"]
        desc = code_prop.get("description", "")
        # Should be shorter than original and have examples stripped
        assert "Example:" not in desc
        assert len(desc.split()) < len(VERBOSE_TOOL["inputSchema"]["properties"]["code"]["description"].split())

    def test_tier2_applies_tier1_first(self) -> None:
        """Tier 2 includes Tier 1 cleanup."""
        tool_with_boilerplate = {
            "name": "test_tool",
            "description": "A verbose test tool. " * 20,
            "inputSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        }
        result = SchemaVirtualizer().virtualize([tool_with_boilerplate], tier=2)
        assert "$schema" not in result[0]["inputSchema"]
        assert "additionalProperties" not in result[0]["inputSchema"]

    def test_types_preserved(self) -> None:
        """Property types are preserved through Tier 2."""
        result = SchemaVirtualizer().virtualize([VERBOSE_TOOL], tier=2)
        props = result[0]["inputSchema"]["properties"]
        assert props["code"]["type"] == "string"
        assert props["language"]["type"] == "string"
