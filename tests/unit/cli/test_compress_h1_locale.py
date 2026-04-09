"""RED tests for H1 — LC_ALL global mutation + UTF-8 decode regression.

The existing compress.run() mutates the C-library global via
locale.setlocale(LC_ALL, "C"), which:
  1. Is not thread-safe — concurrent callers clobber each other.
  2. Forces getpreferredencoding() to ASCII, crashing subprocess.run(text=True)
     on any non-ASCII child output (UnicodeDecodeError).

Fix: never touch the process-global locale. Instead, pass LC_ALL=C via the
subprocess env kwarg, and set encoding="utf-8", errors="replace" on the
subprocess call so decoding never crashes.
"""
from __future__ import annotations

import locale
import subprocess
import sys
from unittest.mock import patch

import pytest

from token_sieve.cli import compress as compress_mod
from token_sieve.cli.compress import run as run_compress


@pytest.fixture(autouse=True)
def _no_bypass_store(monkeypatch):
    monkeypatch.setattr(compress_mod, "_get_bypass_store", lambda: None)


class TestNoProcessLocaleMutation:
    def test_compress_run_does_not_call_locale_setlocale(self, monkeypatch):
        """compress.run() must not mutate the process-global locale."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "true")

        calls: list[tuple] = []
        real_setlocale = locale.setlocale

        def tracking_setlocale(*args, **kwargs):
            # Only track mutating calls (args of form (LC_ALL, value))
            if len(args) >= 2:
                calls.append(args)
            return real_setlocale(*args, **kwargs)

        monkeypatch.setattr(locale, "setlocale", tracking_setlocale)

        run_compress([])

        assert not calls, (
            f"compress.run() must not mutate process locale; saw calls: {calls!r}"
        )


class TestChildEnvHasCLocale:
    def test_subprocess_env_sets_lc_all_c(self, monkeypatch):
        """The child subprocess env must include LC_ALL=C and LANG=C.

        The child still needs deterministic number/date formatting — but this
        must be achieved via the env kwarg, not via mutating the parent.
        """
        monkeypatch.setenv("TSIEV_WRAP_CMD", "true")

        captured_env: dict = {}

        def fake_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env") or {})
            result = subprocess.CompletedProcess(cmd, 0, "", "")
            return result

        with patch.object(compress_mod.subprocess, "run", side_effect=fake_run):
            run_compress([])

        assert captured_env.get("LC_ALL") == "C", (
            f"LC_ALL must be C in child env; got {captured_env.get('LC_ALL')!r}"
        )
        assert captured_env.get("LANG") == "C", (
            f"LANG must be C in child env; got {captured_env.get('LANG')!r}"
        )


class TestUTF8DecodeDoesNotCrash:
    def test_non_ascii_child_output_does_not_crash(self, monkeypatch, capsys):
        """A child emitting UTF-8 characters must not raise UnicodeDecodeError.

        Without encoding="utf-8" and a mutated LC_ALL=C, text=True uses
        getpreferredencoding() = ASCII and crashes.
        """
        monkeypatch.setenv(
            "TSIEV_WRAP_CMD",
            f"{sys.executable} -c \"import sys; sys.stdout.write('caf\\u00e9\\n')\"",
        )

        # This must NOT raise.
        rc = run_compress([])
        captured = capsys.readouterr()

        assert rc == 0
        # The literal non-ASCII character should be preserved (or at worst
        # replaced by the replacement character — but not crash).
        assert "caf" in captured.out
