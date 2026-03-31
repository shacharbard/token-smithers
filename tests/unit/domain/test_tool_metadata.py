"""Tests for ToolMetadata frozen value object.

Follows the frozen dataclass test pattern from test_model.py.
"""

from __future__ import annotations

import pytest

from token_sieve.domain.tool_metadata import ToolMetadata


class TestToolMetadataConstruction:
    """ToolMetadata can be constructed with required and optional fields."""

    def test_minimal_construction(self) -> None:
        tm = ToolMetadata(name="fetch", title=None, description="Fetch URL")
        assert tm.name == "fetch"
        assert tm.title is None
        assert tm.description == "Fetch URL"
        assert tm.input_schema == {}
        assert tm.server_id == "default"

    def test_full_construction(self) -> None:
        schema = {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        }
        tm = ToolMetadata(
            name="fetch",
            title="Website Fetcher",
            description="Fetches a website",
            input_schema=schema,
            server_id="backend-1",
        )
        assert tm.name == "fetch"
        assert tm.title == "Website Fetcher"
        assert tm.description == "Fetches a website"
        assert tm.input_schema == schema
        assert tm.server_id == "backend-1"

    def test_default_server_id(self) -> None:
        tm = ToolMetadata(name="t", title=None, description="d")
        assert tm.server_id == "default"

    def test_default_input_schema_is_empty_dict(self) -> None:
        tm = ToolMetadata(name="t", title=None, description="d")
        assert tm.input_schema == {}


class TestToolMetadataImmutability:
    """ToolMetadata is frozen -- field assignment raises."""

    def test_cannot_assign_name(self) -> None:
        tm = ToolMetadata(name="fetch", title=None, description="d")
        with pytest.raises(AttributeError):
            tm.name = "other"  # type: ignore[misc]

    def test_cannot_assign_title(self) -> None:
        tm = ToolMetadata(name="fetch", title="X", description="d")
        with pytest.raises(AttributeError):
            tm.title = "Y"  # type: ignore[misc]

    def test_cannot_assign_description(self) -> None:
        tm = ToolMetadata(name="fetch", title=None, description="d")
        with pytest.raises(AttributeError):
            tm.description = "other"  # type: ignore[misc]

    def test_cannot_assign_input_schema(self) -> None:
        tm = ToolMetadata(name="fetch", title=None, description="d")
        with pytest.raises(AttributeError):
            tm.input_schema = {}  # type: ignore[misc]

    def test_cannot_assign_server_id(self) -> None:
        tm = ToolMetadata(name="fetch", title=None, description="d")
        with pytest.raises(AttributeError):
            tm.server_id = "other"  # type: ignore[misc]


class TestToolMetadataEquality:
    """ToolMetadata supports equality and hashing."""

    def test_equal_instances(self) -> None:
        a = ToolMetadata(name="fetch", title=None, description="d")
        b = ToolMetadata(name="fetch", title=None, description="d")
        assert a == b

    def test_different_name_not_equal(self) -> None:
        a = ToolMetadata(name="fetch", title=None, description="d")
        b = ToolMetadata(name="read", title=None, description="d")
        assert a != b

    def test_different_server_id_not_equal(self) -> None:
        a = ToolMetadata(name="fetch", title=None, description="d", server_id="a")
        b = ToolMetadata(name="fetch", title=None, description="d", server_id="b")
        assert a != b

    def test_usable_in_set(self) -> None:
        a = ToolMetadata(name="fetch", title=None, description="d")
        b = ToolMetadata(name="fetch", title=None, description="d")
        c = ToolMetadata(name="read", title=None, description="d")
        s = {a, b, c}
        assert len(s) == 2

    def test_usable_as_dict_key(self) -> None:
        tm = ToolMetadata(name="fetch", title=None, description="d")
        d = {tm: "value"}
        assert d[tm] == "value"


class TestToolMetadataInputSchema:
    """input_schema preserves full JSON Schema dict."""

    def test_preserves_nested_schema(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "recursive": {"type": "boolean", "default": False},
            },
            "required": ["path"],
        }
        tm = ToolMetadata(
            name="read_file",
            title="Read File",
            description="Reads a file",
            input_schema=schema,
        )
        assert tm.input_schema["type"] == "object"
        assert "path" in tm.input_schema["properties"]
        assert tm.input_schema["required"] == ["path"]

    def test_schema_with_nested_objects(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "options": {
                    "type": "object",
                    "properties": {
                        "format": {"type": "string", "enum": ["json", "text"]},
                    },
                }
            },
        }
        tm = ToolMetadata(
            name="convert",
            title=None,
            description="Convert data",
            input_schema=schema,
        )
        nested = tm.input_schema["properties"]["options"]["properties"]
        assert nested["format"]["enum"] == ["json", "text"]
