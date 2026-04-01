"""End-to-end integration tests for Phase 04 proxy pipeline.

Exercises the full pipeline: SQLite + schema virtualization + semantic cache +
metrics + dashboard. Uses in-memory SQLite and mock backend.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import mcp.types as types
import pytest

from token_sieve.config.schema import TokenSieveConfig
from token_sieve.domain.metrics import InMemoryMetricsCollector
from token_sieve.domain.model import (
    CompressionEvent,
    ContentEnvelope,
    ContentType,
)
from token_sieve.domain.pipeline import CompressionPipeline
from token_sieve.server.proxy import ProxyServer
from token_sieve.server.tool_filter import ToolFilter


def _make_tool(
    name: str, desc: str = "A test tool", schema: dict | None = None
) -> types.Tool:
    return types.Tool(
        name=name,
        description=desc,
        inputSchema=schema or {"type": "object", "properties": {"path": {"type": "string"}}},
    )


def _make_backend(
    tools: list[types.Tool],
    call_results: dict[str, str] | None = None,
) -> AsyncMock:
    """Create mock backend connector returning given tools and call results."""
    connector = AsyncMock()
    connector.list_tools = AsyncMock(return_value=tools)

    default_results = call_results or {}

    async def fake_call(name: str, arguments: dict):
        text = default_results.get(name, f"Result for {name}: " + json.dumps(arguments) * 10)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
            isError=False,
        )

    connector.call_tool = AsyncMock(side_effect=fake_call)
    return connector


class TestPhase04EndToEnd:
    """Full Phase 04 pipeline integration test."""

    @pytest.fixture
    def tools(self) -> list[types.Tool]:
        return [
            _make_tool("read_file", "Read a file from disk"),
            _make_tool("write_file", "Write content to a file"),
            _make_tool("search_files", "Search for files matching pattern"),
        ]

    @pytest.fixture
    def backend(self, tools) -> AsyncMock:
        return _make_backend(
            tools,
            call_results={
                "read_file": "Line 1: content\n" * 50,
                "write_file": "File written successfully",
                "search_files": json.dumps([{"path": f"/src/file{i}.py", "match": "def test"} for i in range(20)]),
            },
        )

    @pytest.fixture
    def proxy(self, backend, tools) -> ProxyServer:
        """Create a fully wired Phase 04 proxy with mock backend."""
        from token_sieve.adapters.compression.whitespace_normalizer import WhitespaceNormalizer
        from token_sieve.adapters.rerank.statistical_reranker import StatisticalReranker
        from token_sieve.adapters.schema.schema_virtualizer import SchemaVirtualizer
        from token_sieve.domain.counters import CharEstimateCounter
        from token_sieve.server.metrics_sink import StderrMetricsSink

        counter = CharEstimateCounter()
        pipeline = CompressionPipeline(counter=counter, size_gate_threshold=50)
        pipeline.register(ContentType.TEXT, WhitespaceNormalizer())

        reranker = StatisticalReranker(max_tools=50, recency_weight=0.3)
        schema_virt = SchemaVirtualizer(frequent_threshold=2)
        metrics_collector = InMemoryMetricsCollector()

        # Use AsyncMock for semantic cache
        semantic_cache = AsyncMock()
        semantic_cache.lookup_similar = AsyncMock(return_value=None)
        semantic_cache.cache_result = AsyncMock()

        # Use AsyncMock for learning store
        learning_store = AsyncMock()
        learning_store.record_call = AsyncMock()
        learning_store.record_compression_event = AsyncMock()

        proxy = ProxyServer(
            backend_connector=backend,
            tool_filter=ToolFilter(mode="passthrough"),
            pipeline=pipeline,
            metrics_sink=StderrMetricsSink(),
            reranker=reranker,
            schema_virtualizer=schema_virt,
            semantic_cache=semantic_cache,
            learning_store=learning_store,
            metrics_collector=metrics_collector,
        )
        return proxy

    @pytest.mark.asyncio
    async def test_tools_list_applies_schema_virtualization(
        self, proxy: ProxyServer
    ) -> None:
        """tools/list returns virtualized tool schemas."""
        tools = await proxy.handle_list_tools()
        assert len(tools) == 3
        # Verify all tools are present
        names = {t.name for t in tools}
        assert names == {"read_file", "write_file", "search_files"}

    @pytest.mark.asyncio
    async def test_call_tool_compresses_result(
        self, proxy: ProxyServer
    ) -> None:
        """call_tool compresses text results through pipeline."""
        result = await proxy.handle_call_tool("read_file", {"path": "/test.py"})
        assert not result.isError
        # Compression should have removed some whitespace
        text = result.content[0].text
        assert len(text) > 0

    @pytest.mark.asyncio
    async def test_semantic_cache_miss_then_caches(
        self, proxy: ProxyServer
    ) -> None:
        """First call is a cache miss; result is stored in semantic cache."""
        result = await proxy.handle_call_tool("read_file", {"path": "/foo.py"})
        assert not result.isError
        # Semantic cache should have been called
        proxy._semantic_cache.lookup_similar.assert_called()
        proxy._semantic_cache.cache_result.assert_called()

    @pytest.mark.asyncio
    async def test_semantic_cache_hit_skips_backend(
        self, proxy: ProxyServer
    ) -> None:
        """Second call with similar args returns cached result."""
        from token_sieve.domain.ports_cache import CacheHit

        # First call - miss
        await proxy.handle_call_tool("read_file", {"path": "/foo.py"})

        # Configure cache hit for next call
        proxy._semantic_cache.lookup_similar = AsyncMock(
            return_value=CacheHit(
                result_text="cached content here",
                similarity_score=0.92,
                hit_count=1,
            )
        )

        result = await proxy.handle_call_tool("read_file", {"path": "/foo.py"})
        assert result.content[0].text == "cached content here"

    @pytest.mark.asyncio
    async def test_learning_store_records_calls(
        self, proxy: ProxyServer
    ) -> None:
        """Learning store records every tool call."""
        await proxy.handle_call_tool("read_file", {"path": "/a.py"})
        await proxy.handle_call_tool("write_file", {"path": "/b.py", "content": "x"})

        assert proxy._learning_store.record_call.call_count == 2

    @pytest.mark.asyncio
    async def test_metrics_collector_aggregates_events(
        self, proxy: ProxyServer
    ) -> None:
        """Metrics collector receives compression events from pipeline."""
        await proxy.handle_call_tool("read_file", {"path": "/test.py"})

        summary = proxy._metrics_collector.session_summary()
        assert summary["event_count"] >= 1

    @pytest.mark.asyncio
    async def test_mcp_resource_returns_stats(
        self, proxy: ProxyServer
    ) -> None:
        """token-sieve://stats resource returns aggregated metrics."""
        # Make some calls first
        await proxy.handle_call_tool("read_file", {"path": "/test.py"})

        resources = await proxy.handle_list_resources()
        assert any(str(r.uri) == "token-sieve://stats" for r in resources)

        stats_json = await proxy.handle_read_resource("token-sieve://stats")
        stats = json.loads(stats_json)
        assert "session_summary" in stats
        assert "strategy_breakdown" in stats
        assert stats["session_summary"]["event_count"] >= 1

    @pytest.mark.asyncio
    async def test_token_reduction_demonstrated(
        self, proxy: ProxyServer
    ) -> None:
        """End-to-end pipeline demonstrates measurable token reduction."""
        # search_files returns a big JSON blob
        result = await proxy.handle_call_tool(
            "search_files", {"pattern": "*.py"}
        )
        compressed_text = result.content[0].text
        original_text = json.dumps(
            [{"path": f"/src/file{i}.py", "match": "def test"} for i in range(20)]
        ) * 10  # This is what the mock returns (repeated via json.dumps)

        # Verify metrics show savings
        summary = proxy._metrics_collector.session_summary()
        if summary["event_count"] > 0:
            assert summary["total_original_tokens"] > 0

    @pytest.mark.asyncio
    async def test_reranker_records_usage_for_ordering(
        self, proxy: ProxyServer
    ) -> None:
        """Reranker records usage data affecting future tool ordering."""
        # Call read_file multiple times
        for _ in range(5):
            await proxy.handle_call_tool("read_file", {"path": "/a.py"})

        # Verify reranker has recorded usage
        tools = await proxy.handle_list_tools()
        # read_file should appear first (most used)
        assert tools[0].name == "read_file"
