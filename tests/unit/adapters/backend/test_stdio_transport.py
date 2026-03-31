"""Tests for StdioClientTransport adapter.

Verifies the transport wraps the MCP SDK's stdio_client correctly,
spawning a backend subprocess and providing read/write streams.
"""
from __future__ import annotations

import json
import sys

import pytest
from mcp import ClientSession

from token_sieve.adapters.backend.stdio_transport import StdioClientTransport


FAKE_SERVER_MODULE = "tests.helpers.fake_mcp_server"


class TestStdioClientTransportConstruction:
    """Construction and parameter validation."""

    def test_construct_with_minimal_params(self) -> None:
        transport = StdioClientTransport(
            command=sys.executable,
            args=["-m", FAKE_SERVER_MODULE],
        )
        assert transport.command == sys.executable
        assert transport.args == ["-m", FAKE_SERVER_MODULE]
        assert transport.env is None
        assert transport.cwd is None

    def test_construct_with_all_params(self) -> None:
        transport = StdioClientTransport(
            command=sys.executable,
            args=["-m", FAKE_SERVER_MODULE],
            env={"FOO": "bar"},
            cwd="/tmp",
        )
        assert transport.env == {"FOO": "bar"}
        assert transport.cwd == "/tmp"


@pytest.mark.asyncio
class TestStdioClientTransportConnect:
    """Connection lifecycle — connect, use session, disconnect."""

    async def test_connect_yields_working_session(self) -> None:
        """connect() returns read/write streams usable with ClientSession."""
        transport = StdioClientTransport(
            command=sys.executable,
            args=["-m", FAKE_SERVER_MODULE],
        )
        async with transport.connect() as session:
            assert isinstance(session, ClientSession)
            # Verify the session works — list tools
            result = await session.list_tools()
            tool_names = [t.name for t in result.tools]
            assert "echo" in tool_names

    async def test_session_can_call_tools(self) -> None:
        """Connected session can call tools and get results."""
        transport = StdioClientTransport(
            command=sys.executable,
            args=["-m", FAKE_SERVER_MODULE],
        )
        async with transport.connect() as session:
            result = await session.call_tool("echo", arguments={"message": "test"})
            payload = json.loads(result.content[0].text)
            assert payload["tool"] == "echo"
            assert payload["arguments"]["message"] == "test"

    async def test_connect_with_custom_tools(self) -> None:
        """Transport works with custom tool definitions."""
        tools_json = json.dumps([
            {"name": "multiply", "description": "Multiply numbers"},
        ])
        transport = StdioClientTransport(
            command=sys.executable,
            args=["-m", FAKE_SERVER_MODULE, "--tools", tools_json],
        )
        async with transport.connect() as session:
            result = await session.list_tools()
            assert result.tools[0].name == "multiply"

    async def test_cleanup_after_context_exit(self) -> None:
        """After exiting the context manager, resources are cleaned up."""
        transport = StdioClientTransport(
            command=sys.executable,
            args=["-m", FAKE_SERVER_MODULE],
        )
        async with transport.connect() as session:
            # Session works inside context
            await session.list_tools()
        # After exit, we just verify no exception on cleanup
        # (the subprocess should be terminated)

    async def test_error_on_invalid_command(self) -> None:
        """Transport raises on nonexistent binary."""
        transport = StdioClientTransport(
            command="/nonexistent/binary/xyz",
            args=[],
        )
        with pytest.raises((FileNotFoundError, OSError)):
            async with transport.connect() as _session:
                pass
