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


class TestBashCompressRewriteBypassAnchoring:
    """H5: NO_COMPRESS=1 inline detection must be anchored to start of raw command.

    Unanchored detection allowed bypass-by-filename poisoning of the
    auto-learn bypass counter and enabled easy evasion with `: NO_COMPRESS=1 ;`.
    """

    def test_filename_containing_marker_is_not_inline(self) -> None:
        """A test file path containing 'NO_COMPRESS=1' must not trigger inline marker."""
        output = run_hook("pytest tests/test_NO_COMPRESS=1_behavior.py")

        rewritten = (
            output.get("hookSpecificOutput", {})
            .get("updatedInput", {})
            .get("command", "")
        )
        assert rewritten, "Hook should still rewrite the command"
        assert "TSIEV_INLINE_NO_COMPRESS" not in rewritten, (
            f"Filename containing NO_COMPRESS=1 must not be treated as inline bypass; got: {rewritten}"
        )

    def test_grep_pattern_containing_marker_is_not_inline(self) -> None:
        """A grep pattern argument containing NO_COMPRESS=1 must not trigger inline marker."""
        output = run_hook('grep "NO_COMPRESS=1 " file.txt')

        rewritten = (
            output.get("hookSpecificOutput", {})
            .get("updatedInput", {})
            .get("command", "")
        )
        assert rewritten, "Hook should still rewrite the command"
        assert "TSIEV_INLINE_NO_COMPRESS" not in rewritten, (
            f"grep pattern containing NO_COMPRESS=1 must not be treated as inline bypass; got: {rewritten}"
        )

    def test_noop_prefix_bypass_evasion_is_not_inline(self) -> None:
        """`: NO_COMPRESS=1 ; real_cmd` must NOT be treated as a legitimate inline bypass.

        The `:` no-op prefix is an evasion trick: the marker would be recorded
        as a normal inline bypass but the real command still runs unwrapped.
        The anchored detection must reject this.
        """
        output = run_hook(": NO_COMPRESS=1 ; real_cmd")

        rewritten = (
            output.get("hookSpecificOutput", {})
            .get("updatedInput", {})
            .get("command", "")
        )
        assert rewritten, "Hook should still rewrite the command"
        assert "TSIEV_INLINE_NO_COMPRESS" not in rewritten, (
            f"`: NO_COMPRESS=1 ; ...` evasion must not be treated as inline bypass; got: {rewritten}"
        )

    def test_leading_whitespace_inline_is_still_inline(self) -> None:
        """Leading whitespace before NO_COMPRESS=1 is still a legitimate inline bypass."""
        output = run_hook("  NO_COMPRESS=1 pytest tests/foo.py")

        rewritten = (
            output.get("hookSpecificOutput", {})
            .get("updatedInput", {})
            .get("command", "")
        )
        assert "TSIEV_INLINE_NO_COMPRESS=1" in rewritten, (
            f"Leading whitespace should not defeat inline detection; got: {rewritten}"
        )

    def test_hook_survives_strict_pipefail(self) -> None:
        """M13: the hook must exit 0 under `bash -euo pipefail` with no pipe parsing.

        Previously the hook parsed a two-line RESULT via
        `echo "$RESULT" | head -1` and `tail -1`. Under strict pipefail,
        `head -1` can exit 141 (SIGPIPE) when it closes the pipe early,
        which `set -e` would propagate as a non-zero exit from the hook,
        blocking legitimate commands. The fix switches to pure-bash
        parameter expansion (no subprocess pipe parsing).

        This test runs the hook explicitly under `bash -euo pipefail`
        with a normal command and asserts exit 0 + valid JSON output.
        """
        import os

        hook_input = json.dumps({"tool_input": {"command": "pytest tests/unit/"}})
        result = subprocess.run(
            ["bash", "-euo", "pipefail", str(HOOK_PATH)],
            input=hook_input,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        assert result.returncode == 0, (
            f"Hook must exit 0 under strict pipefail; got rc={result.returncode}, "
            f"stderr={result.stderr!r}"
        )
        assert result.stdout.strip(), "Hook should emit JSON on stdout"
        parsed = json.loads(result.stdout)
        rewritten = (
            parsed.get("hookSpecificOutput", {})
            .get("updatedInput", {})
            .get("command", "")
        )
        assert "python3 -m token_sieve compress" in rewritten

    def test_canonical_inline_still_detected(self) -> None:
        """Regression: the canonical `NO_COMPRESS=1 <cmd>` form still works."""
        output = run_hook("NO_COMPRESS=1 pytest tests/foo.py")

        rewritten = (
            output.get("hookSpecificOutput", {})
            .get("updatedInput", {})
            .get("command", "")
        )
        assert "TSIEV_INLINE_NO_COMPRESS=1" in rewritten, (
            f"Canonical inline NO_COMPRESS=1 must be detected; got: {rewritten}"
        )
