"""Fake MCP server for integration tests.

Runs as a subprocess over stdio transport. Handles:
- initialize / initialized handshake
- tools/list with configurable tool definitions
- tools/call echoing back tool name + arguments

Usage::

    python tests/helpers/fake_mcp_server.py
    python tests/helpers/fake_mcp_server.py --tools '[{"name":"add","description":"Add numbers","inputSchema":{"type":"object","properties":{"a":{"type":"number"}}}}]'
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import Server


def _build_tools(tools_json: str | None) -> list[types.Tool]:
    """Parse --tools JSON into MCP Tool objects, or return defaults."""
    if tools_json:
        raw: list[dict[str, Any]] = json.loads(tools_json)
        return [
            types.Tool(
                name=t["name"],
                description=t.get("description", ""),
                inputSchema=t.get(
                    "inputSchema",
                    {"type": "object", "properties": {}},
                ),
            )
            for t in raw
        ]
    # Default: one echo tool
    return [
        types.Tool(
            name="echo",
            description="Echoes back the input arguments",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Message to echo"},
                },
            },
        ),
    ]


def create_server(tools: list[types.Tool]) -> Server:
    """Build and return a low-level MCP Server with tool handlers."""
    server = Server("fake-mcp-server")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return tools

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent]:
        # Echo back the tool name and arguments as text content
        response = json.dumps(
            {"tool": name, "arguments": arguments or {}},
            sort_keys=True,
        )
        return [types.TextContent(type="text", text=response)]

    return server


async def _run(tools: list[types.Tool]) -> None:
    server = create_server(tools)
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fake MCP server for tests")
    parser.add_argument(
        "--tools",
        type=str,
        default=None,
        help="JSON array of tool definitions",
    )
    args = parser.parse_args(argv)
    tools = _build_tools(args.tools)
    asyncio.run(_run(tools))


if __name__ == "__main__":
    main()
