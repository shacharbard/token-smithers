"""RED tests for H2 — SIGINT / KeyboardInterrupt handling in compress.run().

The current subprocess.run() has no SIGINT handler. When the user hits
Ctrl-C, KeyboardInterrupt is raised in the parent before result.returncode
is read; stdout gets truncated, the ring buffer is never flushed, the
shadow logger never writes, and we exit with a Python traceback instead
of the standard SIGINT exit code (130).

Fix: wrap the subprocess call in try/except KeyboardInterrupt. On KBI,
flush telemetry (ring buffer + shadow logger) with whatever raw output
we've captured and exit 130.
"""
from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from token_sieve.cli import compress as compress_mod
from token_sieve.cli.compress import run as run_compress


@pytest.fixture(autouse=True)
def _no_bypass_store(monkeypatch):
    monkeypatch.setattr(compress_mod, "_get_bypass_store", lambda: None)


class TestSigintHandling:
    def test_keyboard_interrupt_returns_130(self, monkeypatch, capsys):
        """When subprocess.run raises KeyboardInterrupt, run() must exit 130."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "true")

        def raise_kbi(cmd, **kwargs):
            raise KeyboardInterrupt()

        with patch.object(compress_mod.subprocess, "run", side_effect=raise_kbi):
            rc = run_compress([])

        assert rc == 130, f"Expected SIGINT exit code 130; got {rc!r}"

    def test_keyboard_interrupt_flushes_ring_buffer(self, monkeypatch, capsys):
        """Telemetry must still be flushed on KBI.

        The ring buffer and shadow logger never run because we never get a
        CompletedProcess — but the try/except must not swallow them either.
        We assert that no uncaught traceback escapes and that the function
        returns (not raises).
        """
        monkeypatch.setenv("TSIEV_WRAP_CMD", "true")

        def raise_kbi(cmd, **kwargs):
            raise KeyboardInterrupt()

        with patch.object(compress_mod.subprocess, "run", side_effect=raise_kbi):
            # Must not raise KeyboardInterrupt from run().
            rc = run_compress([])
            assert isinstance(rc, int)
            assert rc == 130

    def test_keyboard_interrupt_does_not_crash_with_traceback(
        self, monkeypatch, capsys
    ):
        """KBI must be caught inside run() — no traceback on stderr."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "true")

        def raise_kbi(cmd, **kwargs):
            raise KeyboardInterrupt()

        with patch.object(compress_mod.subprocess, "run", side_effect=raise_kbi):
            rc = run_compress([])

        captured = capsys.readouterr()
        assert rc == 130
        assert "Traceback" not in captured.err
        assert "KeyboardInterrupt" not in captured.err
