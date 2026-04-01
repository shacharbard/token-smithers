"""Tests for ToolListTransformer Protocol (reranking port).

Follows the same structural subtyping test pattern as test_ports_mcp.py.
"""

from __future__ import annotations

from token_sieve.domain.ports_rerank import ToolListTransformer
from token_sieve.domain.tool_metadata import ToolMetadata


def _make_tool(name: str = "tool-a") -> ToolMetadata:
    """Helper to create a ToolMetadata for testing."""
    return ToolMetadata(
        name=name,
        title=None,
        description=f"Description for {name}",
        input_schema={"type": "object"},
    )


class TestProtocolImports:
    """ToolListTransformer Protocol is importable."""

    def test_import_tool_list_transformer(self) -> None:
        assert ToolListTransformer is not None


class TestToolListTransformerProtocol:
    """ToolListTransformer structural subtyping tests."""

    def test_structural_subtyping(self) -> None:
        """A plain class with transform() + record_call() satisfies the protocol."""

        class MockTransformer:
            def transform(self, tools: list[ToolMetadata]) -> list[ToolMetadata]:
                return tools

            def record_call(self, tool_name: str) -> None:
                pass

        transformer = MockTransformer()
        assert isinstance(transformer, ToolListTransformer)

    def test_transform_returns_tool_metadata_list(self) -> None:
        """transform() returns a list of ToolMetadata."""

        class MockTransformer:
            def transform(self, tools: list[ToolMetadata]) -> list[ToolMetadata]:
                return tools

            def record_call(self, tool_name: str) -> None:
                pass

        tools = [_make_tool("a"), _make_tool("b")]
        result = MockTransformer().transform(tools)
        assert len(result) == 2
        assert all(isinstance(t, ToolMetadata) for t in result)

    def test_transform_empty_list(self) -> None:
        """transform() with empty list returns empty list."""

        class MockTransformer:
            def transform(self, tools: list[ToolMetadata]) -> list[ToolMetadata]:
                return tools

            def record_call(self, tool_name: str) -> None:
                pass

        result = MockTransformer().transform([])
        assert result == []

    def test_record_call_accepts_string(self) -> None:
        """record_call() accepts a tool name string."""

        class MockTransformer:
            def transform(self, tools: list[ToolMetadata]) -> list[ToolMetadata]:
                return tools

            def record_call(self, tool_name: str) -> None:
                pass

        # Should not raise
        MockTransformer().record_call("some-tool")

    def test_non_conforming_class_fails_isinstance(self) -> None:
        """A class without transform/record_call does not satisfy the protocol."""

        class NotATransformer:
            pass

        assert not isinstance(NotATransformer(), ToolListTransformer)

    def test_missing_record_call_fails(self) -> None:
        """A class with transform but no record_call fails isinstance."""

        class PartialTransformer:
            def transform(self, tools: list[ToolMetadata]) -> list[ToolMetadata]:
                return tools

        assert not isinstance(PartialTransformer(), ToolListTransformer)
