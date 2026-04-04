"""Shared fixtures for hook script tests."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

HOOKS_DIR = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "token_sieve"
    / "hooks"
)


@dataclass(frozen=True)
class HookResult:
    exit_code: int
    stdout: str
    stderr: str


@pytest.fixture
def run_hook():
    """Run a hook script with JSON tool input on stdin.

    Returns a callable: (script_name, tool_input_dict, env_overrides) -> HookResult
    """

    def _run(
        script_name: str,
        tool_input: dict | str | None = None,
        env: dict[str, str] | None = None,
    ) -> HookResult:
        import os

        script_path = HOOKS_DIR / script_name
        stdin_data = ""
        if tool_input is not None:
            stdin_data = (
                tool_input
                if isinstance(tool_input, str)
                else json.dumps(tool_input)
            )

        run_env = os.environ.copy()
        # Clear MCP availability indicators by default
        run_env.pop("TOKEN_SIEVE_JCODEMUNCH", None)
        run_env.pop("TOKEN_SIEVE_CONTEXT_MODE", None)
        if env:
            run_env.update(env)

        result = subprocess.run(
            ["bash", str(script_path)],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=10,
            env=run_env,
        )
        return HookResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    return _run


@pytest.fixture
def assert_completes_under_ms():
    """Assert a hook completes under a given number of milliseconds."""

    def _assert(
        script_name: str,
        tool_input: dict | str | None = None,
        max_ms: int = 50,
        env: dict[str, str] | None = None,
    ) -> None:
        import os

        script_path = HOOKS_DIR / script_name
        stdin_data = ""
        if tool_input is not None:
            stdin_data = (
                tool_input
                if isinstance(tool_input, str)
                else json.dumps(tool_input)
            )

        run_env = os.environ.copy()
        run_env.pop("TOKEN_SIEVE_JCODEMUNCH", None)
        run_env.pop("TOKEN_SIEVE_CONTEXT_MODE", None)
        if env:
            run_env.update(env)

        start = time.perf_counter()
        subprocess.run(
            ["bash", str(script_path)],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=10,
            env=run_env,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < max_ms, (
            f"{script_name} took {elapsed_ms:.1f}ms, expected < {max_ms}ms"
        )

    return _assert
