"""Tests for Phase 04 proxy hooks: schema virtualization, semantic cache, learning store."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import mcp.types as types
import pytest

from token_sieve.domain.model import (
    CompressionEvent,
    ContentEnvelope,
    ContentType,
)
from token_sieve.domain.pipeline import CompressionPipeline
from token_sieve.server.proxy import ProxyServer
from token_sieve.server.tool_filter import ToolFilter


def _make_tool(name: str, desc: str = "test tool") -> types.Tool:
    return types.Tool(name=name, description=desc, inputSchema={"type": "object"})


def _make_call_result(text: str, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        isError=is_error,
    )


def _make_fake_connector(
    tools: list[types.Tool] | None = None,
    call_result: types.CallToolResult | None = None,
) -> AsyncMock:
    connector = AsyncMock()
    connector.list_tools = AsyncMock(return_value=tools or [])
    connector.call_tool = AsyncMock(
        return_value=call_result or _make_call_result("result data " * 50)
    )
    return connector


def _make_fake_filter(*, allowed: bool = True) -> MagicMock:
    filt = MagicMock(spec=ToolFilter)
    filt.filter_tools = MagicMock(side_effect=lambda t: t)
    filt.is_allowed = MagicMock(return_value=allowed)
    return filt


def _make_fake_pipeline(
    events: list[CompressionEvent] | None = None,
    output_content: str | None = None,
) -> MagicMock:
    pipeline = MagicMock(spec=CompressionPipeline)

    def process_side_effect(envelope: ContentEnvelope):
        out = ContentEnvelope(
            content=output_content or envelope.content,
            content_type=envelope.content_type,
        )
        return (out, events or [])

    pipeline.process = MagicMock(side_effect=process_side_effect)
    return pipeline


def _make_fake_sink() -> MagicMock:
    sink = MagicMock()
    sink.format_event = MagicMock(return_value="metric line")
    sink.emit = MagicMock()
    return sink


class TestSchemaVirtualizerIntegration:
    """handle_list_tools with schema_virtualizer returns virtualized tools."""

    @pytest.mark.asyncio
    async def test_list_tools_applies_schema_virtualization(self) -> None:
        """Schema virtualizer is called after reranker, returning virtualized tools."""
        tools = [_make_tool("read_file"), _make_tool("write_file")]
        connector = _make_fake_connector(tools=tools)

        # Mock schema virtualizer that adds a marker to tool descriptions
        schema_virt = MagicMock()
        schema_virt.virtualize = MagicMock(
            return_value=[
                {"name": "read_file", "description": "virtualized"},
                {"name": "write_file", "description": "virtualized"},
            ]
        )

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            schema_virtualizer=schema_virt,
        )

        result = await proxy.handle_list_tools()
        schema_virt.virtualize.assert_called_once()
        # Verify virtualized tools are returned (as types.Tool objects)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_tools_without_virtualizer_unchanged(self) -> None:
        """Without schema_virtualizer, tools/list works as before."""
        tools = [_make_tool("read_file")]
        connector = _make_fake_connector(tools=tools)

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
        )

        result = await proxy.handle_list_tools()
        assert len(result) == 1
        assert result[0].name == "read_file"


class TestSemanticCacheIntegration:
    """handle_call_tool with semantic_cache checks cache before backend."""

    @pytest.mark.asyncio
    async def test_semantic_cache_hit_skips_backend(self) -> None:
        """Semantic cache hit returns cached result without calling backend."""
        from token_sieve.domain.ports_cache import CacheHit

        connector = _make_fake_connector()
        cache = AsyncMock()
        cache.lookup_similar = AsyncMock(
            return_value=CacheHit(
                result_text="cached result text",
                similarity_score=0.95,
                hit_count=3,
            )
        )
        cache.cache_result = AsyncMock()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            semantic_cache=cache,
        )

        result = await proxy.handle_call_tool("read_file", {"path": "/foo"})
        # Backend should NOT be called
        connector.call_tool.assert_not_called()
        # Result text should be from cache
        assert result.content[0].text == "cached result text"

    @pytest.mark.asyncio
    async def test_semantic_cache_miss_calls_backend(self) -> None:
        """Semantic cache miss falls through to backend call."""
        connector = _make_fake_connector(
            call_result=_make_call_result("backend result " * 20)
        )
        cache = AsyncMock()
        cache.lookup_similar = AsyncMock(return_value=None)
        cache.cache_result = AsyncMock()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            semantic_cache=cache,
        )

        result = await proxy.handle_call_tool("read_file", {"path": "/foo"})
        connector.call_tool.assert_called_once()
        # cache_result should be called to store the new result
        cache.cache_result.assert_called_once()


class TestLearningStoreIntegration:
    """handle_call_tool records calls and compression events to learning_store."""

    @pytest.mark.asyncio
    async def test_learning_store_record_call_after_success(self) -> None:
        """After successful tool call, learning_store.record_call is invoked."""
        connector = _make_fake_connector(
            call_result=_make_call_result("some data " * 20)
        )
        store = AsyncMock()
        store.record_call = AsyncMock()
        store.record_compression_event = AsyncMock()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            learning_store=store,
        )

        await proxy.handle_call_tool("read_file", {"path": "/foo"})
        store.record_call.assert_called_once()
        # First arg should be tool name
        assert store.record_call.call_args[0][0] == "read_file"

    @pytest.mark.asyncio
    async def test_learning_store_records_compression_events(self) -> None:
        """Compression events are forwarded to learning_store."""
        event = CompressionEvent(
            original_tokens=100,
            compressed_tokens=60,
            strategy_name="whitespace",
            content_type=ContentType.TEXT,
        )
        connector = _make_fake_connector(
            call_result=_make_call_result("some data " * 20)
        )
        store = AsyncMock()
        store.record_call = AsyncMock()
        store.record_compression_event = AsyncMock()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(),
            pipeline=_make_fake_pipeline(events=[event]),
            metrics_sink=_make_fake_sink(),
            learning_store=store,
        )

        await proxy.handle_call_tool("read_file", {"path": "/foo"})
        store.record_compression_event.assert_called_once()


class TestMetricsCollectorIntegration:
    """Metrics collector receives compression events."""

    @pytest.mark.asyncio
    async def test_metrics_collector_records_events(self) -> None:
        """InMemoryMetricsCollector.record() called for each compression event."""
        event = CompressionEvent(
            original_tokens=200,
            compressed_tokens=80,
            strategy_name="null_elider",
            content_type=ContentType.TEXT,
        )
        connector = _make_fake_connector(
            call_result=_make_call_result("data " * 50)
        )
        collector = MagicMock()
        collector.record = MagicMock()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(),
            pipeline=_make_fake_pipeline(events=[event]),
            metrics_sink=_make_fake_sink(),
            metrics_collector=collector,
        )

        await proxy.handle_call_tool("read_file", {"path": "/foo"})
        collector.record.assert_called_once_with(event)


class TestMCPResourceDashboard:
    """MCP resource token-sieve://stats returns metrics JSON."""

    @pytest.mark.asyncio
    async def test_mcp_resource_returns_stats_json(self) -> None:
        """list_resources includes token-sieve://stats, read_resource returns JSON."""
        from token_sieve.domain.metrics import InMemoryMetricsCollector

        collector = InMemoryMetricsCollector()
        collector.record(
            CompressionEvent(
                original_tokens=100,
                compressed_tokens=40,
                strategy_name="test",
                content_type=ContentType.TEXT,
            )
        )

        proxy = ProxyServer(
            backend_connector=_make_fake_connector(),
            tool_filter=_make_fake_filter(),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            metrics_collector=collector,
        )

        # Access the internal MCP server's resource handlers
        resources = await proxy.handle_list_resources()
        assert any(
            r.uri == "token-sieve://stats" for r in resources
        )

        content = await proxy.handle_read_resource("token-sieve://stats")
        import json

        data = json.loads(content)
        assert data["session_summary"]["event_count"] == 1


class TestAdapterRegistryPhase04:
    """Phase 04 adapters are in the adapter registry."""

    def test_key_aliasing_in_registry(self) -> None:
        assert "key_aliasing" in ProxyServer._ADAPTER_REGISTRY

    def test_ast_skeleton_in_registry(self) -> None:
        assert "ast_skeleton" in ProxyServer._ADAPTER_REGISTRY

    def test_graph_encoder_in_registry(self) -> None:
        assert "graph_encoder" in ProxyServer._ADAPTER_REGISTRY

    def test_progressive_disclosure_in_registry(self) -> None:
        assert "progressive_disclosure" in ProxyServer._ADAPTER_REGISTRY
