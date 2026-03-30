"""Tests for CLI main module -- stdin/stdout piping and savings report."""

from __future__ import annotations

import io
import subprocess
import sys

import pytest


class TestCliPipesStdin:
    """CLI reads from stdin, writes compressed output to stdout."""

    def test_cli_pipes_stdin_through_pipeline(self, capsys, monkeypatch):
        """Feed text via stdin, get compressed output on stdout."""
        from token_sieve.cli.main import main

        monkeypatch.setattr("sys.stdin", io.StringIO("hello world"))
        exit_code = main([])
        captured = capsys.readouterr()
        assert "hello world" in captured.out
        assert exit_code == 0

    def test_cli_reports_savings_to_stderr(self, capsys, monkeypatch):
        """Savings report (original, compressed, ratio) goes to stderr."""
        from token_sieve.cli.main import main

        monkeypatch.setattr("sys.stdin", io.StringIO("hello world"))
        main([])
        captured = capsys.readouterr()
        assert "Original:" in captured.err
        assert "Compressed:" in captured.err
        assert "Savings:" in captured.err


class TestCliFileArgument:
    """CLI reads from file path argument instead of stdin."""

    def test_cli_reads_from_file_argument(self, capsys, tmp_path):
        """Pass a file path as argument, reads from file instead of stdin."""
        from token_sieve.cli.main import main

        test_file = tmp_path / "input.txt"
        test_file.write_text("file content here")
        exit_code = main([str(test_file)])
        captured = capsys.readouterr()
        assert "file content here" in captured.out
        assert exit_code == 0


class TestCliEdgeCases:
    """CLI error handling and edge cases."""

    def test_cli_with_no_input_shows_usage(self, capsys, monkeypatch):
        """No stdin and no file arg prints usage message to stderr."""
        from token_sieve.cli.main import main

        # Simulate non-interactive stdin with no data
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        exit_code = main([])
        captured = capsys.readouterr()
        assert exit_code != 0
        assert "usage" in captured.err.lower() or "error" in captured.err.lower()

    def test_cli_returns_zero_exit_code_on_success(self, capsys, monkeypatch):
        """Successful run returns exit code 0."""
        from token_sieve.cli.main import main

        monkeypatch.setattr("sys.stdin", io.StringIO("some text"))
        exit_code = main([])
        assert exit_code == 0

    def test_cli_file_not_found(self, capsys):
        """Non-existent file argument returns exit code 1 with error."""
        from token_sieve.cli.main import main

        exit_code = main(["/nonexistent/path/file.txt"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "error" in captured.err.lower()


class TestCliIntegration:
    """Integration tests: full pipeline round-trip."""

    def test_main_full_roundtrip(self, capsys, monkeypatch):
        """Invoke main() with real text, verify stdout and stderr."""
        from token_sieve.cli.main import main

        text = "The quick brown fox jumps over the lazy dog"
        monkeypatch.setattr("sys.stdin", io.StringIO(text))
        exit_code = main([])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert text in captured.out
        assert "Original:" in captured.err
        assert "Compressed:" in captured.err
        assert "Savings:" in captured.err

    def test_cli_via_subprocess(self):
        """Pipe text through python -m token_sieve via subprocess."""
        result = subprocess.run(
            [sys.executable, "-m", "token_sieve"],
            input="hello world",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "hello world" in result.stdout
        assert "Savings:" in result.stderr
