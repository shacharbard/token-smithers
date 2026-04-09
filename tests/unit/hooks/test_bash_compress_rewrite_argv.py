"""RED tests for C1 — hook emits TSIEV_WRAP_CMD_ARGV (argv-array protocol).

The hook must emit `TSIEV_WRAP_CMD_ARGV='<base64-json-argv>'` instead of
(or in addition to, for backward compat) the legacy shell-string
`TSIEV_WRAP_CMD='<shell-string>'`. Filenames with shell metacharacters must
round-trip through the JSON array untouched.

If shlex.split fails (unterminated quote), the hook MAY fall back to the
legacy path — that is acceptable safety behavior. Tests here focus on the
primary happy path + metachar fuzz.
"""
from __future__ import annotations

import base64
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


def _run_hook(cmd: str) -> dict:
    hook_input = json.dumps({"tool_input": {"command": cmd}})
    result = subprocess.run(
        ["bash", str(HOOK_PATH)],
        input=hook_input,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"hook exited {result.returncode}; stderr={result.stderr!r}"
    )
    if not result.stdout.strip():
        return {}
    return json.loads(result.stdout)


def _extract_argv_env_value(rewritten: str) -> str | None:
    """Parse rewritten command and return the TSIEV_WRAP_CMD_ARGV value."""
    import shlex

    tokens = shlex.split(rewritten)
    for tok in tokens:
        if tok.startswith("TSIEV_WRAP_CMD_ARGV="):
            return tok[len("TSIEV_WRAP_CMD_ARGV=") :]
    return None


def _decode_argv(value: str) -> list[str]:
    return json.loads(base64.b64decode(value).decode("utf-8"))


class TestHookEmitsArgvProtocol:
    def test_basic_command_emits_argv_env_var(self):
        data = _run_hook("pytest -xvs")
        assert data, "hook emitted no JSON for a normal command"
        rewritten = data["hookSpecificOutput"]["updatedInput"]["command"]
        assert "TSIEV_WRAP_CMD_ARGV=" in rewritten, (
            f"hook must emit TSIEV_WRAP_CMD_ARGV; got {rewritten!r}"
        )

        value = _extract_argv_env_value(rewritten)
        assert value is not None
        argv = _decode_argv(value)
        assert argv == ["pytest", "-xvs"], f"Unexpected argv: {argv!r}"

    @pytest.mark.parametrize(
        "cmd,expected_literal",
        [
            ("echo '$(whoami)'", "$(whoami)"),
            ("echo '`id`'", "`id`"),
            ("ls 'file; rm -rf /tmp/xxx'", "file; rm -rf /tmp/xxx"),
            ('echo "hello && touch /tmp/pwned"', "hello && touch /tmp/pwned"),
        ],
    )
    def test_shell_metachar_filenames_roundtrip_verbatim(self, cmd, expected_literal):
        """Payloads appear in the JSON argv array as literal strings."""
        data = _run_hook(cmd)
        assert data, f"hook emitted no JSON for {cmd!r}"
        rewritten = data["hookSpecificOutput"]["updatedInput"]["command"]

        value = _extract_argv_env_value(rewritten)
        assert value is not None, (
            f"hook must emit TSIEV_WRAP_CMD_ARGV for {cmd!r}; got {rewritten!r}"
        )
        argv = _decode_argv(value)
        # The literal metachar payload must appear as one of the argv tokens,
        # proving shell expansion was NOT applied inside the hook.
        assert any(expected_literal in token for token in argv), (
            f"Expected literal {expected_literal!r} in argv={argv!r}"
        )

    def test_argv_list_is_non_empty_json_array(self):
        data = _run_hook("ls -la /tmp")
        rewritten = data["hookSpecificOutput"]["updatedInput"]["command"]
        value = _extract_argv_env_value(rewritten)
        argv = _decode_argv(value)
        assert isinstance(argv, list)
        assert len(argv) >= 1
        assert argv[0] == "ls"
