"""RED tests for M6 — fail-open annotation leaks str(exc) to stderr.

Current template is:
    [token-sieve: compression failed ({type}: {msg}), raw output below — please report]
where {msg} is str(exc). Exception messages can contain file paths,
cached content snippets, env var values, etc. Leaking them into the
user-visible stderr annotation is a minor information disclosure.

Fix:
  - Template only includes {type} — the exception class name.
  - Full str(exc) is logged via logger.warning on the "token_sieve" logger.
"""
from __future__ import annotations

import logging

import pytest

from token_sieve.cli import compress as compress_mod
from token_sieve.cli.compress import run as run_compress


@pytest.fixture(autouse=True)
def _no_bypass_store(monkeypatch):
    monkeypatch.setattr(compress_mod, "_get_bypass_store", lambda: None)


SECRET_MESSAGE = "SENSITIVE_PATH=/home/user/.secrets/token_ab12cd34"


def _force_pipeline_failure(monkeypatch) -> None:
    from token_sieve.domain.pipeline import CompressionPipeline

    def boom(self_arg, envelope):
        raise RuntimeError(SECRET_MESSAGE)

    monkeypatch.setattr(CompressionPipeline, "process", boom)


class TestFailOpenDoesNotLeakException:
    def test_stderr_annotation_omits_exception_message(self, monkeypatch, capsys):
        """Fail-open stderr must NOT contain str(exc)."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo RAWOUT'")
        _force_pipeline_failure(monkeypatch)

        rc = run_compress([])
        captured = capsys.readouterr()

        assert rc == 0
        assert "RAWOUT" in captured.out
        # The exception type is still OK to show — gives users a hint.
        assert "RuntimeError" in captured.err
        assert "compression failed" in captured.err
        # But the full str(exc) must NOT appear on stderr.
        assert SECRET_MESSAGE not in captured.err, (
            f"M6: str(exc) leaked to stderr; got err={captured.err!r}"
        )
        assert "SENSITIVE_PATH" not in captured.err

    def test_full_exception_is_logged(self, monkeypatch, capsys, caplog):
        """Full str(exc) must still be available via the logger."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo RAWOUT'")
        _force_pipeline_failure(monkeypatch)

        with caplog.at_level(logging.WARNING, logger="token_sieve"):
            run_compress([])

        # At least one warning-or-higher record should mention the secret.
        messages = [rec.getMessage() for rec in caplog.records]
        assert any(SECRET_MESSAGE in m for m in messages), (
            f"Full exception must be logged via logger; records={messages!r}"
        )
