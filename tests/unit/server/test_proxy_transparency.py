"""Tests for compression transparency footer and source_tool metadata."""
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
# Helpers (same patterns as test_proxy.py)
# ---------------------------------------------------------------------------


def _make_call_result(text: str, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        isError=is_error,
    )


def _make_fake_connector(
    call_result: types.CallToolResult | None = None,
) -> AsyncMock:
    connector = AsyncMock()
    connector.list_tools = AsyncMock(return_value=[])
    connector.call_tool = AsyncMock(
        return_value=call_result or _make_call_result("raw backend response")
    )
    return connector


def _make_fake_filter() -> MagicMock:
    filt = MagicMock()
    filt.is_allowed = MagicMock(return_value=True)
    filt.filter_tools = MagicMock(return_value=[])
    return filt


def _make_fake_pipeline(
    events: list[CompressionEvent] | None = None,
    output_content: str | None = None,
) -> MagicMock:
    pipeline = MagicMock()

    def process_side_effect(envelope: ContentEnvelope) -> tuple[ContentEnvelope, list[CompressionEvent]]:
        out = ContentEnvelope(
            content=output_content or envelope.content,
            content_type=envelope.content_type,
            metadata=envelope.metadata,
        )
        return out, events or []

    pipeline.process = MagicMock(side_effect=process_side_effect)
    pipeline.register_strategy = MagicMock()
    pipeline.cleanup = MagicMock()
    return pipeline


def _make_fake_sink() -> MagicMock:
    sink = MagicMock()
    sink.format_event = MagicMock(return_value="metric line")
    sink.emit = MagicMock()
    return sink


# ---------------------------------------------------------------------------
# Test: source_tool metadata
# ---------------------------------------------------------------------------


class TestSourceToolMetadata:
    """ContentEnvelope passed to pipeline should have source_tool metadata."""

    @pytest.mark.anyio
    async def test_envelope_has_source_tool(self) -> None:
        """handle_call_tool sets metadata['source_tool'] to the tool name."""
        from token_sieve.server.proxy import ProxyServer

        connector = _make_fake_connector()
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(),
            pipeline=pipeline,
            metrics_sink=sink,
        )

        await proxy.handle_call_tool("search_symbols", {"query": "foo"})

        # Pipeline.process should have been called
        pipeline.process.assert_called_once()
        envelope = pipeline.process.call_args[0][0]
        assert isinstance(envelope, ContentEnvelope)
        assert envelope.metadata.get("source_tool") == "search_symbols"


# ---------------------------------------------------------------------------
# Test: transparency footer
# ---------------------------------------------------------------------------


class TestTransparencyFooter:
    """Compressed results should include an inline footer."""

    @pytest.mark.anyio
    async def test_footer_appended_when_compression_saves_tokens(self) -> None:
        """Footer shows original and compressed token counts."""
        from token_sieve.server.proxy import ProxyServer

        events = [
            CompressionEvent(
                original_tokens=500,
                compressed_tokens=200,
                strategy_name="NullFieldElider",
                content_type=ContentType.TEXT,
            ),
        ]
        connector = _make_fake_connector()
        pipeline = _make_fake_pipeline(events=events, output_content="compressed text")
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(),
            pipeline=pipeline,
            metrics_sink=sink,
        )

        result = await proxy.handle_call_tool("read_file", {"path": "foo.py"})

        text = result.content[0].text
        assert "[Compressed: 500\u2192200 tokens. Re-call for full detail.]" in text

    @pytest.mark.anyio
    async def test_no_footer_when_no_compression(self) -> None:
        """No footer when pipeline produces no savings."""
        from token_sieve.server.proxy import ProxyServer

        # No events = no compression happened (size gate skip)
        connector = _make_fake_connector()
        pipeline = _make_fake_pipeline(events=[], output_content="same text")
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(),
            pipeline=pipeline,
            metrics_sink=sink,
        )

        result = await proxy.handle_call_tool("read_file", {"path": "foo.py"})

        text = result.content[0].text
        assert "Compressed:" not in text

    @pytest.mark.anyio
    async def test_no_footer_when_zero_savings(self) -> None:
        """No footer when compressed == original (0% savings)."""
        from token_sieve.server.proxy import ProxyServer

        events = [
            CompressionEvent(
                original_tokens=100,
                compressed_tokens=100,
                strategy_name="NullFieldElider",
                content_type=ContentType.TEXT,
            ),
        ]
        connector = _make_fake_connector()
        pipeline = _make_fake_pipeline(events=events, output_content="same text")
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(),
            pipeline=pipeline,
            metrics_sink=sink,
        )

        result = await proxy.handle_call_tool("read_file", {"path": "foo.py"})

        text = result.content[0].text
        assert "Compressed:" not in text

    @pytest.mark.anyio
    async def test_footer_token_counts_span_multiple_events(self) -> None:
        """Footer uses first event's original and last event's compressed."""
        from token_sieve.server.proxy import ProxyServer

        events = [
            CompressionEvent(
                original_tokens=1000,
                compressed_tokens=600,
                strategy_name="NullFieldElider",
                content_type=ContentType.TEXT,
            ),
            CompressionEvent(
                original_tokens=600,
                compressed_tokens=300,
                strategy_name="SmartTruncation",
                content_type=ContentType.TEXT,
            ),
        ]
        connector = _make_fake_connector()
        pipeline = _make_fake_pipeline(events=events, output_content="very compressed")
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(),
            pipeline=pipeline,
            metrics_sink=sink,
        )

        result = await proxy.handle_call_tool("read_file", {"path": "foo.py"})

        text = result.content[0].text
        # First event's original (1000), last event's compressed (300)
        assert "[Compressed: 1000\u2192300 tokens. Re-call for full detail.]" in text

    @pytest.mark.anyio
    async def test_no_footer_on_error_result(self) -> None:
        """Backend errors pass through without footer."""
        from token_sieve.server.proxy import ProxyServer

        connector = _make_fake_connector(
            call_result=_make_call_result("error!", is_error=True)
        )
        pipeline = _make_fake_pipeline()
        sink = _make_fake_sink()

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=_make_fake_filter(),
            pipeline=pipeline,
            metrics_sink=sink,
        )

        result = await proxy.handle_call_tool("bad_tool", {})

        assert result.isError
        assert "Compressed:" not in result.content[0].text
