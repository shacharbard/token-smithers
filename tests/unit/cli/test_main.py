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
