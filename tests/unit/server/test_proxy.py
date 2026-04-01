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
                "size_gate_threshold": 2000,
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
