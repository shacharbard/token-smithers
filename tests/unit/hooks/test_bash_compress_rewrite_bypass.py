"""RED tests for bash-compress-rewrite.sh inline NO_COMPRESS detection.

Task 3 of 09-04: verify the hook can distinguish inline NO_COMPRESS=1
(in the command string) from inherited (in the parent env), and emits the
correct rewrite template with TSIEV_INLINE_NO_COMPRESS=1 for inline cases.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

HOOK_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "src"
    / "token_sieve"
    / "hooks"
    / "bash-compress-rewrite.sh"
)


def run_hook(tool_input_command: str, env: dict | None = None) -> dict:
    """Run the hook with the given command and return the parsed JSON output."""
    import os

    hook_input = json.dumps({"tool_input": {"command": tool_input_command}})
    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    result = subprocess.run(
        ["bash", str(HOOK_PATH)],
        input=hook_input,
        capture_output=True,
        text=True,
        env=run_env,
    )
    if not result.stdout.strip():
        return {}
    return json.loads(result.stdout)


class TestBashCompressRewriteBypass:
    """Tests for inline NO_COMPRESS=1 detection in the bash hook."""

    def test_inline_no_compress_propagated(self) -> None:
        """Inline NO_COMPRESS=1 in command → rewrite includes TSIEV_INLINE_NO_COMPRESS=1."""
        output = run_hook("NO_COMPRESS=1 pytest tests/")

        # Should produce a rewrite
        rewritten = (
            output.get("hookSpecificOutput", {})
            .get("updatedInput", {})
            .get("command", "")
        )
        assert rewritten, "Hook should emit a rewritten command"
        # The rewrite must include the inline marker
        assert "TSIEV_INLINE_NO_COMPRESS=1" in rewritten, (
            f"Expected TSIEV_INLINE_NO_COMPRESS=1 in rewrite, got: {rewritten}"
        )
        # Must still wrap through compress CLI
        assert "python3 -m token_sieve compress" in rewritten, (
            f"Expected compress CLI entrypoint in rewrite, got: {rewritten}"
        )

    def test_inherited_no_compress_NOT_propagated_as_inline(self) -> None:
        """NO_COMPRESS=1 in parent env only (not in command string) → normal rewrite, no inline marker."""
        output = run_hook("pytest tests/", env={"NO_COMPRESS": "1"})

        rewritten = (
            output.get("hookSpecificOutput", {})
            .get("updatedInput", {})
            .get("command", "")
        )
        assert rewritten, "Hook should still emit a rewrite for normal command"
        # Must NOT have inline marker — only inherited env, which the CLI handles separately
        assert "TSIEV_INLINE_NO_COMPRESS" not in rewritten, (
            f"Inherited NO_COMPRESS should NOT inject inline marker; got: {rewritten}"
        )

    def test_no_compress_in_command_string_only_is_inline(self) -> None:
        """Literal NO_COMPRESS=1 prefix in command → detected as inline."""
        output = run_hook("NO_COMPRESS=1 cargo build")

        rewritten = (
            output.get("hookSpecificOutput", {})
            .get("updatedInput", {})
            .get("command", "")
        )
        assert "TSIEV_INLINE_NO_COMPRESS=1" in rewritten, (
            f"NO_COMPRESS=1 prefix in command string should be detected as inline; got: {rewritten}"
        )

    def test_normal_command_unaffected(self) -> None:
        """Normal command (no NO_COMPRESS) → standard rewrite, no inline marker."""
        output = run_hook("pytest tests/unit/")

        rewritten = (
            output.get("hookSpecificOutput", {})
            .get("updatedInput", {})
            .get("command", "")
        )
        assert rewritten, "Normal command should produce a rewrite"
        assert "TSIEV_INLINE_NO_COMPRESS" not in rewritten, (
            "Normal command should not have inline NO_COMPRESS marker"
        )
        assert "python3 -m token_sieve compress" in rewritten, (
            "Normal command should use compress CLI entrypoint"
        )
