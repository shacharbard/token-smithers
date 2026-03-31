"""Smoke tests for the fake MCP server.

Spawns the fake server as a subprocess and verifies initialize,
tools/list, and tools/call round trips via the MCP SDK client.
"""
from __future__ import annotations

import json
import sys

import pytest
import pytest_asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


FAKE_SERVER_CMD = [sys.executable, "-m", "tests.helpers.fake_mcp_server"]


@pytest.fixture
def server_params() -> StdioServerParameters:
    return StdioServerParameters(command=FAKE_SERVER_CMD[0], args=FAKE_SERVER_CMD[1:])


@pytest.fixture
def custom_tools_params() -> StdioServerParameters:
    tools_json = json.dumps([
        {
            "name": "add",
            "description": "Add two numbers",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
        },
        {
            "name": "greet",
            "description": "Greet someone",
            "inputSchema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            },
        },
    ])
    return StdioServerParameters(
        command=FAKE_SERVER_CMD[0],
        args=FAKE_SERVER_CMD[1:] + ["--tools", tools_json],
    )


@pytest.mark.asyncio
class TestFakeMcpServer:
    """Smoke tests: spawn fake server, exercise MCP protocol."""

    async def test_initialize_and_list_default_tools(
        self, server_params: StdioServerParameters
    ) -> None:
        """Server responds to initialize + tools/list with default echo tool."""
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                tool_names = [t.name for t in result.tools]
                assert "echo" in tool_names

    async def test_call_tool_echoes_back(
        self, server_params: StdioServerParameters
    ) -> None:
        """tools/call returns tool name and arguments as JSON text."""
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "echo", arguments={"message": "hello"}
                )
                assert len(result.content) == 1
                payload = json.loads(result.content[0].text)
                assert payload["tool"] == "echo"
                assert payload["arguments"]["message"] == "hello"

    async def test_custom_tools_via_cli_arg(
        self, custom_tools_params: StdioServerParameters
    ) -> None:
        """--tools JSON arg configures which tools are listed."""
        async with stdio_client(custom_tools_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                tool_names = sorted(t.name for t in result.tools)
                assert tool_names == ["add", "greet"]

    async def test_call_custom_tool(
        self, custom_tools_params: StdioServerParameters
    ) -> None:
        """Calling a custom tool echoes its name and arguments."""
        async with stdio_client(custom_tools_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "add", arguments={"a": 1, "b": 2}
                )
                payload = json.loads(result.content[0].text)
                assert payload["tool"] == "add"
                assert payload["arguments"] == {"a": 1, "b": 2}
