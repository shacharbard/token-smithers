"""Integration tests: full MCP round-trip through proxy.

Tests verify the complete data path:
  fake client -> ProxyServer -> fake backend MCP server

Uses anyio memory streams for in-process MCP connections (no subprocess).
"""
from __future__ import annotations

import json
from typing import Any

import anyio
import pytest
from mcp import types
from mcp.client.session import ClientSession
from mcp.server.lowlevel import Server

from token_sieve.adapters.backend.connector import BackendConnector
from token_sieve.adapters.compression.passthrough import PassthroughStrategy
from token_sieve.adapters.compression.truncation import TruncationCompressor
from token_sieve.adapters.dedup.window_dedup import WindowDeduplicationStrategy
from token_sieve.domain.counters import CharEstimateCounter
from token_sieve.domain.model import ContentType
from token_sieve.domain.pipeline import CompressionPipeline
from token_sieve.domain.session import SessionContext
from token_sieve.server.metrics_sink import StderrMetricsSink
from token_sieve.server.proxy import ProxyServer
from token_sieve.server.tool_filter import ToolFilter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BACKEND_TOOLS = [
    types.Tool(
        name="echo",
        description="Echoes input",
        inputSchema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
        },
    ),
    types.Tool(
        name="big_read",
        description="Returns large content",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="secret_tool",
        description="Should be blocked",
        inputSchema={"type": "object", "properties": {}},
    ),
]

BIG_CONTENT = "x" * 80_000  # ~20K tokens at 4 chars/token


def _create_backend_server() -> Server:
    """Build a fake backend MCP server."""
    server = Server("fake-backend")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return BACKEND_TOOLS

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent]:
        args = arguments or {}
        if name == "echo":
            msg = args.get("message", "")
            return [types.TextContent(type="text", text=msg)]
        if name == "big_read":
            return [types.TextContent(type="text", text=BIG_CONTENT)]
        if name == "secret_tool":
            return [types.TextContent(type="text", text="secret data")]
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"tool": name, "arguments": args}),
            )
        ]

    return server


def _create_proxy(
    backend_connector: BackendConnector,
    strategy: str = "passthrough",
    blocked_tools: list[str] | None = None,
) -> ProxyServer:
    """Build a ProxyServer with configurable strategy and filter."""
    counter = CharEstimateCounter()
    pipeline = CompressionPipeline(counter=counter)

    if strategy == "truncation":
        pipeline.register(
            ContentType.TEXT,
            TruncationCompressor(max_tokens=100, counter=counter),
        )
    else:
        pipeline.register(ContentType.TEXT, PassthroughStrategy())

    if blocked_tools:
        tool_filter = ToolFilter(
            mode="blocklist",
            names=frozenset(blocked_tools),
        )
    else:
        tool_filter = ToolFilter(mode="passthrough")

    sink = StderrMetricsSink()

    return ProxyServer(
        backend_connector=backend_connector,
        tool_filter=tool_filter,
        pipeline=pipeline,
        metrics_sink=sink,
    )


async def _run_with_client(
    proxy: ProxyServer,
    client_fn,
) -> Any:
    """Connect a client to the proxy's MCP server via memory streams.

    Sets up two pairs of memory streams (client->proxy, proxy->client)
    and runs both sides concurrently.
    """
    # Streams: proxy reads from client_to_proxy, writes to proxy_to_client
    client_to_proxy_send, client_to_proxy_recv = anyio.create_memory_object_stream[
        Any
    ](100)
    proxy_to_client_send, proxy_to_client_recv = anyio.create_memory_object_stream[
        Any
    ](100)

    result_holder: list[Any] = []

    async def run_proxy():
        await proxy._server.run(
            client_to_proxy_recv,
            proxy_to_client_send,
            proxy._server.create_initialization_options(),
        )

    async def run_client():
        async with ClientSession(
            proxy_to_client_recv, client_to_proxy_send
        ) as session:
            await session.initialize()
            result = await client_fn(session)
            result_holder.append(result)

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_proxy)
        tg.start_soon(run_client)

    return result_holder[0] if result_holder else None


