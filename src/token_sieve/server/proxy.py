"""MCP proxy server — the core of token-sieve.

Sits between Claude Code and a backend MCP server. Intercepts:
- tools/list: filters tools via ToolFilter
- tools/call: forwards to backend, compresses results via CompressionPipeline

Runs as a stdio MCP server that Claude Code connects to directly.
"""
from __future__ import annotations

import asyncio
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.models import InitializationOptions

from token_sieve.config.schema import TokenSieveConfig
from token_sieve.domain.model import ContentEnvelope, ContentType
from token_sieve.domain.pipeline import CompressionPipeline
from token_sieve.server.metrics_sink import StderrMetricsSink
from token_sieve.server.tool_filter import ToolFilter


class ProxyServer:
    """MCP proxy server with tool filtering and result compression.

    Constructed with pre-wired dependencies (connector, filter, pipeline, sink).
    The create_from_config() class method builds all dependencies from config.
    """

    def __init__(
        self,
        backend_connector: Any,
        tool_filter: ToolFilter,
        pipeline: CompressionPipeline,
        metrics_sink: StderrMetricsSink,
        call_cache: Any | None = None,
        invalidator: Any | None = None,
        reranker: Any | None = None,
        schema_cache: Any | None = None,
    ) -> None:
        self._connector = backend_connector
        self._filter = tool_filter
        self._pipeline = pipeline
        self._sink = metrics_sink
        self._call_cache = call_cache
        self._invalidator = invalidator
        self._reranker = reranker
        self._schema_cache = schema_cache
        self._server = self._build_mcp_server()

    def _build_mcp_server(self) -> Server:
        """Create the low-level MCP Server with handlers wired to self."""
        server = Server("token-sieve")

        @server.list_tools()
        async def handle_list_tools() -> list[types.Tool]:
            return await self.handle_list_tools()

        @server.call_tool()
        async def handle_call_tool(
            name: str, arguments: dict[str, Any] | None
        ) -> types.CallToolResult:
            return await self.handle_call_tool(name, arguments or {})

        return server

    async def handle_list_tools(self) -> list[types.Tool]:
        """Return backend tool list, filtered through ToolFilter.

        If SchemaCache is configured, uses it for tool retrieval.
        If StatisticalReranker is configured, reorders tools by usage.
        """
        if self._schema_cache is not None:
            tools = await self._schema_cache.list_tools()
        else:
            tools = await self._connector.list_tools()

        filtered = self._filter.filter_tools(tools)

        if self._reranker is not None:
            from token_sieve.domain.tool_metadata import ToolMetadata

            # Convert types.Tool to ToolMetadata for reranker
            tool_metas = [
                ToolMetadata(
                    name=t.name,
                    title=getattr(t, "title", None),
                    description=t.description or "",
                    input_schema=t.inputSchema or {},
                )
                for t in filtered
            ]
            reranked = self._reranker.transform(tool_metas)
            # Rebuild types.Tool list in reranked order
            tool_by_name = {t.name: t for t in filtered}
            filtered = [tool_by_name[m.name] for m in reranked if m.name in tool_by_name]

        return filtered

    async def handle_call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        """Forward tool call to backend, compress text results.

        1. Gate: reject blocked tools with error response
        2. Check call cache for exact match (short-circuit)
        3. Forward to backend via connector
        4. If backend error, pass through as-is
        5. For text content: wrap in ContentEnvelope, run pipeline, emit metrics
        6. Non-text content passes through unchanged
        7. Cache result and record usage
        8. Trigger invalidation for mutating calls
        """
        # Gate: blocked tools
        if not self._filter.is_allowed(name):
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Tool '{name}' is blocked by token-sieve filter",
                    )
                ],
                isError=True,
            )

        # Short-circuit: check call cache before forwarding
        if self._call_cache is not None:
            cached = self._call_cache.get(name, arguments)
            if cached is not None:
                # Record usage even for cached hits
                if self._reranker is not None:
                    self._reranker.record_call(name)
                return cached

        # Forward to backend
        result = await self._connector.call_tool(name, arguments)

        # Backend errors pass through uncompressed
        if result.isError:
            return result

        # Process text content through compression pipeline
        compressed_content: list[types.TextContent | types.ImageContent | types.EmbeddedResource] = []
        has_text = False

        for item in result.content:
            if isinstance(item, types.TextContent):
                has_text = True
                envelope = ContentEnvelope(
                    content=item.text,
                    content_type=ContentType.TEXT,
                )
                compressed_envelope, events = self._pipeline.process(envelope)

                # Emit metrics for each compression event
                for event in events:
                    msg = self._sink.format_event(event, tool_name=name)
                    self._sink.emit(msg)

                compressed_content.append(
                    types.TextContent(type="text", text=compressed_envelope.content)
                )
            else:
                # Non-text content (images, etc.) passes through unchanged
                compressed_content.append(item)

        if not has_text:
            final_result = result
        else:
            final_result = types.CallToolResult(
                content=compressed_content,
                isError=False,
            )

        # Cache the result
        if self._call_cache is not None:
            self._call_cache.put(name, arguments, final_result)

        # Record usage in reranker
        if self._reranker is not None:
            self._reranker.record_call(name)

        # Trigger invalidation for mutating calls
        if self._invalidator is not None and self._invalidator.is_mutating(name):
            self._invalidator.invalidate_for(name)

        return final_result

    async def run(self) -> None:
        """Start the MCP server on stdio transport."""
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await self._server.run(
                read_stream,
                write_stream,
                self._server.create_initialization_options(),
            )

    # Adapter name -> (module_path, class_name) registry
    _ADAPTER_REGISTRY: dict[str, tuple[str, str]] = {
        "whitespace_normalizer": (
            "token_sieve.adapters.compression.whitespace_normalizer",
            "WhitespaceNormalizer",
        ),
        "null_field_elider": (
            "token_sieve.adapters.compression.null_field_elider",
            "NullFieldElider",
        ),
        "path_prefix_deduplicator": (
            "token_sieve.adapters.compression.path_prefix_deduplicator",
            "PathPrefixDeduplicator",
        ),
        "timestamp_normalizer": (
            "token_sieve.adapters.compression.timestamp_normalizer",
            "TimestampNormalizer",
        ),
        "log_level_filter": (
            "token_sieve.adapters.compression.log_level_filter",
            "LogLevelFilter",
        ),
        "error_stack_compressor": (
            "token_sieve.adapters.compression.error_stack_compressor",
            "ErrorStackCompressor",
        ),
        "code_comment_stripper": (
            "token_sieve.adapters.compression.code_comment_stripper",
            "CodeCommentStripper",
        ),
        "sentence_scorer": (
            "token_sieve.adapters.compression.sentence_scorer",
            "SentenceScorer",
        ),
        "rle_encoder": (
            "token_sieve.adapters.compression.rle_encoder",
            "RunLengthEncoder",
        ),
        "toon_compressor": (
            "token_sieve.adapters.compression.toon_compressor",
            "ToonCompressor",
        ),
        "yaml_transcoder": (
            "token_sieve.adapters.compression.yaml_transcoder",
            "YamlTranscoder",
        ),
        "file_redirect": (
            "token_sieve.adapters.compression.file_redirect",
            "FileRedirectStrategy",
        ),
        "smart_truncation": (
            "token_sieve.adapters.compression.smart_truncation",
            "SmartTruncation",
        ),
        "passthrough": (
            "token_sieve.adapters.compression.passthrough",
            "PassthroughStrategy",
        ),
        "truncation": (
            "token_sieve.adapters.compression.truncation",
            "TruncationCompressor",
        ),
    }

    @classmethod
    def create_from_config(cls, config: TokenSieveConfig) -> ProxyServer:
        """Wire all dependencies from config and return a ProxyServer.

        Creates: ToolFilter, CompressionPipeline (with configured strategies),
        StderrMetricsSink. BackendConnector is NOT created here -- it requires
        an active async session, so it's injected at run-time.
        """
        import importlib

        from token_sieve.domain.counters import CharEstimateCounter

        # Build tool filter
        tool_filter = ToolFilter.from_config(config.filter)

        # Build compression pipeline
        counter = CharEstimateCounter()
        pipeline = CompressionPipeline(
            counter=counter,
            size_gate_threshold=config.compression.size_gate_threshold,
        )

        if config.compression.enabled:
            for adapter_cfg in config.compression.adapters:
                if not adapter_cfg.enabled:
                    continue

                registry_entry = cls._ADAPTER_REGISTRY.get(adapter_cfg.name)
                if registry_entry is None:
                    print(
                        f"Warning: unknown adapter '{adapter_cfg.name}', skipping",
                        file=__import__("sys").stderr,
                    )
                    continue

                module_path, class_name = registry_entry
                try:
                    mod = importlib.import_module(module_path)
                    adapter_cls = getattr(mod, class_name)
                    adapter = adapter_cls(**adapter_cfg.settings)
                except Exception as exc:
                    print(
                        f"Warning: failed to instantiate adapter "
                        f"'{adapter_cfg.name}': {exc}",
                        file=__import__("sys").stderr,
                    )
                    continue

                pipeline.register(ContentType.TEXT, adapter)

        # Build metrics sink
        sink = StderrMetricsSink()

        # Build cache, reranker, and invalidator
        from token_sieve.adapters.cache.call_cache import IdempotentCallCache
        from token_sieve.adapters.cache.diff_state_store import DiffStateStore
        from token_sieve.adapters.cache.invalidation import WriteThruInvalidator
        from token_sieve.adapters.cache.schema_cache import SchemaCache
        from token_sieve.adapters.rerank.statistical_reranker import StatisticalReranker

        call_cache = IdempotentCallCache(max_entries=config.cache.call_cache_max)
        diff_store = DiffStateStore(max_entries=config.cache.diff_store_max)
        invalidator = WriteThruInvalidator()
        invalidator.register_observer(call_cache)
        invalidator.register_observer(diff_store)

        reranker: StatisticalReranker | None = None
        if config.reranker.enabled:
            reranker = StatisticalReranker(
                max_tools=config.reranker.max_tools,
                recency_weight=config.reranker.recency_weight,
            )

        # Placeholder connector -- real one requires async backend session
        # For now, create a stub that will be replaced at run-time
        stub_connector = _StubConnector()

        schema_cache = SchemaCache(
            provider=stub_connector,
            ttl_seconds=config.cache.schema_cache_ttl,
        )

        return cls(
            backend_connector=stub_connector,
            tool_filter=tool_filter,
            pipeline=pipeline,
            metrics_sink=sink,
            call_cache=call_cache,
            invalidator=invalidator,
            reranker=reranker,
            schema_cache=schema_cache,
        )


class _StubConnector:
    """Placeholder connector for create_from_config (no active session yet)."""

    async def list_tools(self) -> list[types.Tool]:
        return []

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text="No backend configured",
                )
            ],
            isError=True,
        )
