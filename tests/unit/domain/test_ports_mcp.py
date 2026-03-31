"""Tests for MCP-specific Protocol ports (ToolListProvider, ClientTransport).

Follows the same structural subtyping test pattern as test_ports.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

from token_sieve.domain.ports_mcp import ClientTransport, ToolListProvider
from token_sieve.domain.tool_metadata import ToolMetadata


class TestProtocolImports:
    """MCP Protocol interfaces are importable."""

    def test_import_tool_list_provider(self) -> None:
        assert ToolListProvider is not None

    def test_import_client_transport(self) -> None:
        assert ClientTransport is not None


class TestToolListProviderProtocol:
    """ToolListProvider structural subtyping tests."""

    def test_structural_subtyping(self) -> None:
        """A plain class with async list_tools() satisfies the protocol."""

        class MockToolListProvider:
            async def list_tools(self) -> list[ToolMetadata]:
                return [
                    ToolMetadata(
                        name="fetch",
                        title="Fetch URL",
                        description="Fetches a URL",
                        input_schema={"type": "object"},
                    )
                ]

        provider = MockToolListProvider()
        assert isinstance(provider, ToolListProvider)

    def test_list_tools_returns_tool_metadata(self) -> None:
        """list_tools returns a list of ToolMetadata."""

        class MockProvider:
            async def list_tools(self) -> list[ToolMetadata]:
                return [
                    ToolMetadata(
                        name="read",
                        title=None,
                        description="Read file",
                        input_schema={},
                    )
                ]

        provider = MockProvider()
        result = asyncio.run(provider.list_tools())
        assert len(result) == 1
        assert isinstance(result[0], ToolMetadata)
        assert result[0].name == "read"

    def test_non_conforming_class_fails_isinstance(self) -> None:
        """A class without list_tools does not satisfy the protocol."""

        class NotAProvider:
            pass

        assert not isinstance(NotAProvider(), ToolListProvider)


class TestClientTransportProtocol:
    """ClientTransport structural subtyping tests."""

    def test_structural_subtyping(self) -> None:
        """A plain class with async connect/disconnect satisfies the protocol."""

        class MockTransport:
            async def connect(self) -> tuple[Any, Any]:
                return ("read_stream", "write_stream")

            async def disconnect(self) -> None:
                pass

        transport = MockTransport()
        assert isinstance(transport, ClientTransport)

    def test_connect_returns_tuple(self) -> None:
        """connect() returns a tuple of (read_stream, write_stream)."""

        class MockTransport:
            async def connect(self) -> tuple[Any, Any]:
                return ("r", "w")

            async def disconnect(self) -> None:
                pass

        transport = MockTransport()
        result = asyncio.run(transport.connect())
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_disconnect_is_async(self) -> None:
        """disconnect() can be awaited without error."""

        class MockTransport:
            async def connect(self) -> tuple[Any, Any]:
                return ("r", "w")

            async def disconnect(self) -> None:
                pass

        transport = MockTransport()
        asyncio.run(transport.disconnect())

    def test_non_conforming_class_fails_isinstance(self) -> None:
        """A class without connect/disconnect does not satisfy the protocol."""

        class NotATransport:
            pass

        assert not isinstance(NotATransport(), ClientTransport)