async def _setup_backend_and_proxy(
    strategy: str = "passthrough",
    blocked_tools: list[str] | None = None,
) -> tuple[ProxyServer, Server]:
    """Create backend server and proxy connected via memory streams.

    Returns the proxy (which has a BackendConnector wired to the backend).
    The backend runs in a task group managed by the caller.
    """
    # We need to connect the proxy's BackendConnector to the backend server
    # via memory streams, then use the proxy's MCP server for client connections.
    backend_server = _create_backend_server()

    # Create streams for proxy-to-backend connection
    proxy_to_backend_send, proxy_to_backend_recv = anyio.create_memory_object_stream[
        Any
    ](100)
    backend_to_proxy_send, backend_to_proxy_recv = anyio.create_memory_object_stream[
        Any
    ](100)

    return backend_server, proxy_to_backend_send, proxy_to_backend_recv, backend_to_proxy_send, backend_to_proxy_recv


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMcpRoundTrip:
    """Full MCP round-trip: client -> proxy -> backend."""

    @pytest.mark.anyio
    async def test_tools_list_returns_filtered_tools(self) -> None:
        """tools/list returns backend tools minus blocked ones."""
        backend_server = _create_backend_server()

        proxy_to_backend_send, proxy_to_backend_recv = anyio.create_memory_object_stream[Any](100)
        backend_to_proxy_send, backend_to_proxy_recv = anyio.create_memory_object_stream[Any](100)

        async def run_test():
            result_tools: list[types.Tool] = []

            async def run_backend():
                await backend_server.run(
                    proxy_to_backend_recv,
                    backend_to_proxy_send,
                    backend_server.create_initialization_options(),
                )

            async def run_client_proxy():
                async with ClientSession(
                    backend_to_proxy_recv, proxy_to_backend_send
                ) as backend_session:
                    await backend_session.initialize()

                    connector = BackendConnector(backend_session)
                    proxy = _create_proxy(
                        connector, blocked_tools=["secret_tool"]
                    )

                    async def client_fn(session: ClientSession):
                        result = await session.list_tools()
                        return list(result.tools)

                    tools = await _run_with_client(proxy, client_fn)
                    result_tools.extend(tools)

            async with anyio.create_task_group() as tg:
                tg.start_soon(run_backend)
                tg.start_soon(run_client_proxy)

            return result_tools

        tools = await run_test()
        tool_names = [t.name for t in tools]
        assert "echo" in tool_names
        assert "big_read" in tool_names
        assert "secret_tool" not in tool_names

    @pytest.mark.anyio
    async def test_tools_call_passthrough_returns_backend_result(self) -> None:
        """tools/call with passthrough compression returns backend result unchanged."""
        backend_server = _create_backend_server()

        proxy_to_backend_send, proxy_to_backend_recv = anyio.create_memory_object_stream[Any](100)
        backend_to_proxy_send, backend_to_proxy_recv = anyio.create_memory_object_stream[Any](100)

        async def run_test():
            call_result_holder: list[types.CallToolResult] = []

            async def run_backend():
                await backend_server.run(
                    proxy_to_backend_recv,
                    backend_to_proxy_send,
                    backend_server.create_initialization_options(),
                )

            async def run_client_proxy():
                async with ClientSession(
                    backend_to_proxy_recv, proxy_to_backend_send
                ) as backend_session:
                    await backend_session.initialize()

                    connector = BackendConnector(backend_session)
                    proxy = _create_proxy(connector, strategy="passthrough")

                    async def client_fn(session: ClientSession):
                        return await session.call_tool(
                            "echo", {"message": "hello world"}
                        )

                    result = await _run_with_client(proxy, client_fn)
                    call_result_holder.append(result)

            async with anyio.create_task_group() as tg:
                tg.start_soon(run_backend)
                tg.start_soon(run_client_proxy)

            return call_result_holder[0]

        result = await run_test()
        assert result.content[0].text == "hello world"

    @pytest.mark.anyio
    async def test_tools_call_truncation_reduces_large_results(self) -> None:
        """tools/call with truncation compression reduces large content."""
        backend_server = _create_backend_server()

        proxy_to_backend_send, proxy_to_backend_recv = anyio.create_memory_object_stream[Any](100)
        backend_to_proxy_send, backend_to_proxy_recv = anyio.create_memory_object_stream[Any](100)

        async def run_test():
            call_result_holder: list[types.CallToolResult] = []

            async def run_backend():
                await backend_server.run(
                    proxy_to_backend_recv,
                    backend_to_proxy_send,
                    backend_server.create_initialization_options(),
                )

            async def run_client_proxy():
                async with ClientSession(
                    backend_to_proxy_recv, proxy_to_backend_send
                ) as backend_session:
                    await backend_session.initialize()

                    connector = BackendConnector(backend_session)
                    proxy = _create_proxy(connector, strategy="truncation")

                    async def client_fn(session: ClientSession):
                        return await session.call_tool("big_read", {})

                    result = await _run_with_client(proxy, client_fn)
                    call_result_holder.append(result)

            async with anyio.create_task_group() as tg:
                tg.start_soon(run_backend)
                tg.start_soon(run_client_proxy)

            return call_result_holder[0]

        result = await run_test()
        # Original was 80K chars; truncation with max_tokens=100 should reduce it
        assert len(result.content[0].text) < len(BIG_CONTENT)
        assert "[truncated:" in result.content[0].text

    @pytest.mark.anyio
    async def test_tools_call_blocked_tool_returns_error(self) -> None:
        """tools/call for blocked tool returns error without hitting backend."""
        backend_server = _create_backend_server()

        proxy_to_backend_send, proxy_to_backend_recv = anyio.create_memory_object_stream[Any](100)
        backend_to_proxy_send, backend_to_proxy_recv = anyio.create_memory_object_stream[Any](100)

        async def run_test():
            call_result_holder: list[types.CallToolResult] = []

            async def run_backend():
                await backend_server.run(
                    proxy_to_backend_recv,
                    backend_to_proxy_send,
                    backend_server.create_initialization_options(),
                )

            async def run_client_proxy():
                async with ClientSession(
                    backend_to_proxy_recv, proxy_to_backend_send
                ) as backend_session:
                    await backend_session.initialize()

                    connector = BackendConnector(backend_session)
                    proxy = _create_proxy(
                        connector, blocked_tools=["secret_tool"]
                    )

                    async def client_fn(session: ClientSession):
                        return await session.call_tool("secret_tool", {})

                    result = await _run_with_client(proxy, client_fn)
                    call_result_holder.append(result)

            async with anyio.create_task_group() as tg:
                tg.start_soon(run_backend)
                tg.start_soon(run_client_proxy)

            return call_result_holder[0]

        result = await run_test()
        assert result.isError is True
        assert "blocked" in result.content[0].text.lower()
