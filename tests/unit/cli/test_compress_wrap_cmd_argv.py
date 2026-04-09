"""RED tests for C1 — argv-array protocol for TSIEV_WRAP_CMD (batch 5).

Replaces the shell-string-via-bash-c protocol with a JSON+base64 argv array
(TSIEV_WRAP_CMD_ARGV) that is invoked with shell=False. The legacy
TSIEV_WRAP_CMD path must still work but emit a DeprecationWarning so
existing installs continue functioning while users re-run `ts setup`.

These tests exercise the CLI side. Hook-side emission is covered by
tests/unit/hooks/test_bash_compress_rewrite_argv.py.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import warnings

import pytest

from token_sieve.cli import compress as compress_mod
from token_sieve.cli.compress import run as run_compress


@pytest.fixture(autouse=True)
def _no_bypass_store(monkeypatch):
    monkeypatch.setattr(compress_mod, "_get_bypass_store", lambda: None)


def _encode_argv(argv: list[str]) -> str:
    return base64.b64encode(json.dumps(argv).encode("utf-8")).decode("ascii")


class TestWrapCmdArgvHappyPath:
    """TSIEV_WRAP_CMD_ARGV is preferred over TSIEV_WRAP_CMD and uses shell=False."""

    def test_argv_path_invokes_subprocess_with_shell_false(self, monkeypatch):
        """argv path must call subprocess.run(argv, shell=False) — never bash -c."""
        monkeypatch.delenv("TSIEV_WRAP_CMD", raising=False)
        monkeypatch.setenv(
            "TSIEV_WRAP_CMD_ARGV", _encode_argv([sys.executable, "-c", "print('OK')"])
        )

        captured = {}
        real_run = subprocess.run

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["shell"] = kwargs.get("shell", False)
            return real_run(cmd, **kwargs)

        monkeypatch.setattr(compress_mod.subprocess, "run", fake_run)

        rc = run_compress([])

        assert rc == 0
        assert captured["shell"] is False
        assert isinstance(captured["cmd"], list), (
            f"Expected argv list, got {type(captured['cmd']).__name__}"
        )
        assert captured["cmd"][0] != "bash", (
            f"argv path must not invoke bash; got {captured['cmd']!r}"
        )
        assert captured["cmd"] == [sys.executable, "-c", "print('OK')"]

    def test_argv_preferred_over_legacy_env_var(self, monkeypatch):
        """When both TSIEV_WRAP_CMD_ARGV and TSIEV_WRAP_CMD are set, argv wins."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "echo LEGACY")
        monkeypatch.setenv(
            "TSIEV_WRAP_CMD_ARGV", _encode_argv(["echo", "ARGV_WINS"])
        )

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            result = subprocess.CompletedProcess(cmd, 0, "ARGV_WINS\n", "")
            return result

        monkeypatch.setattr(compress_mod.subprocess, "run", fake_run)

        run_compress([])

        assert captured["cmd"] == ["echo", "ARGV_WINS"], (
            f"argv env var must take precedence; got {captured['cmd']!r}"
        )


class TestWrapCmdArgvInjectionResistance:
    """Filenames with shell metacharacters must pass through as literal argv."""

    @pytest.mark.parametrize(
        "payload",
        [
            "$(whoami)",
            "`id`",
            "; rm -rf /tmp/xxx",
            "'\"; exit 0; \"'",
            "hello && touch /tmp/pwned_tsiev",
            "$(cat /etc/passwd)",
        ],
    )
    def test_shell_metacharacter_payload_not_executed(
        self, monkeypatch, payload, capsys
    ):
        """Payloads must arrive at argv[1] verbatim — never interpreted by a shell."""
        monkeypatch.delenv("TSIEV_WRAP_CMD", raising=False)
        # Wrap: python -c 'import sys; print(sys.argv[1])' <payload>
        # If payload is executed by a shell, we'd see shell-evaluated output
        # (e.g., the current username instead of the literal $(whoami)).
        monkeypatch.setenv(
            "TSIEV_WRAP_CMD_ARGV",
            _encode_argv(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.write(sys.argv[1])",
                    payload,
                ]
            ),
        )

        rc = run_compress([])
        captured = capsys.readouterr()

        assert rc == 0, f"wrap failed: stderr={captured.err!r}"
        # Pipeline may compress/annotate, but the literal payload must appear.
        assert payload in captured.out, (
            f"payload {payload!r} was NOT passed verbatim. stdout={captured.out!r}"
        )


class TestLegacyWrapCmdFallback:
    """Legacy TSIEV_WRAP_CMD path still works but emits DeprecationWarning."""

    def test_legacy_env_var_still_works_with_deprecation_warning(
        self, monkeypatch, capsys, recwarn
    ):
        """Missing TSIEV_WRAP_CMD_ARGV → fall back to bash -c + warn."""
        monkeypatch.delenv("TSIEV_WRAP_CMD_ARGV", raising=False)
        monkeypatch.setenv("TSIEV_WRAP_CMD", "echo LEGACY_PATH")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            rc = run_compress([])

        out = capsys.readouterr()
        assert rc == 0
        assert "LEGACY_PATH" in out.out

        # Either a real DeprecationWarning or a stderr note is acceptable
        # (the implementation may choose either; assert on at least one).
        has_warning = any(
            issubclass(w.category, DeprecationWarning)
            and "TSIEV_WRAP_CMD" in str(w.message)
            for w in caught
        )
        has_stderr_note = (
            "TSIEV_WRAP_CMD" in out.err
            and ("deprecat" in out.err.lower() or "legacy" in out.err.lower())
        )
        assert has_warning or has_stderr_note, (
            f"Legacy path must signal deprecation via warning or stderr. "
            f"warnings={[str(w.message) for w in caught]!r} stderr={out.err!r}"
        )

    def test_missing_both_env_vars_is_error(self, monkeypatch):
        """No TSIEV_WRAP_CMD_ARGV and no TSIEV_WRAP_CMD → exit 1."""
        monkeypatch.delenv("TSIEV_WRAP_CMD_ARGV", raising=False)
        monkeypatch.delenv("TSIEV_WRAP_CMD", raising=False)

        rc = run_compress([])
        assert rc == 1


class TestWrapCmdArgvMalformed:
    """Malformed argv env vars should fail safely, not crash with a traceback."""

    def test_malformed_base64_returns_error(self, monkeypatch):
        monkeypatch.delenv("TSIEV_WRAP_CMD", raising=False)
        monkeypatch.setenv("TSIEV_WRAP_CMD_ARGV", "!!!not-base64!!!")

        rc = run_compress([])
        assert rc != 0

    def test_empty_argv_array_returns_error(self, monkeypatch):
        monkeypatch.delenv("TSIEV_WRAP_CMD", raising=False)
        monkeypatch.setenv("TSIEV_WRAP_CMD_ARGV", _encode_argv([]))

        rc = run_compress([])
        assert rc != 0
