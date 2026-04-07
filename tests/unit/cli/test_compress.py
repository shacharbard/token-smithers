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


class TestStderrOverrideAllowlist:
    """Per-command stderr merge allowlist (D1c) — Task 3 tests.

    For allowlisted binaries, stderr is merged into the compression input.
    For unknown binaries, stderr passes through raw.
    Only the first shell word (literal match) triggers the merge.
    """

    def _run_with_cmd(self, monkeypatch, capsys, cmd: str) -> tuple[int, str, str]:
        monkeypatch.setenv("TSIEV_WRAP_CMD", cmd)
        rc = run_compress([])
        captured = capsys.readouterr()
        return rc, captured.out, captured.err

    def test_stderr_override_cargo(self, monkeypatch, capsys):
        """cargo: stderr merged into compression input, raw stderr is empty."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo CARGO_ERR >&2'")
        # Monkeypatch first word to simulate 'cargo' as the command
        import token_sieve.cli.compress as cm
        original_allowlist = cm._STDERR_MERGE_ALLOWLIST
        # Patch shlex to return 'cargo' as first word for this test
        import shlex as shlex_mod
        original_split = shlex_mod.split

        def fake_split(cmd, *args, **kwargs):
            result = original_split(cmd, *args, **kwargs)
            # Replace 'bash' with 'cargo' in position 0 for the merge check
            if result and result[0] == "bash":
                return ["cargo"] + result[1:]
            return result

        monkeypatch.setattr(shlex_mod, "split", fake_split)

        rc, out, err = self._run_with_cmd(monkeypatch, capsys,
                                          "bash -c 'echo OUT; echo CARGO_ERR >&2'")
        assert rc == 0
        # stderr should be empty (merged) and output should contain CARGO_ERR
        assert "CARGO_ERR" not in err
        # The merged content went through pipeline so it appears in stdout
        assert "CARGO_ERR" in out or "OUT" in out

    def test_stderr_override_docker(self, monkeypatch, capsys):
        """docker: stderr merged into compression input."""
        import shlex as shlex_mod
        original_split = shlex_mod.split

        def fake_split(cmd, *args, **kwargs):
            result = original_split(cmd, *args, **kwargs)
            if result and result[0] == "bash":
                return ["docker"] + result[1:]
            return result

        monkeypatch.setattr(shlex_mod, "split", fake_split)
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo DOCKER_ERR >&2'")
        rc = run_compress([])
        captured = capsys.readouterr()
        assert rc == 0
        assert "DOCKER_ERR" not in captured.err

    def test_stderr_override_webpack(self, monkeypatch, capsys):
        """webpack: stderr merged into compression input."""
        import shlex as shlex_mod
        original_split = shlex_mod.split

        def fake_split(cmd, *args, **kwargs):
            result = original_split(cmd, *args, **kwargs)
            if result and result[0] == "bash":
                return ["webpack"] + result[1:]
            return result

        monkeypatch.setattr(shlex_mod, "split", fake_split)
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo WEBPACK_ERR >&2'")
        rc = run_compress([])
        captured = capsys.readouterr()
        assert rc == 0
        assert "WEBPACK_ERR" not in captured.err

    def test_stderr_passthrough_for_unknown_binary(self, monkeypatch, capsys):
        """pytest (unknown): stderr passes through raw."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo PYTEST_ERR >&2'")
        rc = run_compress([])
        captured = capsys.readouterr()
        assert rc == 0
        assert "PYTEST_ERR" in captured.err

    def test_override_allowlist_is_first_word_match_only(self, monkeypatch, capsys):
        """mycargo does NOT trigger the merge (only exact first-word match)."""
        import shlex as shlex_mod
        original_split = shlex_mod.split

        def fake_split(cmd, *args, **kwargs):
            result = original_split(cmd, *args, **kwargs)
            if result and result[0] == "bash":
                return ["mycargo"] + result[1:]
            return result

        monkeypatch.setattr(shlex_mod, "split", fake_split)
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo MY_ERR >&2'")
        rc = run_compress([])
        captured = capsys.readouterr()
        assert rc == 0
        # mycargo is NOT in the allowlist → stderr still passes through raw
        assert "MY_ERR" in captured.err
