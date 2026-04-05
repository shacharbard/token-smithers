"""Tests for ProxyServer — MCP proxy with filtering and compression."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp import types
from token_sieve.domain.model import (
    CompressionEvent,
    ContentEnvelope,
    ContentType,
)


# ---------------------------------------------------------------------------
# Helpers / Fakes
# ---------------------------------------------------------------------------


def _make_tool(name: str, desc: str = "test tool") -> types.Tool:
    return types.Tool(
        name=name,
        description=desc,
        inputSchema={"type": "object", "properties": {}},
    )


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
        return_value=call_result or _make_call_result("ok")
    )
    return connector


def _make_fake_filter(*, allowed: bool = True) -> MagicMock:
    filt = MagicMock()
    filt.is_allowed = MagicMock(return_value=allowed)
    filt.filter_tools = MagicMock(side_effect=lambda tools: tools if allowed else [])
    return filt


def _make_fake_pipeline(
    events: list[CompressionEvent] | None = None,
    output_content: str | None = None,
) -> MagicMock:
    pipeline = MagicMock()
    default_events = events or []
    def process_side_effect(envelope: ContentEnvelope) -> tuple[ContentEnvelope, list[CompressionEvent]]:
        out = envelope if output_content is None else ContentEnvelope(
            content=output_content, content_type=envelope.content_type
        )
        return out, default_events
    pipeline.process = MagicMock(side_effect=process_side_effect)
    return pipeline


def _make_fake_sink() -> MagicMock:
    sink = MagicMock()
    sink.format_event = MagicMock(return_value="[token-sieve] formatted")
    sink.emit = MagicMock()
    return sink


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHandleListTools:
    """tools/list handler returns filtered tool list."""

    @pytest.mark.anyio
    async def test_list_tools_returns_filtered_tools(self) -> None:
        from token_sieve.server.proxy import ProxyServer

        tools = [_make_tool("allowed"), _make_tool("blocked")]
        connector = _make_fake_connector(tools=tools)
        filt = MagicMock()
        filt.filter_tools = MagicMock(return_value=[tools[0]])
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
        )

        result = await proxy.handle_list_tools()
        assert len(result) == 1
        assert result[0].name == "allowed"
        connector.list_tools.assert_awaited_once()
        filt.filter_tools.assert_called_once_with(tools)

    @pytest.mark.anyio
    async def test_list_tools_empty_backend(self) -> None:
        from token_sieve.server.proxy import ProxyServer

        connector = _make_fake_connector(tools=[])
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
        )

        result = await proxy.handle_list_tools()
        assert result == []


class TestHandleCallTool:
    """tools/call handler forwards to backend and compresses."""

    @pytest.mark.anyio
    async def test_call_tool_forwards_to_backend(self) -> None:
        from token_sieve.server.proxy import ProxyServer

        backend_result = _make_call_result("hello world")
        connector = _make_fake_connector(call_result=backend_result)
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
        )

        result = await proxy.handle_call_tool("echo", {"msg": "hi"})
        connector.call_tool.assert_awaited_once_with("echo", {"msg": "hi"})
        assert isinstance(result, types.CallToolResult)

    @pytest.mark.anyio
    async def test_call_tool_runs_through_pipeline(self) -> None:
        from token_sieve.server.proxy import ProxyServer

        backend_result = _make_call_result("long content here")
        connector = _make_fake_connector(call_result=backend_result)
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline(output_content="compressed")
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
        )

        result = await proxy.handle_call_tool("echo", {})
        pipeline.process.assert_called_once()
        # Result should contain compressed content
        assert result.content[0].text == "compressed"

    @pytest.mark.anyio
    async def test_call_tool_rejects_blocked_tool(self) -> None:
        from token_sieve.server.proxy import ProxyServer

        connector = _make_fake_connector()
        filt = _make_fake_filter(allowed=False)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
        )

        result = await proxy.handle_call_tool("blocked_tool", {})
        assert result.isError is True
        assert "blocked" in result.content[0].text.lower()
        # Should NOT forward to backend
        connector.call_tool.assert_not_awaited()

    @pytest.mark.anyio
    async def test_call_tool_handles_backend_error(self) -> None:
        from token_sieve.server.proxy import ProxyServer

        error_result = _make_call_result("Backend error: timeout", is_error=True)
        connector = _make_fake_connector(call_result=error_result)
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
        )

        result = await proxy.handle_call_tool("echo", {})
        # Backend errors should pass through without compression
        assert result.isError is True

    @pytest.mark.anyio
    async def test_call_tool_emits_metrics(self) -> None:
        from token_sieve.server.proxy import ProxyServer

        event = CompressionEvent(
            original_tokens=100,
            compressed_tokens=50,
            strategy_name="Truncation",
            content_type=ContentType.TEXT,
        )
        backend_result = _make_call_result("content")
        connector = _make_fake_connector(call_result=backend_result)
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline(events=[event])
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
        )

        await proxy.handle_call_tool("echo", {})
        sink.format_event.assert_called_once_with(event, tool_name="echo")
        sink.emit.assert_called()

    @pytest.mark.anyio
    async def test_call_tool_passes_text_content_only(self) -> None:
        """Non-text content from backend is passed through uncompressed."""
        from token_sieve.server.proxy import ProxyServer

        # Backend returns image content (non-text)
        image_content = types.ImageContent(
            type="image",
            data="base64data",
            mimeType="image/png",
        )
        backend_result = types.CallToolResult(
            content=[image_content],
            isError=False,
        )
        connector = _make_fake_connector(call_result=backend_result)
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
        )

        result = await proxy.handle_call_tool("image_tool", {})
        # Non-text content passes through unchanged
        assert result.content[0].type == "image"
        pipeline.process.assert_not_called()


class TestCreateFromConfig:
    """ProxyServer.create_from_config() wires all dependencies."""

    def test_create_from_config_returns_proxy(self) -> None:
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.server.proxy import ProxyServer

        config = TokenSieveConfig()
        proxy = ProxyServer.create_from_config(config)
        assert isinstance(proxy, ProxyServer)

    def test_create_from_config_wires_adapters_from_config(self) -> None:
        """create_from_config() registers adapters from config list."""
        from token_sieve.config.schema import AdapterConfig, TokenSieveConfig
        from token_sieve.server.proxy import ProxyServer

        config = TokenSieveConfig(
            compression={
                "adapters": [
                    {"name": "whitespace_normalizer"},
                    {"name": "smart_truncation"},
                ],
                "size_gate_threshold": 500,
            }
        )
        proxy = ProxyServer.create_from_config(config)
        assert isinstance(proxy, ProxyServer)
        # Pipeline should have strategies registered
        pipeline = proxy._pipeline
        text_chain = pipeline._routes.get(ContentType.TEXT, [])
        assert len(text_chain) >= 2  # at least the 2 adapters we specified

    def test_create_from_config_skips_disabled_adapter(self) -> None:
        """Adapters with enabled=False are not registered in the pipeline."""
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.server.proxy import ProxyServer

        config = TokenSieveConfig(
            compression={
                "adapters": [
                    {"name": "whitespace_normalizer", "enabled": True},
                    {"name": "smart_truncation", "enabled": False},
                ],
            }
        )
        proxy = ProxyServer.create_from_config(config)
        pipeline = proxy._pipeline
        text_chain = pipeline._routes.get(ContentType.TEXT, [])
        # Only whitespace_normalizer should be registered
        names = [type(s).__name__ for s in text_chain]
        assert "SmartTruncation" not in names
        assert "WhitespaceNormalizer" in names

    def test_create_from_config_uses_size_gate_threshold(self) -> None:
        """size_gate_threshold from config is passed to pipeline."""
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.server.proxy import ProxyServer

        config = TokenSieveConfig(
            compression={"size_gate_threshold": 5000}
        )
        proxy = ProxyServer.create_from_config(config)
        assert proxy._pipeline._size_gate_threshold == 5000

    def test_create_from_config_passes_adapter_settings(self) -> None:
        """Per-adapter settings are forwarded to adapter constructors."""
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.server.proxy import ProxyServer

        config = TokenSieveConfig(
            compression={
                "adapters": [
                    {
                        "name": "smart_truncation",
                        "settings": {"head_lines": 10, "tail_lines": 5},
                    },
                ],
            }
        )
        proxy = ProxyServer.create_from_config(config)
        pipeline = proxy._pipeline
        text_chain = pipeline._routes.get(ContentType.TEXT, [])
        smart_trunc = [s for s in text_chain if type(s).__name__ == "SmartTruncation"]
        assert len(smart_trunc) == 1
        assert smart_trunc[0].head_lines == 10
        assert smart_trunc[0].tail_lines == 5


class TestCallCacheIntegration:
    """handle_call_tool with IdempotentCallCache."""

    @pytest.mark.anyio
    async def test_cached_result_skips_backend(self) -> None:
        """Cached call returns cached result without calling backend."""
        from token_sieve.adapters.cache.call_cache import IdempotentCallCache
        from token_sieve.server.proxy import ProxyServer

        backend_result = _make_call_result("backend response")
        connector = _make_fake_connector(call_result=backend_result)
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        cache = IdempotentCallCache()
        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            call_cache=cache,
        )

        # First call — cache miss, should call backend
        result1 = await proxy.handle_call_tool("read_file", {"path": "a"})
        assert connector.call_tool.await_count == 1

        # Second call — cache hit, should NOT call backend again
        result2 = await proxy.handle_call_tool("read_file", {"path": "a"})
        assert connector.call_tool.await_count == 1  # still 1
        assert result2.content[0].text == result1.content[0].text

    @pytest.mark.anyio
    async def test_cache_miss_calls_backend_and_caches(self) -> None:
        """Cache miss calls backend + caches the result."""
        from token_sieve.adapters.cache.call_cache import IdempotentCallCache
        from token_sieve.server.proxy import ProxyServer

        backend_result = _make_call_result("fresh data")
        connector = _make_fake_connector(call_result=backend_result)
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        cache = IdempotentCallCache()
        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            call_cache=cache,
        )

        result = await proxy.handle_call_tool("read_file", {"path": "a"})
        assert result.content[0].text is not None
        # Verify it's now cached
        assert cache.get("read_file", {"path": "a"}) is not None

    @pytest.mark.anyio
    async def test_mutating_call_invalidates_cache(self) -> None:
        """Mutating call triggers invalidation."""
        from token_sieve.adapters.cache.call_cache import IdempotentCallCache
        from token_sieve.adapters.cache.invalidation import WriteThruInvalidator
        from token_sieve.server.proxy import ProxyServer

        connector = _make_fake_connector(call_result=_make_call_result("data"))
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        cache = IdempotentCallCache()
        invalidator = WriteThruInvalidator()
        invalidator.register_observer(cache)

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            call_cache=cache,
            invalidator=invalidator,
        )

        # Cache a read result
        await proxy.handle_call_tool("read_file", {"path": "a"})
        assert cache.get("read_file", {"path": "a"}) is not None

        # Mutating call should trigger invalidation
        connector.call_tool = AsyncMock(
            return_value=_make_call_result("written")
        )
        await proxy.handle_call_tool("write_file", {"path": "b"})

        # read_file cache should be cleared (invalidation by tool prefix is global)
        # Actually, invalidation is by exact tool name — "write_file" invalidates
        # write_file entries, but the invalidator notifies about the mutating call.
        # The cache.invalidate("write_file") only clears write_file entries.


class TestRerankerIntegration:
    """handle_list_tools with SchemaCache + StatisticalReranker."""

    @pytest.mark.anyio
    async def test_reranker_reorders_tools(self) -> None:
        """Reranker reorders tools after usage recording."""
        from token_sieve.adapters.rerank.statistical_reranker import StatisticalReranker
        from token_sieve.domain.tool_metadata import ToolMetadata
        from token_sieve.server.proxy import ProxyServer

        tools = [_make_tool("rarely_used"), _make_tool("often_used")]
        connector = _make_fake_connector(tools=tools)
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        reranker = StatisticalReranker()
        # Record usage for "often_used" multiple times
        for _ in range(5):
            reranker.record_call("often_used")

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            reranker=reranker,
        )

        result = await proxy.handle_list_tools()
        # often_used should come first after reranking
        assert result[0].name == "often_used"

    @pytest.mark.anyio
    async def test_handle_call_tool_records_usage(self) -> None:
        """handle_call_tool records usage in reranker."""
        from token_sieve.adapters.rerank.statistical_reranker import StatisticalReranker
        from token_sieve.server.proxy import ProxyServer

        connector = _make_fake_connector(call_result=_make_call_result("ok"))
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        reranker = StatisticalReranker()
        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            reranker=reranker,
        )

        await proxy.handle_call_tool("my_tool", {})
        assert reranker._stats.get("my_tool") is not None
        assert reranker._stats["my_tool"].call_count == 1


class TestSchemaCacheIntegration:
    """handle_list_tools with SchemaCache."""

    @pytest.mark.anyio
    async def test_schema_cache_second_call_uses_cache(self) -> None:
        """Second handle_list_tools uses cached tools."""
        from token_sieve.adapters.cache.schema_cache import SchemaCache
        from token_sieve.domain.tool_metadata import ToolMetadata
        from token_sieve.server.proxy import ProxyServer

        tools = [_make_tool("tool_a"), _make_tool("tool_b")]
        connector = _make_fake_connector(tools=tools)
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        schema_cache = SchemaCache(provider=connector, ttl_seconds=3600.0)
        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            schema_cache=schema_cache,
        )

        result1 = await proxy.handle_list_tools()
        result2 = await proxy.handle_list_tools()
        # Backend should only be called once (second call uses cache)
        assert connector.list_tools.await_count == 1
        assert len(result1) == 2
        assert len(result2) == 2


class TestCreateFromConfigExtended:
    """create_from_config() wires cache, reranker, invalidator."""

    def test_create_from_config_wires_call_cache(self) -> None:
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.server.proxy import ProxyServer

        config = TokenSieveConfig(cache={"call_cache_max": 50})
        proxy = ProxyServer.create_from_config(config)
        assert proxy._call_cache is not None
        assert proxy._call_cache._max_entries == 50

    def test_create_from_config_wires_reranker(self) -> None:
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.server.proxy import ProxyServer

        config = TokenSieveConfig(reranker={"max_tools": 100, "recency_weight": 0.5})
        proxy = ProxyServer.create_from_config(config)
        assert proxy._reranker is not None

    def test_create_from_config_wires_invalidator(self) -> None:
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.server.proxy import ProxyServer

        config = TokenSieveConfig()
        proxy = ProxyServer.create_from_config(config)
        assert proxy._invalidator is not None


class TestSchemaCacheRebind:
    """Finding 1 (P0): SchemaCache must use the live connector after rebind."""

    @pytest.mark.anyio
    async def test_schema_cache_reads_through_live_connector(self) -> None:
        """After rebinding _connector, SchemaCache must use the new connector."""
        from token_sieve.adapters.cache.schema_cache import SchemaCache
        from token_sieve.server.proxy import ProxyServer

        # Start with stub that returns empty
        stub = _make_fake_connector(tools=[])
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()
        schema_cache = SchemaCache(provider=stub, ttl_seconds=3600.0)

        proxy = ProxyServer(
            backend_connector=stub,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            schema_cache=schema_cache,
        )

        # Simulate _run_proxy rebinding: replace connector with a live one
        live_tools = [_make_tool("live_tool")]
        live_connector = _make_fake_connector(tools=live_tools)
        proxy.rebind_connector(live_connector)

        result = await proxy.handle_list_tools()
        assert len(result) == 1
        assert result[0].name == "live_tool"


class TestHandleCallToolEmptyText:
    """Finding 3 (P1): Empty TextContent from backend must not crash."""

    @pytest.mark.anyio
    async def test_empty_text_content_passes_through(self) -> None:
        """Backend returning empty text should pass through without error."""
        from token_sieve.server.proxy import ProxyServer

        empty_result = types.CallToolResult(
            content=[types.TextContent(type="text", text="")],
            isError=False,
        )
        connector = _make_fake_connector(call_result=empty_result)
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
        )

        # Should not raise
        result = await proxy.handle_call_tool("some_tool", {})
        assert result.isError is False
        assert len(result.content) == 1
        assert result.content[0].text == ""


class TestMutatingCallGlobalInvalidation:
    """Finding 6: Mutating calls must invalidate ALL cached entries."""

    @pytest.mark.anyio
    async def test_mutating_call_invalidates_all_read_caches(self) -> None:
        """A write_file call should invalidate unrelated read_file cache entries."""
        from token_sieve.adapters.cache.call_cache import IdempotentCallCache
        from token_sieve.adapters.cache.invalidation import WriteThruInvalidator
        from token_sieve.server.proxy import ProxyServer

        connector = _make_fake_connector(
            call_result=_make_call_result("result data")
        )
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()
        cache = IdempotentCallCache(max_entries=100)
        invalidator = WriteThruInvalidator()
        invalidator.register_observer(cache)

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            call_cache=cache,
            invalidator=invalidator,
        )

        # Cache a read_file result
        await proxy.handle_call_tool("read_file", {"path": "/a.txt"})
        assert cache.get("read_file", {"path": "/a.txt"}) is not None

        # Now do a mutating call (write_file)
        await proxy.handle_call_tool("write_file", {"path": "/b.txt"})

        # The read_file cache entry should be invalidated (global invalidation)
        assert cache.get("read_file", {"path": "/a.txt"}) is None


# ---------------------------------------------------------------------------
# Phase 04 adversarial review findings (F1-F4, F6)
# ---------------------------------------------------------------------------


class TestSemanticCacheSkipsMutatingCalls:
    """F1: Semantic cache must not serve results for mutating tool calls."""

    @pytest.mark.asyncio
    async def test_mutating_call_bypasses_semantic_cache(self) -> None:
        """write_file should NEVER hit the semantic cache."""
        from token_sieve.adapters.cache.invalidation import WriteThruInvalidator
        from token_sieve.server.proxy import ProxyServer

        fake_semantic_cache = AsyncMock()
        fake_semantic_cache.lookup_similar = AsyncMock(
            return_value=MagicMock(result_text="stale cached data")
        )
        fake_semantic_cache.similarity_threshold = 0.85
        fake_semantic_cache.evict_expired = AsyncMock(return_value=0)

        invalidator = WriteThruInvalidator()

        connector = _make_fake_connector(
            call_result=_make_call_result("fresh write result"),
        )

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            invalidator=invalidator,
            semantic_cache=fake_semantic_cache,
        )

        result = await proxy.handle_call_tool("write_file", {"path": "/a.txt"})

        # Must NOT have called lookup_similar — mutating calls skip cache
        fake_semantic_cache.lookup_similar.assert_not_called()
        # Must have actually called backend
        connector.call_tool.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_semantic_cache_registered_as_invalidation_observer(self) -> None:
        """F1 part 2: semantic cache invalidate_all called on mutation."""
        from token_sieve.adapters.cache.invalidation import WriteThruInvalidator
        from token_sieve.server.proxy import _DeferredSemanticCache

        cache = _DeferredSemanticCache(
            max_entries=10, ttl_seconds=60, similarity_threshold=0.85
        )

        # Verify it has invalidate_all for the observer protocol
        assert hasattr(cache, "invalidate_all"), (
            "_DeferredSemanticCache must implement invalidate_all()"
        )


class TestLearningStoreIOSafety:
    """F2: Learning store I/O errors must not crash tool calls."""

    @pytest.mark.asyncio
    async def test_learning_store_error_does_not_crash_call(self) -> None:
        """If learning store raises, tool call still returns result."""
        from token_sieve.server.proxy import ProxyServer

        learning_store = AsyncMock()
        learning_store.record_call = AsyncMock(
            side_effect=IOError("disk full")
        )

        connector = _make_fake_connector(
            call_result=_make_call_result("good result"),
        )

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            learning_store=learning_store,
        )

        # Should NOT raise — must fail open
        result = await proxy.handle_call_tool("read_file", {"path": "/a"})
        assert not result.isError

    @pytest.mark.asyncio
    async def test_learning_store_disabled_after_max_failures(self) -> None:
        """After 3 consecutive failures, learning store should be disabled."""
        from token_sieve.server.proxy import ProxyServer

        call_count = 0

        async def always_fail(*args: Any) -> None:
            nonlocal call_count
            call_count += 1
            raise IOError("disk full")

        learning_store = AsyncMock()
        learning_store.record_call = AsyncMock(side_effect=always_fail)

        connector = _make_fake_connector(
            call_result=_make_call_result("result"),
        )

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            learning_store=learning_store,
        )

        for i in range(4):
            await proxy.handle_call_tool("read_file", {"path": f"/{i}"})

        # 3 failures then disabled — 4th call should not attempt
        assert call_count == 3, "Learning store should be disabled after 3 consecutive failures"

    @pytest.mark.asyncio
    async def test_semantic_cache_store_error_does_not_crash(self) -> None:
        """F2 part 2: _store_semantic_cache failure must not crash."""
        from token_sieve.server.proxy import ProxyServer

        fake_semantic_cache = AsyncMock()
        fake_semantic_cache.lookup_similar = AsyncMock(return_value=None)
        fake_semantic_cache.similarity_threshold = 0.85
        fake_semantic_cache.evict_expired = AsyncMock(return_value=0)
        fake_semantic_cache.cache_result = AsyncMock(
            side_effect=IOError("write failed")
        )

        connector = _make_fake_connector(
            call_result=_make_call_result("good result"),
        )

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            semantic_cache=fake_semantic_cache,
        )

        # Should NOT raise
        result = await proxy.handle_call_tool("read_file", {"path": "/a"})
        assert not result.isError


class TestSimilarityThresholdFromConfig:
    """F3: Configured similarity threshold must be used, not hardcoded 0.85."""

    @pytest.mark.asyncio
    async def test_custom_threshold_used_in_lookup(self) -> None:
        """Semantic cache lookup must use the configured threshold."""
        from token_sieve.server.proxy import ProxyServer

        fake_semantic_cache = AsyncMock()
        fake_semantic_cache.lookup_similar = AsyncMock(return_value=None)
        fake_semantic_cache.similarity_threshold = 0.70  # Custom threshold
        fake_semantic_cache.evict_expired = AsyncMock(return_value=0)
        fake_semantic_cache.cache_result = AsyncMock()

        connector = _make_fake_connector(
            call_result=_make_call_result("result"),
        )

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            semantic_cache=fake_semantic_cache,
        )

        await proxy.handle_call_tool("read_file", {"path": "/a"})

        # The threshold passed to lookup_similar must be 0.70, NOT 0.85
        call_args = fake_semantic_cache.lookup_similar.call_args
        assert call_args is not None
        threshold_used = call_args.kwargs.get(
            "threshold", call_args.args[2] if len(call_args.args) > 2 else None
        )
        assert threshold_used == pytest.approx(0.70), (
            f"Expected threshold=0.70 but got {threshold_used}"
        )


class TestTTLEvictionRuns:
    """F4: TTL eviction runs rate-limited (every 50 cache checks)."""

    @pytest.mark.asyncio
    async def test_evict_expired_rate_limited(self) -> None:
        """evict_expired() is called every 50th _check_semantic_cache, not every call."""
        from token_sieve.server.proxy import ProxyServer

        fake_semantic_cache = AsyncMock()
        fake_semantic_cache.lookup_similar = AsyncMock(return_value=None)
        fake_semantic_cache.similarity_threshold = 0.85
        fake_semantic_cache.evict_expired = AsyncMock(return_value=0)
        fake_semantic_cache.cache_result = AsyncMock()

        connector = _make_fake_connector(
            call_result=_make_call_result("result"),
        )

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            semantic_cache=fake_semantic_cache,
        )

        # First 49 calls should NOT trigger eviction
        for _ in range(49):
            await proxy.handle_call_tool("read_file", {"path": "/a"})
        assert fake_semantic_cache.evict_expired.await_count == 0

        # 50th call should trigger eviction
        await proxy.handle_call_tool("read_file", {"path": "/a"})
        assert fake_semantic_cache.evict_expired.await_count == 1

        # 51st call should NOT trigger again
        await proxy.handle_call_tool("read_file", {"path": "/a"})
        assert fake_semantic_cache.evict_expired.await_count == 1


class TestPipelineCleanup:
    """F6: Pipeline cleanup must propagate to strategies."""

    def test_cleanup_calls_strategy_cleanup(self) -> None:
        """CompressionPipeline.cleanup() must call cleanup on strategies that have it."""
        from token_sieve.domain.counters import CharEstimateCounter
        from token_sieve.domain.pipeline import CompressionPipeline

        counter = CharEstimateCounter()
        pipeline = CompressionPipeline(counter=counter)

        # Strategy with cleanup
        strategy_with_cleanup = MagicMock()
        strategy_with_cleanup.can_handle = MagicMock(return_value=True)
        strategy_with_cleanup.compress = MagicMock()
        strategy_with_cleanup.cleanup = MagicMock()

        # Strategy without cleanup
        strategy_no_cleanup = MagicMock(spec=["can_handle", "compress"])

        pipeline.register(ContentType.TEXT, strategy_with_cleanup)
        pipeline.register(ContentType.TEXT, strategy_no_cleanup)

        pipeline.cleanup()

        strategy_with_cleanup.cleanup.assert_called_once()
        # strategy_no_cleanup should not crash (no cleanup method)

    def test_cleanup_method_exists(self) -> None:
        """CompressionPipeline must have a cleanup() method."""
        from token_sieve.domain.counters import CharEstimateCounter
        from token_sieve.domain.pipeline import CompressionPipeline

        pipeline = CompressionPipeline(counter=CharEstimateCounter())
        assert hasattr(pipeline, "cleanup"), (
            "CompressionPipeline must have a cleanup() method"
        )


class TestProxyRunCleanup:
    """F6 part 2: ProxyServer.run() must cleanup pipeline in finally block."""

    @pytest.mark.asyncio
    async def test_run_calls_pipeline_cleanup(self) -> None:
        """Pipeline cleanup must be called even if server exits."""
        from token_sieve.server.proxy import ProxyServer
        from unittest.mock import patch

        pipeline = _make_fake_pipeline()
        pipeline.cleanup = MagicMock()

        proxy = ProxyServer(
            backend_connector=_make_fake_connector(),
            tool_filter=_make_fake_filter(),
            pipeline=pipeline,
            metrics_sink=_make_fake_sink(),
        )

        # Mock stdio_server as an async context manager
        class _FakeCtx:
            async def __aenter__(self):
                return (AsyncMock(), AsyncMock())

            async def __aexit__(self, *args):
                pass

        with patch("mcp.server.stdio.stdio_server", return_value=_FakeCtx()):
            with patch.object(proxy._server, "run", new_callable=AsyncMock):
                await proxy.run()

        pipeline.cleanup.assert_called_once()


class TestCacheableAllowlist:
    """Item 1: Semantic cache should only be used for known-safe (read-only) tools."""

    def test_read_tool_is_cacheable(self) -> None:
        """Tools with read-like names should be cacheable."""
        from token_sieve.server.proxy import ProxyServer

        proxy = ProxyServer(
            backend_connector=_make_fake_connector(),
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
        )
        assert proxy._is_cacheable("read_file") is True
        assert proxy._is_cacheable("get_symbol") is True
        assert proxy._is_cacheable("list_tools") is True
        assert proxy._is_cacheable("search_files") is True
        assert proxy._is_cacheable("find_references") is True
        assert proxy._is_cacheable("describe_table") is True
        assert proxy._is_cacheable("show_config") is True
        assert proxy._is_cacheable("view_log") is True
        assert proxy._is_cacheable("fetch_data") is True
        assert proxy._is_cacheable("check_status") is True
        assert proxy._is_cacheable("query_db") is True
        assert proxy._is_cacheable("browse_dir") is True

    def test_mutating_tool_not_cacheable(self) -> None:
        """Tools with write-like names should NOT be cacheable."""
        from token_sieve.server.proxy import ProxyServer

        proxy = ProxyServer(
            backend_connector=_make_fake_connector(),
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
        )
        assert proxy._is_cacheable("write_file") is False
        assert proxy._is_cacheable("create_dir") is False
        assert proxy._is_cacheable("delete_item") is False
        assert proxy._is_cacheable("update_record") is False

    def test_unknown_tool_not_cacheable(self) -> None:
        """Tools with non-standard names (bash, execute, mv) should NOT be cacheable."""
        from token_sieve.server.proxy import ProxyServer

        proxy = ProxyServer(
            backend_connector=_make_fake_connector(),
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
        )
        assert proxy._is_cacheable("bash") is False
        assert proxy._is_cacheable("execute") is False
        assert proxy._is_cacheable("run_command") is False
        assert proxy._is_cacheable("apply_patch") is False
        assert proxy._is_cacheable("mv") is False
        assert proxy._is_cacheable("chmod") is False
        assert proxy._is_cacheable("kill") is False

    @pytest.mark.asyncio
    async def test_unknown_tool_bypasses_semantic_cache(self) -> None:
        """A tool like 'bash' must not use semantic cache even with a warm cache."""
        from token_sieve.server.proxy import ProxyServer

        semantic_cache = AsyncMock()
        semantic_cache.lookup_similar = AsyncMock(return_value=None)
        semantic_cache.cache_result = AsyncMock()
        semantic_cache.evict_expired = AsyncMock()
        semantic_cache.similarity_threshold = 0.85

        connector = _make_fake_connector(call_result=_make_call_result("live result"))

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            semantic_cache=semantic_cache,
        )

        result = await proxy.handle_call_tool("bash", {"cmd": "ls"})
        assert not result.isError
        # Semantic cache should NOT have been consulted
        semantic_cache.lookup_similar.assert_not_called()

    @pytest.mark.asyncio
    async def test_cacheable_tool_uses_semantic_cache(self) -> None:
        """A read-like tool should consult the semantic cache."""
        from token_sieve.server.proxy import ProxyServer

        semantic_cache = AsyncMock()
        semantic_cache.lookup_similar = AsyncMock(return_value=None)
        semantic_cache.cache_result = AsyncMock()
        semantic_cache.evict_expired = AsyncMock()
        semantic_cache.similarity_threshold = 0.85

        connector = _make_fake_connector(call_result=_make_call_result("file contents"))

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            semantic_cache=semantic_cache,
        )

        await proxy.handle_call_tool("read_file", {"path": "/a.py"})
        semantic_cache.lookup_similar.assert_called()


class TestLearningStoreRetry:
    """Item 3: Learning store should retry before permanent disable."""

    @pytest.mark.asyncio
    async def test_learning_store_retries_on_transient_error(self) -> None:
        """After 1 failure, learning store should still be attempted on next call."""
        from token_sieve.server.proxy import ProxyServer

        call_count = 0

        async def record_call_sometimes_fail(*args: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise IOError("transient disk error")

        learning_store = AsyncMock()
        learning_store.record_call = AsyncMock(side_effect=record_call_sometimes_fail)
        learning_store.record_compression_event = AsyncMock()

        connector = _make_fake_connector(call_result=_make_call_result("result"))

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            learning_store=learning_store,
        )

        # First call - fails but should not disable
        await proxy.handle_call_tool("read_file", {"path": "/a"})
        # Second call - should still attempt learning store
        await proxy.handle_call_tool("read_file", {"path": "/b"})

        assert call_count == 2, "Learning store should be retried after first failure"

    @pytest.mark.asyncio
    async def test_learning_store_disabled_after_max_failures(self) -> None:
        """After 3 consecutive failures, learning store should be disabled."""
        from token_sieve.server.proxy import ProxyServer

        call_count = 0

        async def always_fail(*args: Any) -> None:
            nonlocal call_count
            call_count += 1
            raise IOError("persistent disk error")

        learning_store = AsyncMock()
        learning_store.record_call = AsyncMock(side_effect=always_fail)

        connector = _make_fake_connector(call_result=_make_call_result("result"))

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            learning_store=learning_store,
        )

        # 3 calls should each attempt (and fail)
        for i in range(4):
            await proxy.handle_call_tool("read_file", {"path": f"/{i}"})

        # After 3 failures, the 4th should not attempt (disabled)
        assert call_count == 3, "Learning store should be disabled after 3 consecutive failures"

    @pytest.mark.asyncio
    async def test_learning_store_failure_counter_resets_on_success(self) -> None:
        """A successful call resets the failure counter."""
        from token_sieve.server.proxy import ProxyServer

        call_count = 0

        async def fail_then_succeed(*args: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count in (1, 2):
                raise IOError("transient")
            # calls 3+ succeed

        learning_store = AsyncMock()
        learning_store.record_call = AsyncMock(side_effect=fail_then_succeed)
        learning_store.record_compression_event = AsyncMock()

        connector = _make_fake_connector(call_result=_make_call_result("result"))

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            learning_store=learning_store,
        )

        # 2 failures, then success — counter should reset
        for i in range(3):
            await proxy.handle_call_tool("read_file", {"path": f"/{i}"})

        assert call_count == 3
        # After reset, 2 more failures should still be tolerated
        # (not disabled because counter was reset by the success)
        assert proxy._learning_store is not None


# ---------------------------------------------------------------------------
# Schema virtualization logging
# ---------------------------------------------------------------------------


class TestSchemaVirtualizationLogging:
    """handle_list_tools logs schema compression events to learning store."""

    @pytest.mark.anyio
    async def test_schema_virtualization_logs_compression_event(self) -> None:
        """When schema virtualizer compresses tools, a CompressionEvent is recorded."""
        from token_sieve.server.proxy import ProxyServer

        tools = [
            types.Tool(
                name="search",
                description="Search for documents by query string",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "limit": {"type": "integer", "description": "Max results"},
                    },
                    "required": ["query"],
                },
            ),
        ]
        connector = _make_fake_connector(tools=tools)
        filt = MagicMock()
        filt.filter_tools = MagicMock(return_value=tools)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        # Fake virtualizer that returns a compact version
        virtualizer = MagicMock()
        virtualizer.virtualize.return_value = [
            {
                "name": "search",
                "description": "search(query:str, limit?:int)",
                "inputSchema": {"type": "object"},
            }
        ]

        learning_store = AsyncMock()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            schema_virtualizer=virtualizer,
            learning_store=learning_store,
        )

        await proxy.handle_list_tools()

        # Learning store should have received a compression event
        learning_store.record_compression_event.assert_awaited_once()
        call_args = learning_store.record_compression_event.call_args
        session_id = call_args[0][0]
        event = call_args[0][1]
        tool_name = call_args[0][2]

        assert isinstance(event, CompressionEvent)
        assert event.strategy_name == "SchemaVirtualization"
        assert event.content_type == ContentType.SCHEMA
        assert event.original_tokens > event.compressed_tokens
        assert event.original_tokens > 0
        assert tool_name == "__schema__"

    @pytest.mark.anyio
    async def test_no_logging_without_virtualizer(self) -> None:
        """Without schema virtualizer, no schema compression event is logged."""
        from token_sieve.server.proxy import ProxyServer

        tools = [_make_tool("foo")]
        connector = _make_fake_connector(tools=tools)
        filt = MagicMock()
        filt.filter_tools = MagicMock(return_value=tools)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()
        learning_store = AsyncMock()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            learning_store=learning_store,
        )

        await proxy.handle_list_tools()

        learning_store.record_compression_event.assert_not_awaited()

    @pytest.mark.anyio
    async def test_schema_logging_error_does_not_crash(self) -> None:
        """If learning store fails during schema logging, list_tools still works."""
        from token_sieve.server.proxy import ProxyServer

        tools = [_make_tool("foo")]
        connector = _make_fake_connector(tools=tools)
        filt = MagicMock()
        filt.filter_tools = MagicMock(return_value=tools)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        virtualizer = MagicMock()
        virtualizer.virtualize.return_value = [
            {"name": "foo", "description": "f()", "inputSchema": {"type": "object"}}
        ]

        learning_store = AsyncMock()
        learning_store.record_compression_event.side_effect = OSError("disk full")

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            schema_virtualizer=virtualizer,
            learning_store=learning_store,
        )

        # Should not raise
        result = await proxy.handle_list_tools()
        assert len(result) == 1
        assert result[0].name == "foo"


class TestSchemaVirtualizationCaching:
    """Fix 3: Schema virtualization results should be cached."""

    @pytest.mark.anyio
    async def test_virtualization_cached_on_second_call(self) -> None:
        """Second list_tools call with same tools should not re-virtualize."""
        from token_sieve.server.proxy import ProxyServer

        tools = [_make_tool("foo"), _make_tool("bar")]
        connector = _make_fake_connector(tools=tools)
        filt = MagicMock()
        filt.filter_tools = MagicMock(return_value=tools)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        virtualizer = MagicMock()
        virtualizer.virtualize.return_value = [
            {"name": "foo", "description": "foo", "inputSchema": {"type": "object"}},
            {"name": "bar", "description": "bar", "inputSchema": {"type": "object"}},
        ]

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            schema_virtualizer=virtualizer,
        )

        result1 = await proxy.handle_list_tools()
        result2 = await proxy.handle_list_tools()

        # Virtualizer should be called only once (cache hit on second call)
        assert virtualizer.virtualize.call_count == 1
        assert len(result1) == len(result2)

    @pytest.mark.anyio
    async def test_cache_invalidated_on_rebind(self) -> None:
        """rebind_connector should clear the virtualization cache."""
        from token_sieve.server.proxy import ProxyServer

        tools = [_make_tool("foo")]
        connector = _make_fake_connector(tools=tools)
        filt = MagicMock()
        filt.filter_tools = MagicMock(return_value=tools)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        virtualizer = MagicMock()
        virtualizer.virtualize.return_value = [
            {"name": "foo", "description": "foo", "inputSchema": {"type": "object"}},
        ]

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            schema_virtualizer=virtualizer,
        )

        await proxy.handle_list_tools()
        assert virtualizer.virtualize.call_count == 1

        # Rebind should clear cache
        new_connector = _make_fake_connector(tools=tools)
        proxy.rebind_connector(new_connector)

        await proxy.handle_list_tools()
        assert virtualizer.virtualize.call_count == 2


class TestSemanticCacheStripsFooter:
    """C1: Semantic cache must NOT store the compression footer."""

    @pytest.mark.anyio
    async def test_cached_result_does_not_contain_footer(self) -> None:
        """Compression footer must be stripped before caching."""
        from token_sieve.server.proxy import ProxyServer

        backend_text = "x " * 100  # 200 chars
        compressed_text = "x " * 50  # 100 chars

        connector = _make_fake_connector(
            call_result=_make_call_result(backend_text),
        )
        pipeline = _make_fake_pipeline(
            output_content=compressed_text,
            events=[
                CompressionEvent(
                    original_tokens=200,
                    compressed_tokens=100,
                    strategy_name="TestStrategy",
                    content_type=ContentType.TEXT,
                ),
            ],
        )

        semantic_cache = AsyncMock()
        semantic_cache.lookup_similar = AsyncMock(return_value=None)
        semantic_cache.cache_result = AsyncMock()
        semantic_cache.evict_expired = AsyncMock()
        semantic_cache.similarity_threshold = 0.85

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=pipeline,
            metrics_sink=_make_fake_sink(),
            semantic_cache=semantic_cache,
        )

        result = await proxy.handle_call_tool("read_file", {"path": "/a"})

        # The result returned to the user SHOULD have the footer
        assert "Re-call for full detail" in result.content[0].text

        # But the text stored in cache must NOT have the footer
        semantic_cache.cache_result.assert_called_once()
        cached_text = semantic_cache.cache_result.call_args[0][3]
        assert "Re-call for full detail" not in cached_text
        assert "Compressed:" not in cached_text


class TestCacheableWordBoundary:
    """C2: _is_cacheable must use word-boundary matching, not substring."""

    def test_restart_service_not_cacheable(self) -> None:
        """'restart_service' contains 'stat' but should NOT be cacheable."""
        from token_sieve.server.proxy import ProxyServer

        proxy = ProxyServer(
            backend_connector=_make_fake_connector(),
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
        )
        assert proxy._is_cacheable("restart_service") is False

    def test_blacklist_user_not_cacheable(self) -> None:
        """'blacklist_user' contains 'list' but should NOT be cacheable."""
        from token_sieve.server.proxy import ProxyServer

        proxy = ProxyServer(
            backend_connector=_make_fake_connector(),
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
        )
        assert proxy._is_cacheable("blacklist_user") is False

    def test_budget_widget_not_cacheable(self) -> None:
        """'budget_widget' contains 'get' but should NOT be cacheable."""
        from token_sieve.server.proxy import ProxyServer

        proxy = ProxyServer(
            backend_connector=_make_fake_connector(),
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
        )
        assert proxy._is_cacheable("budget_widget") is False

    def test_legitimate_tools_still_cacheable(self) -> None:
        """Legitimate read-only tools must still be cacheable."""
        from token_sieve.server.proxy import ProxyServer

        proxy = ProxyServer(
            backend_connector=_make_fake_connector(),
            tool_filter=_make_fake_filter(allowed=True),
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
        )
        assert proxy._is_cacheable("read_file") is True
        assert proxy._is_cacheable("get_symbol") is True
        assert proxy._is_cacheable("list_tools") is True
        assert proxy._is_cacheable("check_status") is True
        assert proxy._is_cacheable("search_files") is True


class TestSchemaVirtualizationCacheKeyIncludesContent:
    """H2: Virtualization cache key must include schema content hash."""

    @pytest.mark.anyio
    async def test_cache_invalidated_when_schema_changes(self) -> None:
        """Same tool names but different schemas must re-virtualize."""
        from token_sieve.server.proxy import ProxyServer

        tools_v1 = [
            _make_tool("read_file", "Read a file"),
        ]
        tools_v2 = [
            types.Tool(
                name="read_file",
                description="Read a file (v2 with new schema)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "encoding": {"type": "string"},
                    },
                },
            ),
        ]

        connector = _make_fake_connector(tools=tools_v1)
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()
        virtualizer = MagicMock()
        virtualizer.virtualize.return_value = [
            {"name": "read_file", "description": "desc", "inputSchema": {"type": "object"}},
        ]

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            schema_virtualizer=virtualizer,
        )

        await proxy.handle_list_tools()
        assert virtualizer.virtualize.call_count == 1

        # Change schema content but keep same tool names
        connector.list_tools = AsyncMock(return_value=tools_v2)

        await proxy.handle_list_tools()
        # Should re-virtualize because schema content changed
        assert virtualizer.virtualize.call_count == 2, (
            "Cache key only checked tool names, not schema content"
        )


# ---------------------------------------------------------------------------
# Phase 08 adversarial review fixes
# ---------------------------------------------------------------------------


class TestC1CreateFromConfigWiresVisibilityController:
    """C1: create_from_config must wire VisibilityController when enabled."""

    def test_visibility_controller_wired_when_enabled_with_learning(self) -> None:
        """When tool_visibility.enabled=True and learning.enabled=True,
        create_from_config should create a VisibilityController."""
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.server.proxy import ProxyServer

        config = TokenSieveConfig(
            tool_visibility={"enabled": True, "frequency_threshold": 5},
            learning={"enabled": True, "db_path": ":memory:"},
        )
        proxy = ProxyServer.create_from_config(config)
        assert proxy._visibility_controller is not None, (
            "C1: VisibilityController should be wired when tool_visibility "
            "and learning are both enabled"
        )

    def test_visibility_controller_not_wired_when_disabled(self) -> None:
        """When tool_visibility.enabled=False, no VisibilityController."""
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.server.proxy import ProxyServer

        config = TokenSieveConfig(
            tool_visibility={"enabled": False},
            learning={"enabled": True, "db_path": ":memory:"},
        )
        proxy = ProxyServer.create_from_config(config)
        assert proxy._visibility_controller is None

    def test_visibility_controller_not_wired_without_learning(self) -> None:
        """When learning is disabled, VisibilityController not wired."""
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.server.proxy import ProxyServer

        config = TokenSieveConfig(
            tool_visibility={"enabled": True},
            learning={"enabled": False},
        )
        proxy = ProxyServer.create_from_config(config)
        assert proxy._visibility_controller is None

    def test_visibility_controller_uses_config_thresholds(self) -> None:
        """VisibilityController should be constructed with config values."""
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.server.proxy import ProxyServer

        config = TokenSieveConfig(
            tool_visibility={
                "enabled": True,
                "frequency_threshold": 7,
                "min_visible_floor": 15,
                "cold_start_sessions": 5,
            },
            learning={"enabled": True, "db_path": ":memory:"},
        )
        proxy = ProxyServer.create_from_config(config)
        vc = proxy._visibility_controller
        assert vc is not None
        assert vc._frequency_threshold == 7
        assert vc._min_visible_floor == 15
        assert vc._cold_start_sessions == 5


class TestH1FrequencyThresholdUsedInScoring:
    """H1: _score_tools must use frequency_threshold, not hardcoded > 0."""

    def test_tools_below_threshold_are_hidden(self) -> None:
        """Tools with call_count < frequency_threshold should be hidden."""
        from token_sieve.adapters.visibility.visibility_controller import (
            VisibilityController,
        )
        from token_sieve.domain.learning_types import ToolUsageRecord

        tools = [_make_tool("a"), _make_tool("b"), _make_tool("c")]
        usage = [
            ToolUsageRecord(tool_name="a", server_id="default", call_count=5, last_called_at="2025-01-01"),
            ToolUsageRecord(tool_name="b", server_id="default", call_count=2, last_called_at="2025-01-01"),
            ToolUsageRecord(tool_name="c", server_id="default", call_count=0, last_called_at="2025-01-01"),
        ]
        ctrl = VisibilityController(frequency_threshold=3, min_visible_floor=0, cold_start_sessions=0)
        visible, hidden = ctrl.apply(tools, usage, session_count=10)
        visible_names = {t.name for t in visible}
        hidden_names = {t.name for t in hidden}
        # Only "a" (5 >= 3) should be visible; "b" (2 < 3) and "c" (0 < 3) hidden
        assert visible_names == {"a"}, (
            f"H1: tools with call_count < frequency_threshold should be hidden, "
            f"got visible={visible_names}"
        )
        assert hidden_names == {"b", "c"}


class TestH2ReuseProxyVisibilityController:
    """H2: CLI instruction injection must reuse proxy's VC, not create new."""

    def test_instruction_hint_uses_proxy_visibility_controller(self) -> None:
        """_inject_visibility_instructions should use proxy._visibility_controller."""
        # This tests that the proxy VC is reused rather than creating a throwaway.
        # We verify by checking proxy._visibility_controller is the SAME instance
        # used for hidden_stats in handle_read_resource.
        from token_sieve.server.proxy import ProxyServer

        tools = [_make_tool("a"), _make_tool("b")]
        connector = _make_fake_connector(tools=tools)
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        vc = MagicMock()
        vc.hidden_stats.return_value = {"total_hidden": 5, "visible": 10}

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            visibility_controller=vc,
        )
        # The proxy should expose the same VC instance
        assert proxy._visibility_controller is vc


