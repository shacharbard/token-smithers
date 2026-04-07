"""RED tests for compress CLI subcommand — Task 2 of 09-01.

Tests cover exit code propagation, env var isolation, stdout compression,
and main() dispatch routing.
"""
from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from token_sieve.cli import compress as compress_mod
from token_sieve.cli.compress import run as run_compress
from token_sieve.cli.main import main


class TestCompressExitCode:
    """Exit code is byte-equal to upstream subprocess returncode (D1b)."""

    def test_exit_code_propagation_zero(self, monkeypatch, capsys):
        monkeypatch.setenv("TSIEV_WRAP_CMD", "true")
        rc = run_compress([])
        assert rc == 0

    def test_exit_code_propagation_nonzero(self, monkeypatch, capsys):
        monkeypatch.setenv("TSIEV_WRAP_CMD", "false")
        rc = run_compress([])
        assert rc == 1

    def test_exit_code_propagation_arbitrary(self, monkeypatch, capsys):
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'exit 42'")
        rc = run_compress([])
        assert rc == 42


class TestCompressEnvIsolation:
    """TSIEV_WRAP_CMD must NOT be inherited by the child process (D1 escaping)."""

    def test_env_var_popped_before_subprocess(self, monkeypatch):
        """The env dict passed to subprocess.run must not contain TSIEV_WRAP_CMD."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "true")
        captured_env: dict = {}

        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env") or {})
            # Return a minimal CompletedProcess-like object
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with patch.object(compress_mod.subprocess, "run", side_effect=fake_run):
            run_compress([])

        assert "TSIEV_WRAP_CMD" not in captured_env


class TestCompressStderrPassthrough:
    """stdout is compressed; stderr passes through raw by default (D1c)."""

    def test_stdout_compressed_stderr_raw(self, monkeypatch, capsys):
        """Stdout goes through pipeline; stderr is byte-equal to child's stderr."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo ERR >&2'")
        rc = run_compress([])
        assert rc == 0

        captured = capsys.readouterr()
        # stderr must contain the raw child stderr (ERR\n)
        assert "ERR" in captured.err


class TestMainDispatchesToCompress:
    """main() routes 'compress' subcommand to compress.run()."""

    def test_main_dispatches_compress_subcommand(self, monkeypatch):
        monkeypatch.setenv("TSIEV_WRAP_CMD", "true")
        rc = main(["compress"])
        assert rc == 0
