"""Integration tests for all hook scripts — contract validation."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

HOOKS_DIR = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "token_sieve"
    / "hooks"
)


class TestAllHooksExecutable:
    """All .sh files in hooks/ must have executable permission."""

    def test_all_hooks_are_executable(self):
        """All .sh files in the hooks directory are executable."""
        hook_scripts = list(HOOKS_DIR.glob("*.sh"))
        assert len(hook_scripts) > 0, "No hook scripts found"
        for script in hook_scripts:
            if script.name.startswith("_"):
                continue  # Skip _common.sh (sourced, not executed directly)
            assert os.access(script, os.X_OK), (
                f"{script.name} is not executable"
            )


class TestAllHooksHandleEdgeCases:
    """No hook should crash on empty or malformed input."""

    def _get_hook_scripts(self) -> list[str]:
        """Return all non-helper hook script names."""
        return [
            s.name
            for s in HOOKS_DIR.glob("*.sh")
            if not s.name.startswith("_")
        ]

    def test_all_hooks_handle_empty_stdin(self, run_hook):
        """No hook crashes on empty stdin — graceful exit 0."""
        for script in self._get_hook_scripts():
            result = run_hook(script, "")
            assert result.exit_code == 0, (
                f"{script} crashed on empty stdin (exit {result.exit_code}): {result.stderr}"
            )

    def test_all_hooks_handle_malformed_json(self, run_hook):
        """No hook crashes on malformed JSON — graceful exit 0."""
        for script in self._get_hook_scripts():
            result = run_hook(script, "not valid json {{{")
            assert result.exit_code == 0, (
                f"{script} crashed on malformed JSON (exit {result.exit_code}): {result.stderr}"
            )

    def test_all_hooks_handle_missing_fields(self, run_hook):
        """Missing expected JSON fields don't cause errors."""
        for script in self._get_hook_scripts():
            result = run_hook(script, {"unexpected_field": "value"})
            assert result.exit_code == 0, (
                f"{script} crashed on missing fields (exit {result.exit_code}): {result.stderr}"
            )


class TestNoNetworkCalls:
    """Hook scripts must not make network calls."""

    def test_no_hook_makes_network_calls(self):
        """Grep hook scripts for curl, wget, http — none found."""
        hook_scripts = list(HOOKS_DIR.glob("*.sh"))
        network_commands = ["curl ", "wget ", "http://", "https://", "nc ", "ncat "]
        for script in hook_scripts:
            content = script.read_text()
            for cmd in network_commands:
                assert cmd not in content, (
                    f"{script.name} contains network command: {cmd!r}"
                )
