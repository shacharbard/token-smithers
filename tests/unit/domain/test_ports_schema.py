"""Tests for SchemaVirtualizerPort Protocol."""

from __future__ import annotations

from token_sieve.domain.ports_schema import SchemaVirtualizerPort


class TestSchemaVirtualizerPortProtocol:
    """SchemaVirtualizerPort structural subtyping tests."""

    def test_conforming_class_satisfies_protocol(self) -> None:
        """A class with virtualize() and get_full_schema() satisfies the protocol."""

        class MockVirtualizer:
            def virtualize(
                self,
                tools: list[dict],
                *,
                tier: int = 3,
                usage_stats: dict[str, int] | None = None,
            ) -> list[dict]:
                return tools

            def get_full_schema(self, tool_name: str) -> dict | None:
                return None

        virtualizer = MockVirtualizer()
        assert isinstance(virtualizer, SchemaVirtualizerPort)

    def test_non_conforming_class_fails_isinstance(self) -> None:
        """A class without required methods does not satisfy the protocol."""

        class NotAVirtualizer:
            pass

        assert not isinstance(NotAVirtualizer(), SchemaVirtualizerPort)

    def test_missing_get_full_schema_fails(self) -> None:
        """A class with only virtualize() fails isinstance."""

        class PartialVirtualizer:
            def virtualize(self, tools: list[dict], *, tier: int = 3) -> list[dict]:
                return tools

        assert not isinstance(PartialVirtualizer(), SchemaVirtualizerPort)

    def test_virtualize_returns_list(self) -> None:
        """virtualize() returns a list of dicts."""

        class MockVirtualizer:
            def virtualize(
                self,
                tools: list[dict],
                *,
                tier: int = 3,
                usage_stats: dict[str, int] | None = None,
            ) -> list[dict]:
                return tools

            def get_full_schema(self, tool_name: str) -> dict | None:
                return None

        tools = [{"name": "test", "inputSchema": {}}]
        result = MockVirtualizer().virtualize(tools)
        assert isinstance(result, list)

    def test_get_full_schema_returns_dict_or_none(self) -> None:
        """get_full_schema() returns dict or None."""

        class MockVirtualizer:
            def virtualize(
                self,
                tools: list[dict],
                *,
                tier: int = 3,
                usage_stats: dict[str, int] | None = None,
            ) -> list[dict]:
                return tools

            def get_full_schema(self, tool_name: str) -> dict | None:
                if tool_name == "known":
                    return {"type": "object"}
                return None

        v = MockVirtualizer()
        assert v.get_full_schema("known") == {"type": "object"}
        assert v.get_full_schema("unknown") is None
