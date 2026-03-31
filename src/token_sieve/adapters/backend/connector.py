"""Backend connector bridging domain ports with MCP backend sessions.

BackendConnector wraps a ClientSession and implements the BackendToolAdapter
protocol structurally. It provides list_tools() and call_tool() with error
boundary protection — backend failures return error content rather than
crashing the proxy.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import mcp.types as types
from mcp import ClientSession

logger = logging.getLogger(__name__)


class BackendConnector:
    """Bridges domain BackendToolAdapter protocol with an MCP ClientSession.

    Maintains a reference to one persistent session (injected at construction).
    Caches tool list after first fetch. Wraps every backend call in try/except
    to ensure the proxy never crashes due to backend failures.

    Satisfies ``BackendToolAdapter.call_tool()`` structurally.
    """

    def __init__(self, session: ClientSession) -> None:
        self._session = session
        self._tools_cache: list[types.Tool] | None = None

    async def list_tools(self) -> list[types.Tool]:
        """Return tools from backend, caching after first call.

        If the backend is unreachable, returns an empty list and logs the error.
        """
        if self._tools_cache is not None:
            return self._tools_cache
        try:
            result = await self._session.list_tools()
            self._tools_cache = list(result.tools)
            return self._tools_cache
        except Exception:
            logger.exception("Failed to list tools from backend")
            return []

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        """Forward a tool call to the backend session.

        On success, returns the backend's CallToolResult directly.
        On failure, returns an error CallToolResult with isError=True
        containing the exception message — the proxy never crashes.
        """
        try:
            return await self._session.call_tool(name, arguments)
        except Exception as exc:
            logger.exception(
                "Backend call_tool(%s) failed: %s", name, exc
            )
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Backend error: {exc}",
                    ),
                ],
                isError=True,
            )
