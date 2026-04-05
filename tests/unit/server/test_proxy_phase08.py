"""Tests for Phase 08 proxy integration — VisibilityController + synthetic tools."""
from __future__ import annotations

from collections import OrderedDict
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

    def process_side_effect(
        envelope: ContentEnvelope,
    ) -> tuple[ContentEnvelope, list[CompressionEvent]]:
        out = (
            envelope
            if output_content is None
            else ContentEnvelope(
                content=output_content, content_type=envelope.content_type
            )
        )
        return out, default_events

    pipeline.process = MagicMock(side_effect=process_side_effect)
    return pipeline


def _make_fake_sink() -> MagicMock:
    sink = MagicMock()
    sink.format_event = MagicMock(return_value="[token-sieve] formatted")
    sink.emit = MagicMock()
    return sink


def _make_usage_record(name: str, count: int) -> Any:
    """Create a mock ToolUsageRecord."""
    record = MagicMock()
    record.tool_name = name
    record.call_count = count
    record.server_id = "default"
    return record


def _make_fake_learning_store(
    usage_stats: list | None = None,
    session_count: int = 5,
    cooccurrence: list | None = None,
) -> AsyncMock:
    """Create a fake learning store with configurable responses."""
    store = AsyncMock()
    store.get_usage_stats = AsyncMock(return_value=usage_stats or [])
    store.get_session_count = AsyncMock(return_value=session_count)
    store.get_cooccurrence = AsyncMock(return_value=cooccurrence or [])
    store.record_call = AsyncMock()
    store.record_compression_events_batch = AsyncMock()
    store.get_pipeline_config = AsyncMock(return_value=None)
    store.get_savings_trend = AsyncMock(return_value=[{} for _ in range(session_count)])
    return store


