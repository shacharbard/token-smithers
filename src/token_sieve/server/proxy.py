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
from token_sieve.domain.model import CompressionEvent, ContentEnvelope, ContentType
from token_sieve.domain.pipeline import CompressionPipeline
from token_sieve.server.metrics_sink import StderrMetricsSink
from token_sieve.server.tool_filter import ToolFilter


class ProxyServer:
    """MCP proxy server with tool filtering and result compression.

    Constructed with pre-wired dependencies (connector, filter, pipeline, sink).
    The create_from_config() class method builds all dependencies from config.
    """

    # Safe-by-default: only tools matching these read-only patterns use semantic cache.
    # Unknown tools (bash, execute, mv, etc.) are denied cache by default.
    _CACHEABLE_PATTERNS: frozenset[str] = frozenset({
        "read", "get", "list", "search", "find", "describe", "show", "view",
        "stat", "info", "status", "query", "fetch", "check", "count", "browse",
        "outline", "hover", "symbols", "references", "diagnostics", "toc",
        "section", "lookup", "suggest", "resolve",
    })

    _MAX_LEARNING_FAILURES: int = 3

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
        schema_virtualizer: Any | None = None,
        learning_store: Any | None = None,
        semantic_cache: Any | None = None,
        metrics_collector: Any | None = None,
        metrics_writer: Any | None = None,
    ) -> None:
        self._connector = backend_connector
        self._filter = tool_filter
        self._pipeline = pipeline
        self._sink = metrics_sink
        self._call_cache = call_cache
        self._invalidator = invalidator
        self._reranker = reranker
        self._schema_cache = schema_cache
        self._schema_virtualizer = schema_virtualizer
        self._learning_store = learning_store
        self._learning_store_failures: int = 0
        self._semantic_cache = semantic_cache
        self._metrics_collector = metrics_collector
        self._metrics_writer = metrics_writer
        self._virtualized_cache_key: tuple[str, ...] | None = None
        self._virtualized_cache_result: list[types.Tool] | None = None
        self._server = self._build_mcp_server()

    def rebind_connector(self, connector: Any) -> None:
        """Replace the backend connector and update SchemaCache provider.

        Called by _run_proxy after the real backend session is established.
        """
        self._connector = connector
        self._virtualized_cache_key = None
        self._virtualized_cache_result = None
        if self._schema_cache is not None:
            self._schema_cache._provider = connector
            self._schema_cache.invalidate()

    def _is_cacheable(self, name: str) -> bool:
        """Check if a tool name matches known read-only patterns (allowlist).

        Returns True only if the tool name contains at least one cacheable
        substring. Unknown tools default to NOT cacheable (safe-by-default).
        """
        lower = name.lower()
        return any(pattern in lower for pattern in self._CACHEABLE_PATTERNS)

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

        # Register resource handlers for dashboard
        if self._metrics_collector is not None:
            from mcp.types import Resource

            @server.list_resources()
            async def handle_list_resources() -> list[Resource]:
                return await self.handle_list_resources()

            @server.read_resource()
            async def handle_read_resource(uri: str) -> str:
                return await self.handle_read_resource(uri)

        return server

    async def handle_list_resources(self) -> list[Any]:
        """Return available MCP resources."""
        from mcp.types import Resource

        resources = []
        if self._metrics_collector is not None:
            resources.append(
                Resource(
                    uri="token-sieve://stats",
                    name="Token Sieve Statistics",
                    description="Session compression metrics and per-strategy breakdown",
                    mimeType="application/json",
                )
            )
        return resources

    async def handle_read_resource(self, uri: str) -> str:
        """Read an MCP resource by URI."""
        import json

        if uri == "token-sieve://stats" and self._metrics_collector is not None:
            data = {
                "session_summary": self._metrics_collector.session_summary(),
                "strategy_breakdown": self._metrics_collector.strategy_breakdown(),
            }
            return json.dumps(data, indent=2)
        raise ValueError(f"Unknown resource: {uri}")

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

        # Schema virtualization: compress tool schemas after reranking
        if self._schema_virtualizer is not None:
            tools_key = tuple(t.name for t in filtered)
            if self._virtualized_cache_key == tools_key:
                return self._virtualized_cache_result  # type: ignore[return-value]
            pre_virtualized = filtered
            filtered = self._apply_schema_virtualization(filtered)
            self._virtualized_cache_key = tools_key
            self._virtualized_cache_result = filtered
            await self._log_schema_savings(pre_virtualized, filtered)

        return filtered

    def _apply_schema_virtualization(
        self, tools: list[types.Tool]
    ) -> list[types.Tool]:
        """Run schema virtualizer over tool list, returning virtualized tools."""
        # Convert to dicts for virtualizer
        tool_dicts = [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.inputSchema or {},
            }
            for t in tools
        ]
        # Get usage stats from reranker if available
        usage_stats: dict[str, int] | None = None
        if self._reranker is not None:
            usage_stats = {
                name: data.get("count", 0)
                for name, data in getattr(self._reranker, "_scores", {}).items()
            }
        virtualized = self._schema_virtualizer.virtualize(
            tool_dicts, usage_stats=usage_stats
        )
        # Rebuild types.Tool from virtualized dicts
        return [
            types.Tool(
                name=vt["name"],
                description=vt.get("description", ""),
                inputSchema=vt.get("inputSchema", {"type": "object"}),
            )
            for vt in virtualized
        ]

    async def _log_schema_savings(
        self,
        original: list[types.Tool],
        virtualized: list[types.Tool],
    ) -> None:
        """Log schema virtualization savings to the learning store."""
        if self._learning_store is None:
            return
        import json

        orig_size = sum(
            len(json.dumps({"name": t.name, "description": t.description or "",
                            "inputSchema": t.inputSchema or {}}, separators=(",", ":")))
            for t in original
        )
        virt_size = sum(
            len(json.dumps({"name": t.name, "description": t.description or "",
                            "inputSchema": t.inputSchema or {}}, separators=(",", ":")))
            for t in virtualized
        )
        orig_tokens = max(1, orig_size // 4)
        virt_tokens = max(1, virt_size // 4) if virt_size > 0 else 0
        if orig_tokens <= virt_tokens:
            return
        event = CompressionEvent(
            original_tokens=orig_tokens,
            compressed_tokens=virt_tokens,
            strategy_name="SchemaVirtualization",
            content_type=ContentType.SCHEMA,
        )
        try:
            await self._learning_store.record_compression_event(
                "session", event, "__schema__"
            )
        except Exception:
            pass

    async def _check_semantic_cache(
        self, name: str, arguments: dict[str, Any]
    ) -> types.CallToolResult | None:
        """Check semantic cache for a similar prior result."""
        from token_sieve.adapters.cache.param_normalizer import (
            compute_args_hash,
            normalize_args,
        )

        # F4: Run TTL eviction before lookup
        await self._semantic_cache.evict_expired()

        args_normalized = normalize_args(arguments)
        # F3: Use configured threshold instead of hardcoded 0.85
        hit = await self._semantic_cache.lookup_similar(
            name, args_normalized, threshold=self._semantic_cache.similarity_threshold
        )
        if hit is not None:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=hit.result_text)],
                isError=False,
            )
        return None

    async def _store_semantic_cache(
        self,
        name: str,
        arguments: dict[str, Any],
        result: types.CallToolResult,
    ) -> None:
        """Store a result in the semantic cache."""
        try:
            from token_sieve.adapters.cache.param_normalizer import (
                compute_args_hash,
                normalize_args,
            )

            # Only cache text results
            texts = [
                item.text
                for item in result.content
                if isinstance(item, types.TextContent) and item.text
            ]
            if not texts:
                return
            combined = "\n".join(texts)
            args_normalized = normalize_args(arguments)
            args_hash = compute_args_hash(arguments)
            await self._semantic_cache.cache_result(
                name, args_normalized, args_hash, combined
            )
        except Exception as exc:
            print(
                f"Warning: semantic cache store failed: {exc}",
                file=__import__("sys").stderr,
            )

    async def _record_to_learning_store(
        self, name: str, events: list[Any]
    ) -> None:
        """Record tool call and compression events to learning store.

        Tolerates up to _MAX_LEARNING_FAILURES consecutive errors before
        permanently disabling the store.  A successful call resets the
        failure counter so transient errors don't accumulate.
        """
        try:
            await self._learning_store.record_call(name, "default")
            for event in events:
                await self._learning_store.record_compression_event(
                    "session", event, name
                )
            # Success — reset failure counter
            self._learning_store_failures = 0
        except Exception as exc:
            self._learning_store_failures += 1
            print(
                f"Warning: learning store I/O failed "
                f"({self._learning_store_failures}/{self._MAX_LEARNING_FAILURES}): {exc}",
                file=__import__("sys").stderr,
            )
            if self._learning_store_failures >= self._MAX_LEARNING_FAILURES:
                print(
                    "Warning: learning store permanently disabled after "
                    f"{self._MAX_LEARNING_FAILURES} consecutive failures",
                    file=__import__("sys").stderr,
                )
                self._learning_store = None

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

        # Short-circuit: check semantic cache before exact-match cache
        # Safe-by-default: only use cache for known read-only tools (allowlist)
        if self._semantic_cache is not None and self._is_cacheable(name):
            sem_result = await self._check_semantic_cache(name, arguments)
            if sem_result is not None:
                if self._reranker is not None:
                    self._reranker.record_call(name)
                return sem_result

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
        events_for_learning: list[Any] = []
        has_text = False

        for item in result.content:
            if isinstance(item, types.TextContent):
                has_text = True

                # Guard: empty text passes through unchanged (ContentEnvelope
                # rejects empty content, and there's nothing to compress)
                if not item.text:
                    compressed_content.append(item)
                    continue

                envelope = ContentEnvelope(
                    content=item.text,
                    content_type=ContentType.TEXT,
                    metadata={"source_tool": name},
                )
                compressed_envelope, events = self._pipeline.process(envelope)

                # Emit metrics for each compression event
                for event in events:
                    msg = self._sink.format_event(event, tool_name=name)
                    self._sink.emit(msg)
                    events_for_learning.append(event)

                # Transparency footer: show compression stats
                output_text = compressed_envelope.content
                if events:
                    total_original = events[0].original_tokens
                    total_compressed = events[-1].compressed_tokens
                    if total_compressed < total_original:
                        output_text += (
                            f"\n[Compressed: {total_original}\u2192"
                            f"{total_compressed} tokens. "
                            f"Re-call for full detail.]"
                        )

                compressed_content.append(
                    types.TextContent(type="text", text=output_text)
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

        # Store in semantic cache
        if self._semantic_cache is not None:
            await self._store_semantic_cache(name, arguments, final_result)

        # Record usage in reranker
        if self._reranker is not None:
            self._reranker.record_call(name)

        # Record to learning store
        if self._learning_store is not None:
            await self._record_to_learning_store(name, events_for_learning)

        # Record to metrics collector (via writer if available, else direct)
        if self._metrics_writer is not None:
            for event in events_for_learning:
                self._metrics_writer.record_and_maybe_flush(event)
        elif self._metrics_collector is not None:
            for event in events_for_learning:
                self._metrics_collector.record(event)

        # Trigger invalidation for mutating calls
        if self._invalidator is not None and self._invalidator.is_mutating(name):
            self._invalidator.invalidate_for(name)

        return final_result

    async def run(self) -> None:
        """Start the MCP server on stdio transport."""
        try:
            async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
                await self._server.run(
                    read_stream,
                    write_stream,
                    self._server.create_initialization_options(),
                )
        finally:
            self._pipeline.cleanup()

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
        "key_aliasing": (
            "token_sieve.adapters.compression.key_aliasing",
            "KeyAliasingStrategy",
        ),
        "ast_skeleton": (
            "token_sieve.adapters.compression.ast_skeleton",
            "ASTSkeletonExtractor",
        ),
        "graph_encoder": (
            "token_sieve.adapters.compression.graph_encoder",
            "GraphAdjacencyEncoder",
        ),
        "progressive_disclosure": (
            "token_sieve.adapters.compression.progressive_disclosure",
            "ProgressiveDisclosureStrategy",
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

        # Phase 04: Schema virtualization
        schema_virtualizer = None
        if config.schema_virtualization.enabled:
            from token_sieve.adapters.schema.schema_virtualizer import SchemaVirtualizer

            schema_virtualizer = SchemaVirtualizer(
                frequent_threshold=config.schema_virtualization.frequent_call_threshold,
            )

        # Phase 04: Learning store (SQLite persistence)
        learning_store = None
        if config.learning.enabled:
            from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

            # Store will be initialized lazily at first use (async connect)
            # For now, store config for async init in _run_proxy
            learning_store = _DeferredLearningStore(
                db_path=config.learning.db_path,
            )

        # Phase 04: Semantic cache
        semantic_cache = None
        if config.semantic_cache.enabled:
            from token_sieve.adapters.cache.semantic_cache import SQLiteSemanticCache

            semantic_cache = _DeferredSemanticCache(
                max_entries=config.semantic_cache.max_entries,
                ttl_seconds=config.semantic_cache.ttl_seconds or 86400,
                similarity_threshold=config.semantic_cache.similarity_threshold,
            )
            # F1: Register semantic cache as invalidation observer
            invalidator.register_observer(semantic_cache)

        # Phase 04: Dashboard / metrics collector + file writer
        from token_sieve.domain.metrics import InMemoryMetricsCollector

        metrics_collector = None
        metrics_writer = None
        if config.dashboard.enabled:
            import os

            metrics_collector = InMemoryMetricsCollector()

            from token_sieve.server.metrics_writer import MetricsFileWriter

            expanded_path = os.path.expanduser(config.dashboard.metrics_file_path)
            metrics_writer = MetricsFileWriter(
                collector=metrics_collector,
                metrics_path=expanded_path,
            )

        proxy = cls(
            backend_connector=stub_connector,
            tool_filter=tool_filter,
            pipeline=pipeline,
            metrics_sink=sink,
            call_cache=call_cache,
            invalidator=invalidator,
            reranker=reranker,
            schema_cache=schema_cache,
            schema_virtualizer=schema_virtualizer,
            learning_store=learning_store,
            semantic_cache=semantic_cache,
            metrics_collector=metrics_collector,
            metrics_writer=metrics_writer,
        )

        # Self-tuning interval (calls between threshold adjustments)
        proxy._self_tune_interval = 50
        proxy._self_tune_call_count = 0

        return proxy


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


class _DeferredLearningStore:
    """Deferred learning store — wraps config for lazy async init.

    Since create_from_config is sync but SQLiteLearningStore.connect()
    is async, this wrapper defers actual DB connection until first use.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._store: Any = None

    async def _ensure_connected(self) -> Any:
        if self._store is None:
            import os

            from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

            expanded = os.path.expanduser(self._db_path)
            os.makedirs(os.path.dirname(expanded), exist_ok=True) if os.path.dirname(expanded) else None
            self._store = await SQLiteLearningStore.connect(expanded)
        return self._store

    async def record_call(self, tool_name: str, server_id: str) -> None:
        store = await self._ensure_connected()
        await store.record_call(tool_name, server_id)

    async def record_compression_event(
        self, session_id: str, event: Any, tool_name: str
    ) -> None:
        store = await self._ensure_connected()
        await store.record_compression_event(session_id, event, tool_name)

    async def record_compression_events_batch(
        self, session_id: str, events: list, tool_name: str
    ) -> None:
        store = await self._ensure_connected()
        await store.record_compression_events_batch(session_id, events, tool_name)

    async def get_usage_stats(self, server_id: str) -> list:
        store = await self._ensure_connected()
        return await store.get_usage_stats(server_id)

    async def record_cooccurrence(self, tool_a: str, tool_b: str) -> None:
        store = await self._ensure_connected()
        await store.record_cooccurrence(tool_a, tool_b)

    async def get_cooccurrence(self, tool_name: str) -> list:
        store = await self._ensure_connected()
        return await store.get_cooccurrence(tool_name)

    async def cache_result(
        self, tool_name: str, args_normalized: str, result: str
    ) -> None:
        store = await self._ensure_connected()
        await store.cache_result(tool_name, args_normalized, result)

    async def lookup_similar(
        self, tool_name: str, args_normalized: str, threshold: float
    ) -> str | None:
        store = await self._ensure_connected()
        return await store.lookup_similar(tool_name, args_normalized, threshold)


class _DeferredSemanticCache:
    """Deferred semantic cache — wraps config for lazy async init."""

    def __init__(
        self,
        max_entries: int = 1000,
        ttl_seconds: int = 86400,
        similarity_threshold: float = 0.85,
    ) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._similarity_threshold = similarity_threshold
        self._cache: Any = None

    @property
    def similarity_threshold(self) -> float:
        """Return the configured similarity threshold."""
        return self._similarity_threshold

    def invalidate_all(self) -> None:
        """Clear the underlying cache (InvalidationObserver protocol)."""
        self._cache = None

    async def _ensure_initialized(self) -> Any:
        if self._cache is None:
            from token_sieve.adapters.cache.semantic_cache import SQLiteSemanticCache

            self._cache = SQLiteSemanticCache(
                db_path=":memory:",
                max_entries=self._max_entries,
                ttl_seconds=self._ttl_seconds,
            )
            await self._cache.initialize()
        return self._cache

    async def lookup_similar(
        self,
        tool_name: str,
        args_normalized: str,
        threshold: float,
    ) -> Any:
        cache = await self._ensure_initialized()
        return await cache.lookup_similar(tool_name, args_normalized, threshold)

    async def cache_result(
        self,
        tool_name: str,
        args_normalized: str,
        args_hash: str,
        result: str,
    ) -> None:
        cache = await self._ensure_initialized()
        await cache.cache_result(tool_name, args_normalized, args_hash, result)

    async def evict_expired(self) -> int:
        cache = await self._ensure_initialized()
        return await cache.evict_expired()
