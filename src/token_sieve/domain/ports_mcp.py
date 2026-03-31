"""MCP-specific domain port interfaces (Protocol classes).

Async Protocol interfaces for MCP proxy operations. These extend the domain
port pattern from Phase 01 (ports.py) with async methods required for MCP I/O.
Zero external dependencies -- only stdlib + domain model types.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from token_sieve.domain.tool_metadata import ToolMetadata


@runtime_checkable
class ToolListProvider(Protocol):
    """Provides the cached tool list from a backend MCP server."""

    async def list_tools(self) -> list[ToolMetadata]:
        """Return the list of tools available from the backend."""
        ...


@runtime_checkable
class ClientTransport(Protocol):
    """Abstracts stdio/SSE/HTTP transport for backend MCP connection.

    Implementations wrap the MCP SDK's transport context managers.
    connect() returns a (read_stream, write_stream) tuple compatible
    with mcp.ClientSession.
    """

    async def connect(self) -> tuple[Any, Any]:
        """Establish connection to the backend, returning (read, write) streams."""
        ...

    async def disconnect(self) -> None:
        """Gracefully close the backend connection."""
        ...