def _make_proxy(
    tools: list[types.Tool] | None = None,
    visibility_controller: Any | None = None,
    learning_store: Any | None = None,
    call_result: types.CallToolResult | None = None,
    **kwargs: Any,
) -> Any:
    """Create a ProxyServer with optional Phase 08 components."""
    from token_sieve.server.proxy import ProxyServer

    connector = _make_fake_connector(tools=tools, call_result=call_result)
    return ProxyServer(
        backend_connector=connector,
        tool_filter=_make_fake_filter(),
        pipeline=_make_fake_pipeline(),
        metrics_sink=_make_fake_sink(),
        learning_store=learning_store,
        visibility_controller=visibility_controller,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Task 1: VisibilityController wiring in handle_list_tools
# ---------------------------------------------------------------------------


class TestHandleListToolsVisibility:
    """VisibilityController integration in handle_list_tools pipeline."""

    @pytest.mark.anyio
    async def test_handle_list_tools_hides_unused_tools(self) -> None:
        """Tools with 0 calls are hidden when VisibilityController is active."""
        from token_sieve.adapters.visibility.visibility_controller import (
            VisibilityController,
        )

        # 10 tools: 5 with calls, 5 without
        tools = [_make_tool(f"tool_{i}") for i in range(10)]
        usage_stats = [
            _make_usage_record(f"tool_{i}", 5) for i in range(5)
        ]

        vc = VisibilityController(
            min_visible_floor=5,
            cold_start_sessions=3,
        )
        store = _make_fake_learning_store(usage_stats=usage_stats, session_count=5)
        proxy = _make_proxy(
            tools=tools,
            visibility_controller=vc,
            learning_store=store,
        )

        result = await proxy.handle_list_tools()

        # Should have 5 visible tools + synthetic tools
        visible_names = {t.name for t in result}
        for i in range(5):
            assert f"tool_{i}" in visible_names
        for i in range(5, 10):
            assert f"tool_{i}" not in visible_names

    @pytest.mark.anyio
    async def test_handle_list_tools_no_visibility_controller(self) -> None:
        """Without VisibilityController, all tools returned (backward compat)."""
        tools = [_make_tool(f"tool_{i}") for i in range(10)]
        proxy = _make_proxy(tools=tools)

        result = await proxy.handle_list_tools()
        assert len(result) == 10

    @pytest.mark.anyio
    async def test_discover_tools_injected_when_hidden_above_threshold(self) -> None:
        """discover_tools synthetic tool appears when hidden_count > threshold."""
        from token_sieve.adapters.visibility.visibility_controller import (
            VisibilityController,
        )

        # 20 tools, only 5 have calls -> 15 hidden > default threshold of 5
        tools = [_make_tool(f"tool_{i}") for i in range(20)]
        usage_stats = [
            _make_usage_record(f"tool_{i}", 3) for i in range(5)
        ]

        vc = VisibilityController(min_visible_floor=5, cold_start_sessions=3)
        store = _make_fake_learning_store(usage_stats=usage_stats, session_count=5)
        proxy = _make_proxy(
            tools=tools,
            visibility_controller=vc,
            learning_store=store,
        )

        result = await proxy.handle_list_tools()
        names = {t.name for t in result}
        assert "discover_tools" in names

    @pytest.mark.anyio
    async def test_explain_compression_always_injected(self) -> None:
        """explain_compression always appears when visibility is enabled."""
        from token_sieve.adapters.visibility.visibility_controller import (
            VisibilityController,
        )

        tools = [_make_tool(f"tool_{i}") for i in range(3)]
        usage_stats = [
            _make_usage_record(f"tool_{i}", 5) for i in range(3)
        ]

        vc = VisibilityController(min_visible_floor=3, cold_start_sessions=3)
        store = _make_fake_learning_store(usage_stats=usage_stats, session_count=5)
        proxy = _make_proxy(
            tools=tools,
            visibility_controller=vc,
            learning_store=store,
        )

        result = await proxy.handle_list_tools()
        names = {t.name for t in result}
        assert "explain_compression" in names


# ---------------------------------------------------------------------------
# Task 2: Synthetic tool dispatch + discover_tools handler
# ---------------------------------------------------------------------------


class TestSyntheticToolDispatch:
    """Synthetic tool dispatch and discover_tools handler."""

    @pytest.mark.anyio
    async def test_discover_tools_call_returns_results(self) -> None:
        """discover_tools returns DietMCP summaries for matching hidden tools."""
        from token_sieve.adapters.visibility.visibility_controller import (
            VisibilityController,
        )

        # 3 tools containing "search" in name/description that will be hidden
        tools = [
            _make_tool("search_files", "Search files by pattern"),
            _make_tool("search_code", "Search code by regex"),
            _make_tool("search_docs", "Search documentation"),
            _make_tool("active_tool", "Already used tool"),
        ]
        usage_stats = [_make_usage_record("active_tool", 10)]

        vc = VisibilityController(min_visible_floor=1, cold_start_sessions=3)
        store = _make_fake_learning_store(usage_stats=usage_stats, session_count=5)
        proxy = _make_proxy(
            tools=tools,
            visibility_controller=vc,
            learning_store=store,
        )

        # First call handle_list_tools to populate hidden tools
        await proxy.handle_list_tools()

        # Now call discover_tools
        result = await proxy.handle_call_tool(
            "discover_tools", {"query": "search"}
        )
        assert not result.isError
        text = result.content[0].text
        assert "search_files" in text
        assert "search_code" in text
        assert "search_docs" in text

    @pytest.mark.anyio
    async def test_discover_tools_auto_unhides(self) -> None:
        """After discover_tools, matched tools appear in handle_list_tools."""
        from token_sieve.adapters.visibility.visibility_controller import (
            VisibilityController,
        )

        tools = [
            _make_tool("search_files", "Search files"),
            _make_tool("active_tool", "Active tool"),
        ]
        usage_stats = [_make_usage_record("active_tool", 10)]

        vc = VisibilityController(min_visible_floor=1, cold_start_sessions=3)
        store = _make_fake_learning_store(usage_stats=usage_stats, session_count=5)
        proxy = _make_proxy(
            tools=tools,
            visibility_controller=vc,
            learning_store=store,
        )

        # Populate hidden
        await proxy.handle_list_tools()

        # Call discover_tools to unhide
        await proxy.handle_call_tool("discover_tools", {"query": "search"})

        # Now the tool should be visible
        result = await proxy.handle_list_tools()
        names = {t.name for t in result}
        assert "search_files" in names

    @pytest.mark.anyio
    async def test_synthetic_tool_before_filter_gate(self) -> None:
        """Synthetic tools bypass ToolFilter — not blocked even if filter denies."""
        from token_sieve.adapters.visibility.visibility_controller import (
            VisibilityController,
        )

        tools = [_make_tool("tool_a")]
        vc = VisibilityController(min_visible_floor=1, cold_start_sessions=3)
        store = _make_fake_learning_store(session_count=5)

        # Filter that blocks everything
        filt = MagicMock()
        filt.is_allowed = MagicMock(return_value=False)
        filt.filter_tools = MagicMock(side_effect=lambda t: t)

        from token_sieve.server.proxy import ProxyServer

        proxy = ProxyServer(
            backend_connector=_make_fake_connector(tools=tools),
            tool_filter=filt,
            pipeline=_make_fake_pipeline(),
            metrics_sink=_make_fake_sink(),
            learning_store=store,
            visibility_controller=vc,
        )

        result = await proxy.handle_call_tool("discover_tools", {"query": "all"})
        assert not result.isError

    @pytest.mark.anyio
    async def test_synthetic_tools_not_recorded(self) -> None:
        """Synthetic tools do not get recorded to learning store."""
        from token_sieve.adapters.visibility.visibility_controller import (
            VisibilityController,
        )

        tools = [_make_tool("tool_a")]
        vc = VisibilityController(min_visible_floor=1, cold_start_sessions=3)
        store = _make_fake_learning_store(session_count=5)
        proxy = _make_proxy(
            tools=tools,
            visibility_controller=vc,
            learning_store=store,
        )

        await proxy.handle_call_tool("discover_tools", {"query": "test"})

        store.record_call.assert_not_called()
