"""Tests for BackendConnector adapter.

Verifies the connector bridges domain BackendToolAdapter protocol with
a real MCP backend session, including error boundaries and session reuse.
"""
from __future__ import annotations

import json
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from token_sieve.adapters.backend.connector import BackendConnector
from token_sieve.adapters.backend.stdio_transport import StdioClientTransport
from token_sieve.domain.ports import BackendToolAdapter


FAKE_SERVER_MODULE = "tests.helpers.fake_mcp_server"


def _make_transport() -> StdioClientTransport:
    return StdioClientTransport(
        command=sys.executable,
        args=["-m", FAKE_SERVER_MODULE],
    )


def _make_custom_transport(tools: list[dict[str, Any]]) -> StdioClientTransport:
    return StdioClientTransport(
        command=sys.executable,
        args=["-m", FAKE_SERVER_MODULE, "--tools", json.dumps(tools)],
    )


@pytest.mark.asyncio
class TestBackendConnectorListTools:
    """list_tools() returns tool metadata from backend."""

    async def test_list_tools_returns_tool_info(self) -> None:
        """list_tools returns list of tool info dicts from backend."""
        transport = _make_transport()
        async with transport.connect() as session:
            connector = BackendConnector(session)
            tools = await connector.list_tools()
            assert len(tools) >= 1
            assert any(t.name == "echo" for t in tools)

    async def test_list_tools_with_custom_tools(self) -> None:
        """list_tools reflects the backend's configured tools."""
        transport = _make_custom_transport([
            {"name": "add", "description": "Add numbers"},
            {"name": "sub", "description": "Subtract numbers"},
        ])
        async with transport.connect() as session:
            connector = BackendConnector(session)
            tools = await connector.list_tools()
            names = sorted(t.name for t in tools)
            assert names == ["add", "sub"]

    async def test_list_tools_caches_result(self) -> None:
        """Second list_tools call returns cached result (no backend round trip)."""
        transport = _make_transport()
        async with transport.connect() as session:
            connector = BackendConnector(session)
            tools1 = await connector.list_tools()
            tools2 = await connector.list_tools()
            # Same object reference => cached
            assert tools1 is tools2


@pytest.mark.asyncio
class TestBackendConnectorCallTool:
    """call_tool() forwards to backend and returns result."""

    async def test_call_tool_returns_result(self) -> None:
        """call_tool forwards name + arguments and returns content."""
        transport = _make_transport()
        async with transport.connect() as session:
            connector = BackendConnector(session)
            result = await connector.call_tool("echo", {"message": "hello"})
            assert result.content is not None
            assert len(result.content) >= 1
            payload = json.loads(result.content[0].text)
            assert payload["tool"] == "echo"
            assert payload["arguments"]["message"] == "hello"

    async def test_call_tool_with_empty_arguments(self) -> None:
        """call_tool works with empty arguments dict."""
        transport = _make_transport()
        async with transport.connect() as session:
            connector = BackendConnector(session)
            result = await connector.call_tool("echo", {})
            payload = json.loads(result.content[0].text)
            assert payload["arguments"] == {}


@pytest.mark.asyncio
class TestBackendConnectorErrorBoundary:
    """Error handling: backend failures return error content, not proxy crash."""

    async def test_backend_exception_returns_error_content(self) -> None:
        """When backend session raises, connector returns error result."""
        mock_session = AsyncMock(spec=ClientSession)
        mock_session.call_tool.side_effect = Exception("Connection lost")

        connector = BackendConnector(mock_session)
        result = await connector.call_tool("broken_tool", {"x": 1})

        assert result.isError is True
        assert len(result.content) >= 1
        assert "Connection lost" in result.content[0].text

    async def test_backend_timeout_returns_error_content(self) -> None:
        """Timeout errors are caught and returned as error content."""
        mock_session = AsyncMock(spec=ClientSession)
        mock_session.call_tool.side_effect = TimeoutError("Backend timed out")

        connector = BackendConnector(mock_session)
        result = await connector.call_tool("slow_tool", {})

        assert result.isError is True
        assert "timed out" in result.content[0].text.lower()

    async def test_list_tools_error_returns_empty_list(self) -> None:
        """When list_tools fails on backend, return empty list."""
        mock_session = AsyncMock(spec=ClientSession)
        mock_session.list_tools.side_effect = Exception("Backend unreachable")

        connector = BackendConnector(mock_session)
        tools = await connector.list_tools()
        assert tools == []


@pytest.mark.asyncio
class TestBackendConnectorSessionReuse:
    """Persistent session: multiple calls reuse the same session."""

    async def test_multiple_calls_reuse_session(self) -> None:
        """Multiple call_tool invocations use the same injected session."""
        transport = _make_transport()
        async with transport.connect() as session:
            connector = BackendConnector(session)
            r1 = await connector.call_tool("echo", {"msg": "first"})
            r2 = await connector.call_tool("echo", {"msg": "second"})
            # Both should succeed — same session, no reconnection
            p1 = json.loads(r1.content[0].text)
            p2 = json.loads(r2.content[0].text)
            assert p1["arguments"]["msg"] == "first"
            assert p2["arguments"]["msg"] == "second"

    async def test_list_then_call_on_same_session(self) -> None:
        """list_tools + call_tool work sequentially on same session."""
        transport = _make_transport()
        async with transport.connect() as session:
            connector = BackendConnector(session)
            tools = await connector.list_tools()
            assert len(tools) >= 1
            result = await connector.call_tool("echo", {"test": True})
            payload = json.loads(result.content[0].text)
            assert payload["tool"] == "echo"


class TestBackendConnectorProtocolCompliance:
    """BackendConnector satisfies BackendToolAdapter protocol structurally."""

    def test_satisfies_backend_tool_adapter(self) -> None:
        """BackendConnector has call_tool method matching the protocol."""
        mock_session = MagicMock(spec=ClientSession)
        connector = BackendConnector(mock_session)
        # Structural subtyping check: has call_tool with right signature
        assert hasattr(connector, "call_tool")
        assert callable(connector.call_tool)