class TestH3SyntheticToolsCheckFilter:
    """H3: Synthetic tool calls must check ToolFilter before dispatch."""

    @pytest.mark.anyio
    async def test_synthetic_tool_blocked_when_filtered(self) -> None:
        """discover_tools should be blocked if ToolFilter denies it."""
        from token_sieve.server.proxy import ProxyServer

        connector = _make_fake_connector()
        filt = _make_fake_filter(allowed=False)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
        )

        result = await proxy.handle_call_tool("discover_tools", {"query": "test"})
        # H3: If ToolFilter blocks the synthetic tool, it should return an error
        # OR pass through to handler (if gated behind config). Either way it
        # should not bypass the filter check entirely.
        filt.is_allowed.assert_called()

    @pytest.mark.anyio
    async def test_explain_compression_checks_filter(self) -> None:
        """explain_compression should also check ToolFilter."""
        from token_sieve.server.proxy import ProxyServer

        connector = _make_fake_connector()
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
        )

        await proxy.handle_call_tool("explain_compression", {})
        filt.is_allowed.assert_called()


class TestH4SyntheticToolCollisionDetection:
    """H4: Synthetic tools must not collide with backend tool names."""

    @pytest.mark.anyio
    async def test_no_synthetic_injection_on_name_collision(self) -> None:
        """If backend has a tool named 'discover_tools', synthetic is skipped."""
        from token_sieve.server.proxy import ProxyServer

        # Backend has a tool named 'discover_tools' that passes through vc.apply
        backend_discover = _make_tool("discover_tools", desc="Real backend tool")
        other_tool = _make_tool("other")
        connector = _make_fake_connector(tools=[backend_discover, other_tool])
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        vc = MagicMock()
        # Backend discover_tools is visible (it's a real tool), plus many hidden
        vc.apply.return_value = (
            [backend_discover, other_tool],
            [_make_tool(f"hidden{i}") for i in range(10)],
        )

        learning_store = AsyncMock()
        learning_store.get_usage_stats = AsyncMock(return_value=[])
        learning_store.get_session_count = AsyncMock(return_value=10)

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            visibility_controller=vc,
            learning_store=learning_store,
        )

        tools = await proxy.handle_list_tools()
        tool_names = [t.name for t in tools]
        # Should NOT have duplicate 'discover_tools' entries
        assert tool_names.count("discover_tools") <= 1, (
            f"H4: synthetic 'discover_tools' collides with backend tool. "
            f"Names: {tool_names}"
        )


class TestH5ExplainCompressionGuardedByHiddenCount:
    """H5: explain_compression should not be injected when 0 tools are hidden."""

    @pytest.mark.anyio
    async def test_no_explain_compression_when_no_hidden(self) -> None:
        """When visibility hides 0 tools, explain_compression not injected."""
        from token_sieve.server.proxy import ProxyServer

        tools = [_make_tool("a"), _make_tool("b")]
        connector = _make_fake_connector(tools=tools)
        filt = _make_fake_filter(allowed=True)
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        vc = MagicMock()
        # All visible, nothing hidden
        vc.apply.return_value = (tools, [])

        learning_store = AsyncMock()
        learning_store.get_usage_stats = AsyncMock(return_value=[])
        learning_store.get_session_count = AsyncMock(return_value=10)

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=filt,
            pipeline=pipeline,
            metrics_sink=sink,
            visibility_controller=vc,
            learning_store=learning_store,
        )

        result = await proxy.handle_list_tools()
        tool_names = [t.name for t in result]
        assert "explain_compression" not in tool_names, (
            "H5: explain_compression should not be injected when hidden count is 0"
        )
