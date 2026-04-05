"""Tests for instruction injection and session recording in _run_proxy."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from token_sieve.domain.learning_types import ToolUsageRecord


def _make_tool(name: str) -> MagicMock:
    """Create a mock MCP Tool with a .name attribute."""
    tool = MagicMock()
    tool.name = name
    return tool


def _make_config_file(tmp_path: Path, *, visibility_enabled: bool = True) -> Path:
    """Write a minimal config YAML with tool_visibility settings."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "backend:\n  command: echo\n  args: [hello]\n"
        f"tool_visibility:\n  enabled: {str(visibility_enabled).lower()}\n"
        "  cold_start_sessions: 3\n  min_visible_floor: 5\n"
        "learning:\n  enabled: true\n"
    )
    return config_file


def _setup_mocks(
    mock_transport_cls: MagicMock,
    mock_connector_cls: MagicMock,
    *,
    tools: list[MagicMock] | None = None,
    existing_instructions: str | None = None,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Set up transport, connector, and proxy mocks for _run_proxy tests.

    Returns (mock_connector, mock_proxy, mock_learning_store).
    """
    # Transport context manager
    mock_session = AsyncMock()
    mock_transport = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_transport.connect.return_value = mock_ctx
    mock_transport_cls.return_value = mock_transport

    # Connector
    mock_connector = MagicMock()
    mock_connector.list_tools = AsyncMock(return_value=tools or [])
    mock_connector.get_instructions.return_value = existing_instructions
    mock_connector.set_instructions = MagicMock()
    mock_connector_cls.return_value = mock_connector

    # Learning store
    mock_learning_store = AsyncMock()
    mock_learning_store.get_usage_stats = AsyncMock(return_value=[])
    mock_learning_store.get_session_count = AsyncMock(return_value=10)
    mock_learning_store.record_session = AsyncMock()

    # Proxy
    mock_proxy = MagicMock()
    mock_proxy.run = AsyncMock()
    mock_proxy.rebind_connector = MagicMock()
    mock_proxy._session_id = "test-session-123"
    mock_proxy._learning_store = mock_learning_store
    mock_proxy._pipeline = MagicMock()
    mock_proxy._pipeline.process.return_value = (MagicMock(content="compressed"), [])

    return mock_connector, mock_proxy, mock_learning_store


class TestInstructionInjection:
    """Instruction injection wires into _run_proxy startup path."""

    def test_instruction_injection_with_hidden_tools(
        self, tmp_path: Path
    ) -> None:
        """When tools are hidden, connector gets hint with discover_tools."""
        config_file = _make_config_file(tmp_path)

        # 10 tools total, 5 have usage (will be visible), 5 don't (will be hidden)
        tools = [_make_tool(f"tool_{i}") for i in range(10)]
        usage_stats = [
            ToolUsageRecord(tool_name=f"tool_{i}", server_id="default", call_count=5, last_called_at="2026-01-01")
            for i in range(5)
        ]

        with (
            patch(
                "token_sieve.adapters.backend.stdio_transport.StdioClientTransport"
            ) as mock_transport_cls,
            patch(
                "token_sieve.adapters.backend.connector.BackendConnector"
            ) as mock_connector_cls,
            patch(
                "token_sieve.server.proxy.ProxyServer.create_from_config"
            ) as mock_create,
        ):
            mock_connector, mock_proxy, mock_ls = _setup_mocks(
                mock_transport_cls, mock_connector_cls, tools=tools
            )
            mock_ls.get_usage_stats.return_value = usage_stats
            mock_create.return_value = mock_proxy

            from token_sieve.cli.main import _run_proxy

            exit_code = asyncio.run(_run_proxy(str(config_file)))

            assert exit_code == 0
            # Verify set_instructions was called with hint
            mock_connector.set_instructions.assert_called()
            call_args = mock_connector.set_instructions.call_args[0][0]
            assert "discover_tools" in call_args
            assert "5" in call_args  # 5 hidden tools

    def test_no_injection_when_all_visible(self, tmp_path: Path) -> None:
        """When all tools are visible, no hint is injected."""
        config_file = _make_config_file(tmp_path)

        # 5 tools, all have usage
        tools = [_make_tool(f"tool_{i}") for i in range(5)]
        usage_stats = [
            ToolUsageRecord(tool_name=f"tool_{i}", server_id="default", call_count=5, last_called_at="2026-01-01")
            for i in range(5)
        ]

        with (
            patch(
                "token_sieve.adapters.backend.stdio_transport.StdioClientTransport"
            ) as mock_transport_cls,
            patch(
                "token_sieve.adapters.backend.connector.BackendConnector"
            ) as mock_connector_cls,
            patch(
                "token_sieve.server.proxy.ProxyServer.create_from_config"
            ) as mock_create,
        ):
            mock_connector, mock_proxy, mock_ls = _setup_mocks(
                mock_transport_cls, mock_connector_cls, tools=tools
            )
            mock_ls.get_usage_stats.return_value = usage_stats
            mock_ls.get_session_count.return_value = 10
            mock_create.return_value = mock_proxy

            from token_sieve.cli.main import _run_proxy

            exit_code = asyncio.run(_run_proxy(str(config_file)))

            assert exit_code == 0
            # set_instructions should NOT have been called with discover_tools hint
            # (it may have been called for instruction compression, but not for visibility)
            for call in mock_connector.set_instructions.call_args_list:
                hint_text = call[0][0]
                assert "discover_tools" not in hint_text

    def test_injection_appends_to_existing_instructions(
        self, tmp_path: Path
    ) -> None:
        """Hint is appended to existing backend instructions."""
        config_file = _make_config_file(tmp_path)

        tools = [_make_tool(f"tool_{i}") for i in range(10)]
        usage_stats = [
            ToolUsageRecord(tool_name=f"tool_{i}", server_id="default", call_count=5, last_called_at="2026-01-01")
            for i in range(5)
        ]

        with (
            patch(
                "token_sieve.adapters.backend.stdio_transport.StdioClientTransport"
            ) as mock_transport_cls,
            patch(
                "token_sieve.adapters.backend.connector.BackendConnector"
            ) as mock_connector_cls,
            patch(
                "token_sieve.server.proxy.ProxyServer.create_from_config"
            ) as mock_create,
        ):
            mock_connector, mock_proxy, mock_ls = _setup_mocks(
                mock_transport_cls,
                mock_connector_cls,
                tools=tools,
                existing_instructions="Backend server v1.0",
            )
            mock_ls.get_usage_stats.return_value = usage_stats
            mock_create.return_value = mock_proxy

            from token_sieve.cli.main import _run_proxy

            exit_code = asyncio.run(_run_proxy(str(config_file)))

            assert exit_code == 0
            # Find the call that contains discover_tools
            hint_calls = [
                c for c in mock_connector.set_instructions.call_args_list
                if "discover_tools" in c[0][0]
            ]
            assert len(hint_calls) == 1
            combined = hint_calls[0][0][0]
            assert combined.startswith("Backend server v1.0")

    def test_injection_gracefully_handles_list_tools_error(
        self, tmp_path: Path
    ) -> None:
        """If connector.list_tools() raises, proxy still starts."""
        config_file = _make_config_file(tmp_path)

        with (
            patch(
                "token_sieve.adapters.backend.stdio_transport.StdioClientTransport"
            ) as mock_transport_cls,
            patch(
                "token_sieve.adapters.backend.connector.BackendConnector"
            ) as mock_connector_cls,
            patch(
                "token_sieve.server.proxy.ProxyServer.create_from_config"
            ) as mock_create,
        ):
            mock_connector, mock_proxy, mock_ls = _setup_mocks(
                mock_transport_cls, mock_connector_cls
            )
            mock_connector.list_tools = AsyncMock(
                side_effect=RuntimeError("Backend down")
            )
            mock_create.return_value = mock_proxy

            from token_sieve.cli.main import _run_proxy

            exit_code = asyncio.run(_run_proxy(str(config_file)))

            # Proxy should still start successfully
            assert exit_code == 0
            mock_proxy.run.assert_awaited_once()


class TestSessionRecording:
    """Session recording at _run_proxy startup."""

    def test_session_recorded_at_startup(self, tmp_path: Path) -> None:
        """record_session is called with session_id during startup."""
        config_file = _make_config_file(tmp_path)

        with (
            patch(
                "token_sieve.adapters.backend.stdio_transport.StdioClientTransport"
            ) as mock_transport_cls,
            patch(
                "token_sieve.adapters.backend.connector.BackendConnector"
            ) as mock_connector_cls,
            patch(
                "token_sieve.server.proxy.ProxyServer.create_from_config"
            ) as mock_create,
        ):
            mock_connector, mock_proxy, mock_ls = _setup_mocks(
                mock_transport_cls, mock_connector_cls
            )
            mock_create.return_value = mock_proxy

            from token_sieve.cli.main import _run_proxy

            exit_code = asyncio.run(_run_proxy(str(config_file)))

            assert exit_code == 0
            mock_ls.record_session.assert_awaited_once_with("test-session-123")

    def test_session_recording_failure_does_not_block(
        self, tmp_path: Path
    ) -> None:
        """If record_session raises, proxy still starts."""
        config_file = _make_config_file(tmp_path)

        with (
            patch(
                "token_sieve.adapters.backend.stdio_transport.StdioClientTransport"
            ) as mock_transport_cls,
            patch(
                "token_sieve.adapters.backend.connector.BackendConnector"
            ) as mock_connector_cls,
            patch(
                "token_sieve.server.proxy.ProxyServer.create_from_config"
            ) as mock_create,
        ):
            mock_connector, mock_proxy, mock_ls = _setup_mocks(
                mock_transport_cls, mock_connector_cls
            )
            mock_ls.record_session = AsyncMock(
                side_effect=RuntimeError("DB write failed")
            )
            mock_create.return_value = mock_proxy

            from token_sieve.cli.main import _run_proxy

            exit_code = asyncio.run(_run_proxy(str(config_file)))

            assert exit_code == 0
            mock_proxy.run.assert_awaited_once()
