"""Tests for bash-compress-rewrite.sh hook.

The hook rewrites a Bash command into the D1 rewrite template:
  TSIEV_WRAP_CMD="<ORIG>" python3 -m token_sieve compress --wrap-env

Tests use subprocess.run to invoke the .sh file with crafted JSON stdin,
matching the real Claude Code PreToolUse hook protocol format.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from tests.unit.hooks.conftest import HOOKS_DIR

HOOK = "bash-compress-rewrite.sh"


class TestBashCompressRewriteHook:
    """PreToolUse:Bash hook rewrites commands into the D1 rewrite template."""

    def test_rewrite_emits_updated_input(self, run_hook):
        """Normal command: hook emits hookSpecificOutput.updatedInput.command.

        C1 note: the hook now prefers the argv-array protocol
        (TSIEV_WRAP_CMD_ARGV=<base64-json>) over the legacy shell-string
        protocol (TSIEV_WRAP_CMD=<shell-quoted>). Either is acceptable.
        """
        import base64
        import json as _json

        result = run_hook(HOOK, {"tool_input": {"command": "pytest -xvs"}})

        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}: {result.stderr}"
        data = json.loads(result.stdout)
        hook_out = data["hookSpecificOutput"]
        assert hook_out["hookEventName"] == "PreToolUse"
        updated_cmd = hook_out["updatedInput"]["command"]
        assert (
            "TSIEV_WRAP_CMD_ARGV=" in updated_cmd
            or "TSIEV_WRAP_CMD=" in updated_cmd
        )
        assert "python3 -m token_sieve compress --wrap-env" in updated_cmd

        # Original command is embedded either as literal tokens in the base64
        # JSON argv, or as a shell-quoted string in the legacy fallback.
        if "TSIEV_WRAP_CMD_ARGV=" in updated_cmd:
            # Extract the base64 value (between single quotes).
            import re

            m = re.search(r"TSIEV_WRAP_CMD_ARGV='([^']+)'", updated_cmd)
            assert m, f"Could not extract argv payload from {updated_cmd!r}"
            argv = _json.loads(base64.b64decode(m.group(1)).decode("utf-8"))
            assert argv == ["pytest", "-xvs"]
        else:
            assert "pytest -xvs" in updated_cmd

    def test_rewrite_escapes_double_quotes_in_original(self, run_hook):
        """Command with double quotes: argv protocol preserves tokens verbatim.

        C1: with the argv-array protocol, there is no shell escaping to worry
        about — the tokens in the JSON array must exactly equal the result
        of shlex.split on the original command.
        """
        import base64
        import re
        import shlex as _shlex

        result = run_hook(HOOK, {"tool_input": {"command": 'echo "hi"'}})

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        updated_cmd = data["hookSpecificOutput"]["updatedInput"]["command"]
        assert "python3 -m token_sieve compress --wrap-env" in updated_cmd

        if "TSIEV_WRAP_CMD_ARGV=" in updated_cmd:
            m = re.search(r"TSIEV_WRAP_CMD_ARGV='([^']+)'", updated_cmd)
            assert m
            argv = json.loads(base64.b64decode(m.group(1)).decode("utf-8"))
            assert argv == _shlex.split('echo "hi"')
        else:
            # Legacy fallback path: verify round-trip via bash eval.
            assert "TSIEV_WRAP_CMD=" in updated_cmd
            extract_and_run = f"""
set -euo pipefail
eval "{updated_cmd.split(' python3 ')[0].strip()}"
bash -c "$TSIEV_WRAP_CMD"
"""
            run_result = subprocess.run(
                ["bash", "-c", extract_and_run],
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert "hi" in run_result.stdout

    def test_empty_command_allows_passthrough(self, run_hook):
        """Empty command string: exit 0 with no stdout JSON (allow)."""
        result = run_hook(HOOK, {"tool_input": {"command": ""}})

        assert result.exit_code == 0
        # No JSON output — just passthrough
        assert result.stdout.strip() == ""

    def test_missing_command_field_allows_passthrough(self, run_hook):
        """Missing command field in tool_input: exit 0, no stdout JSON."""
        result = run_hook(HOOK, {"tool_input": {}})

        assert result.exit_code == 0
        assert result.stdout.strip() == ""


class TestBashCompressRewriteEndToEnd:
    """End-to-end round-trip: rewrite template + 09-01 compress CLI pipeline."""

    @pytest.mark.parametrize(
        "original_cmd,expected_in_stdout",
        [
            ("echo HELLO_WORLD", "HELLO_WORLD"),
            ("echo 'single quoted arg'", "single quoted arg"),
            ('echo "double quoted"', "double quoted"),
            ("printf '%s\\n' hello", "hello"),
        ],
        ids=["simple", "single-quoted", "double-quoted", "dollar-sign"],
    )
    def test_end_to_end_rewrite_executes_correctly(
        self, run_hook, original_cmd: str, expected_in_stdout: str
    ) -> None:
        """Rewrite template round-trips correctly: original command output preserved.

        Invokes the hook to get the rewritten command, then executes it
        via bash -c using the current Python (which has token_sieve installed).
        This proves the rewrite template + 09-01's compress CLI form a working pipeline.
        """
        import os

        result = run_hook(HOOK, {"tool_input": {"command": original_cmd}})
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        updated_cmd = data["hookSpecificOutput"]["updatedInput"]["command"]
        # C1: either protocol is acceptable; the E2E pipe must still work.
        assert (
            "TSIEV_WRAP_CMD_ARGV=" in updated_cmd
            or "TSIEV_WRAP_CMD=" in updated_cmd
        )
        assert "python3 -m token_sieve compress --wrap-env" in updated_cmd

        # Use the same Python executable as the test process to ensure
        # token_sieve is importable in the round-trip subprocess.
        python_exe = sys.executable
        cmd_with_python = updated_cmd.replace(
            "python3 -m token_sieve compress",
            f"{python_exe} -m token_sieve compress",
        )

        run_result = subprocess.run(
            ["bash", "-c", cmd_with_python],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "PYTHONPATH": str(HOOKS_DIR.parents[3] / "src")},
        )
        assert expected_in_stdout in run_result.stdout, (
            f"Round-trip failed for {original_cmd!r}. "
            f"cmd={cmd_with_python!r}, "
            f"stdout={run_result.stdout!r}, stderr={run_result.stderr!r}"
        )
