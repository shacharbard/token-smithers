"""Tests for CLI main module -- pipe mode, proxy mode, and help."""

from __future__ import annotations

import io
import subprocess
import sys
from unittest.mock import AsyncMock, patch

import pytest


class TestCliPipeMode:
    """CLI --pipe mode reads from stdin, writes compressed output to stdout."""

    def test_pipe_mode_stdin_through_pipeline(self, capsys, monkeypatch):
        """Feed text via stdin with --pipe, get compressed output on stdout."""
        from token_sieve.cli.main import main

        monkeypatch.setattr("sys.stdin", io.StringIO("hello world"))
        exit_code = main(["--pipe"])
        captured = capsys.readouterr()
        assert "hello world" in captured.out
        assert exit_code == 0

    def test_pipe_mode_reports_savings_to_stderr(self, capsys, monkeypatch):
        """Savings report (original, compressed, ratio) goes to stderr."""
        from token_sieve.cli.main import main

        monkeypatch.setattr("sys.stdin", io.StringIO("hello world"))
        main(["--pipe"])
        captured = capsys.readouterr()
        assert "Original:" in captured.err
        assert "Compressed:" in captured.err
        assert "Savings:" in captured.err

    def test_pipe_mode_reads_from_file_argument(self, capsys, tmp_path):
        """--pipe with file path reads from file instead of stdin."""
        from token_sieve.cli.main import main

        test_file = tmp_path / "input.txt"
        test_file.write_text("file content here")
        exit_code = main(["--pipe", str(test_file)])
        captured = capsys.readouterr()
        assert "file content here" in captured.out
        assert exit_code == 0

    def test_pipe_mode_no_input_shows_error(self, capsys, monkeypatch):
        """--pipe with no stdin and no file prints error to stderr."""
        from token_sieve.cli.main import main

        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        exit_code = main(["--pipe"])
        captured = capsys.readouterr()
        assert exit_code != 0
        assert "usage" in captured.err.lower() or "error" in captured.err.lower()

    def test_pipe_mode_file_not_found(self, capsys):
        """--pipe with non-existent file returns exit code 1."""
        from token_sieve.cli.main import main

        exit_code = main(["--pipe", "/nonexistent/path/file.txt"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "error" in captured.err.lower()

    def test_pipe_mode_full_roundtrip(self, capsys, monkeypatch):
        """--pipe with real text: verify stdout and stderr."""
        from token_sieve.cli.main import main

        text = "The quick brown fox jumps over the lazy dog"
        monkeypatch.setattr("sys.stdin", io.StringIO(text))
        exit_code = main(["--pipe"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert text in captured.out
        assert "Original:" in captured.err

    def test_pipe_mode_via_subprocess(self):
        """Pipe text through python -m token_sieve --pipe via subprocess."""
        result = subprocess.run(
            [sys.executable, "-m", "token_sieve", "--pipe"],
            input="hello world",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "hello world" in result.stdout
        assert "Savings:" in result.stderr


class TestCliProxyMode:
    """CLI proxy mode starts MCP server."""

    def test_proxy_mode_calls_server_run(self, monkeypatch):
        """Default mode (no --pipe) creates ProxyServer and calls run()."""
        from token_sieve.cli.main import main

        mock_run = AsyncMock(return_value=0)
        with patch(
            "token_sieve.cli.main._run_proxy", mock_run
        ):
            exit_code = main([])
            mock_run.assert_called_once()
            assert exit_code == 0

    def test_proxy_mode_with_config_flag(self, tmp_path, monkeypatch):
        """--config flag loads config file for proxy mode."""
        from token_sieve.cli.main import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "backend:\n  transport: stdio\n  command: echo\n"
        )

        mock_run = AsyncMock(return_value=0)
        with patch(
            "token_sieve.cli.main._run_proxy", mock_run
        ):
            exit_code = main(["--config", str(config_file)])
            mock_run.assert_called_once()
            assert exit_code == 0

    def test_proxy_mode_invalid_config_returns_error(self, capsys, tmp_path):
        """--config with invalid YAML returns error."""
        from token_sieve.cli.main import main

        config_file = tmp_path / "bad.yaml"
        config_file.write_text(": invalid: yaml: [")

        exit_code = main(["--config", str(config_file)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "error" in captured.err.lower()

    def test_proxy_mode_config_not_found_returns_error(self, capsys):
        """--config with non-existent file returns error."""
        from token_sieve.cli.main import main

        exit_code = main(["--config", "/nonexistent/config.yaml"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "error" in captured.err.lower()


class TestCliHelp:
    """--help shows both proxy and pipe modes."""

    def test_help_shows_proxy_and_pipe(self, capsys):
        """--help output mentions both proxy and pipe modes."""
        from token_sieve.cli.main import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "pipe" in captured.out.lower()
        assert "proxy" in captured.out.lower() or "mcp" in captured.out.lower()


class TestCliErrorHandling:
    """Finding 5: main() must log tracebacks and handle CancelledError."""

    def test_exception_logs_traceback(self, caplog):
        """Exceptions in proxy mode must be logged with full traceback."""
        import logging

        from token_sieve.cli.main import main

        mock_run = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            patch("token_sieve.cli.main._run_proxy", mock_run),
            caplog.at_level(logging.ERROR, logger="token_sieve.cli.main"),
        ):
            exit_code = main([])

        assert exit_code == 1
        # logger.exception() should produce a log record with exc_info
        assert any("boom" in r.message for r in caplog.records), (
            f"Expected logger.exception with 'boom', got: {[r.message for r in caplog.records]}"
        )
        # Verify traceback is attached (exc_info is set)
        assert any(r.exc_info for r in caplog.records), (
            "Expected exc_info in log records for full traceback"
        )

    def test_cancelled_error_returns_zero(self):
        """asyncio.CancelledError should be treated as normal shutdown (exit 0)."""
        import asyncio

        from token_sieve.cli.main import main

        mock_run = AsyncMock(side_effect=asyncio.CancelledError())
        with patch("token_sieve.cli.main._run_proxy", mock_run):
            exit_code = main([])
        assert exit_code == 0

    def test_keyboard_interrupt_returns_130(self):
        """KeyboardInterrupt should return 130 (standard SIGINT exit code)."""
        from token_sieve.cli.main import main

        mock_run = AsyncMock(side_effect=KeyboardInterrupt())
        with patch("token_sieve.cli.main._run_proxy", mock_run):
            exit_code = main([])
        assert exit_code == 130


class TestM10GenericInstructionHint:
    """M10: Instruction hint should be generic, not include exact hidden count."""

    @pytest.mark.asyncio
    async def test_instruction_hint_is_generic(self) -> None:
        """Visibility hint should not expose exact count of hidden tools."""
        from token_sieve.cli.main import _inject_visibility_instructions

        # Create a proxy mock with VC that hides tools
        proxy = AsyncMock()
        proxy._session_id = "test-session"
        learning_store = AsyncMock()
        learning_store.record_session = AsyncMock()
        learning_store.get_usage_stats = AsyncMock(return_value=[])
        learning_store.get_session_count = AsyncMock(return_value=10)
        proxy._learning_store = learning_store

        from token_sieve.adapters.visibility.visibility_controller import (
            VisibilityController,
        )

        vc = VisibilityController(
            frequency_threshold=3, min_visible_floor=0, cold_start_sessions=0
        )
        proxy._visibility_controller = vc

        import mcp.types as types

        tools = [
            types.Tool(name=f"tool_{i}", description=f"Tool {i}", inputSchema={"type": "object"})
            for i in range(5)
        ]
        connector = AsyncMock()
        connector.list_tools = AsyncMock(return_value=tools)
        connector.get_instructions = AsyncMock(return_value="")
        connector.set_instructions = AsyncMock()

        config = AsyncMock()
        config.tool_visibility.frequency_threshold = 3
        config.tool_visibility.min_visible_floor = 0
        config.tool_visibility.cold_start_sessions = 0

        await _inject_visibility_instructions(proxy, connector, config)

        if connector.set_instructions.called:
            hint = connector.set_instructions.call_args[0][0]
            # M10: hint should NOT contain exact count like "5 tool(s)"
            import re
            assert not re.search(r"\d+ tool\(s\)", hint), (
                f"M10: instruction hint should be generic, not include exact count. "
                f"Got: {hint}"
            )


class TestM11DefaultServerIdConstant:
    """M11: 'default' server_id should use a shared constant."""

    def test_default_server_id_constant_exists(self) -> None:
        """A DEFAULT_SERVER_ID constant should exist in the domain layer."""
        try:
            from token_sieve.domain.constants import DEFAULT_SERVER_ID
            assert DEFAULT_SERVER_ID == "default"
        except ImportError:
            pytest.fail(
                "M11: token_sieve.domain.constants.DEFAULT_SERVER_ID not found. "
                "Extract hardcoded 'default' to a shared constant."
            )


class TestM7EndedAtColumn:
    """M7: Sessions table should have ended_at + end_session method."""

    @pytest.mark.asyncio
    async def test_sessions_table_has_ended_at_column(self) -> None:
        """sessions table must have an ended_at column."""
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        store = await SQLiteLearningStore.connect(":memory:")
        async with store._db.execute("PRAGMA table_info(sessions)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        assert "ended_at" in columns, (
            f"M7: sessions table missing ended_at column. Columns: {columns}"
        )

    @pytest.mark.asyncio
    async def test_end_session_method_exists(self) -> None:
        """SQLiteLearningStore must have an end_session method."""
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        store = await SQLiteLearningStore.connect(":memory:")
        assert hasattr(store, "end_session"), (
            "M7: SQLiteLearningStore missing end_session method"
        )

    @pytest.mark.asyncio
    async def test_end_session_updates_ended_at(self) -> None:
        """end_session should set ended_at on the session row."""
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        store = await SQLiteLearningStore.connect(":memory:")
        await store.record_session("test-session")
        await store.end_session("test-session")
        async with store._db.execute(
            "SELECT ended_at FROM sessions WHERE session_id = ?",
            ("test-session",),
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] is not None, "M7: ended_at should be set after end_session"

    @pytest.mark.asyncio
    async def test_end_session_protocol(self) -> None:
        """LearningStore Protocol should declare end_session."""
        from token_sieve.domain.ports_learning import LearningStore

        assert hasattr(LearningStore, "end_session"), (
            "M7: LearningStore Protocol missing end_session method"
        )


class TestH2ReuseProxyVC:
    """H2: _inject_visibility_instructions must reuse proxy._visibility_controller."""

    @pytest.mark.asyncio
    async def test_uses_proxy_vc_not_new_instance(self) -> None:
        """Should use proxy._visibility_controller instead of creating new VC."""
        import inspect
        from token_sieve.cli.main import _inject_visibility_instructions

        source = inspect.getsource(_inject_visibility_instructions)
        # H2: function should NOT instantiate VisibilityController
        assert "VisibilityController(" not in source, (
            "H2: _inject_visibility_instructions creates a new VisibilityController "
            "instead of reusing proxy._visibility_controller"
        )


class TestProxyBackendWiring:
    """Finding 1: _run_proxy must wire a real backend, not leave the stub."""

    def test_run_proxy_fails_fast_without_backend_command(self, capsys):
        """Proxy mode must fail fast if backend.command is not configured."""
        from token_sieve.cli.main import main

        exit_code = main([])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "backend" in captured.err.lower()

    def test_run_proxy_wires_real_backend(self, tmp_path):
        """_run_proxy must replace _StubConnector with a real BackendConnector."""
        import asyncio
        import contextlib

        from token_sieve.adapters.backend.connector import BackendConnector
        from token_sieve.cli.main import _run_proxy

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "backend:\n"
            "  transport: stdio\n"
            "  command: echo\n"
            "  args: [\"hello\"]\n"
        )

        captured_connector = {}

        async def fake_run(self_proxy):
            """Capture the connector type instead of actually running."""
            captured_connector["type"] = type(self_proxy._connector).__name__

        # Mock the transport.connect() to avoid real subprocess
        mock_session = AsyncMock()

        @contextlib.asynccontextmanager
        async def fake_connect():
            yield mock_session

        mock_transport = AsyncMock()
        mock_transport.connect = fake_connect

        with (
            patch(
                "token_sieve.adapters.backend.stdio_transport.StdioClientTransport",
                return_value=mock_transport,
            ),
            patch(
                "token_sieve.server.proxy.ProxyServer.run",
                fake_run,
            ),
        ):
            exit_code = asyncio.run(_run_proxy(str(config_file)))

        assert exit_code == 0
        assert captured_connector.get("type") == "BackendConnector", (
            f"Expected BackendConnector, got {captured_connector.get('type')}"
        )
