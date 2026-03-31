"""Stdio transport adapter wrapping the MCP SDK's stdio_client.

Provides an async context manager that spawns a backend MCP server
subprocess and yields a ready-to-use ClientSession.
"""
from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class StdioClientTransport:
    """Wraps MCP SDK stdio_client for backend server connections.

    Usage::

        transport = StdioClientTransport(command="python", args=["-m", "server"])
        async with transport.connect() as session:
            tools = await session.list_tools()
            result = await session.call_tool("tool_name", {"arg": "value"})
    """

    def __init__(
        self,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self.command = command
        self.args = args
        self.env = env
        self.cwd = cwd

    @contextlib.asynccontextmanager
    async def connect(self) -> AsyncGenerator[ClientSession, None]:
        """Spawn backend subprocess and yield an initialized ClientSession.

        The subprocess is terminated when the context manager exits.
        """
        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env,
            cwd=self.cwd,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
