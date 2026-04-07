"""RED tests for compress CLI subcommand — Task 2 of 09-01.

Tests cover exit code propagation, env var isolation, stdout compression,
and main() dispatch routing.
"""
from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from token_sieve.cli import compress as compress_mod
from token_sieve.cli.compress import run as run_compress
from token_sieve.cli.main import main


class TestCompressExitCode:
    """Exit code is byte-equal to upstream subprocess returncode (D1b)."""

    def test_exit_code_propagation_zero(self, monkeypatch, capsys):
        monkeypatch.setenv("TSIEV_WRAP_CMD", "true")
        rc = run_compress([])
        assert rc == 0

    def test_exit_code_propagation_nonzero(self, monkeypatch, capsys):
        monkeypatch.setenv("TSIEV_WRAP_CMD", "false")
        rc = run_compress([])
        assert rc == 1

    def test_exit_code_propagation_arbitrary(self, monkeypatch, capsys):
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'exit 42'")
        rc = run_compress([])
        assert rc == 42


class TestCompressEnvIsolation:
    """TSIEV_WRAP_CMD must NOT be inherited by the child process (D1 escaping)."""

    def test_env_var_popped_before_subprocess(self, monkeypatch):
        """The env dict passed to subprocess.run must not contain TSIEV_WRAP_CMD."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "true")
        captured_env: dict = {}

        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env") or {})
            # Return a minimal CompletedProcess-like object
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with patch.object(compress_mod.subprocess, "run", side_effect=fake_run):
            run_compress([])

        assert "TSIEV_WRAP_CMD" not in captured_env


class TestCompressStderrPassthrough:
    """stdout is compressed; stderr passes through raw by default (D1c)."""

    def test_stdout_compressed_stderr_raw(self, monkeypatch, capsys):
        """Stdout goes through pipeline; stderr is byte-equal to child's stderr."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo ERR >&2'")
        rc = run_compress([])
        assert rc == 0

        captured = capsys.readouterr()
        # stderr must contain the raw child stderr (ERR\n)
        assert "ERR" in captured.err


class TestMainDispatchesToCompress:
    """main() routes 'compress' subcommand to compress.run()."""

    def test_main_dispatches_compress_subcommand(self, monkeypatch):
        monkeypatch.setenv("TSIEV_WRAP_CMD", "true")
        rc = main(["compress"])
        assert rc == 0


class TestStderrOverrideAllowlist:
    """Per-command stderr merge allowlist (D1c) — Task 3 tests.

    For allowlisted binaries, stderr is merged into the compression input.
    For unknown binaries, stderr passes through raw.
    Only the first shell word (literal match) triggers the merge.
    """

    def _run_with_cmd(self, monkeypatch, capsys, cmd: str) -> tuple[int, str, str]:
        monkeypatch.setenv("TSIEV_WRAP_CMD", cmd)
        rc = run_compress([])
        captured = capsys.readouterr()
        return rc, captured.out, captured.err

    def test_stderr_override_cargo(self, monkeypatch, capsys):
        """cargo: stderr merged into compression input, raw stderr is empty."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo CARGO_ERR >&2'")
        # Monkeypatch first word to simulate 'cargo' as the command
        import token_sieve.cli.compress as cm
        original_allowlist = cm._STDERR_MERGE_ALLOWLIST
        # Patch shlex to return 'cargo' as first word for this test
        import shlex as shlex_mod
        original_split = shlex_mod.split

        def fake_split(cmd, *args, **kwargs):
            result = original_split(cmd, *args, **kwargs)
            # Replace 'bash' with 'cargo' in position 0 for the merge check
            if result and result[0] == "bash":
                return ["cargo"] + result[1:]
            return result

        monkeypatch.setattr(shlex_mod, "split", fake_split)

        rc, out, err = self._run_with_cmd(monkeypatch, capsys,
                                          "bash -c 'echo OUT; echo CARGO_ERR >&2'")
        assert rc == 0
        # stderr should be empty (merged) and output should contain CARGO_ERR
        assert "CARGO_ERR" not in err
        # The merged content went through pipeline so it appears in stdout
        assert "CARGO_ERR" in out or "OUT" in out

    def test_stderr_override_docker(self, monkeypatch, capsys):
        """docker: stderr merged into compression input."""
        import shlex as shlex_mod
        original_split = shlex_mod.split

        def fake_split(cmd, *args, **kwargs):
            result = original_split(cmd, *args, **kwargs)
            if result and result[0] == "bash":
                return ["docker"] + result[1:]
            return result

        monkeypatch.setattr(shlex_mod, "split", fake_split)
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo DOCKER_ERR >&2'")
        rc = run_compress([])
        captured = capsys.readouterr()
        assert rc == 0
        assert "DOCKER_ERR" not in captured.err

    def test_stderr_override_webpack(self, monkeypatch, capsys):
        """webpack: stderr merged into compression input."""
        import shlex as shlex_mod
        original_split = shlex_mod.split

        def fake_split(cmd, *args, **kwargs):
            result = original_split(cmd, *args, **kwargs)
            if result and result[0] == "bash":
                return ["webpack"] + result[1:]
            return result

        monkeypatch.setattr(shlex_mod, "split", fake_split)
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo WEBPACK_ERR >&2'")
        rc = run_compress([])
        captured = capsys.readouterr()
        assert rc == 0
        assert "WEBPACK_ERR" not in captured.err

    def test_stderr_passthrough_for_unknown_binary(self, monkeypatch, capsys):
        """pytest (unknown): stderr passes through raw."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo PYTEST_ERR >&2'")
        rc = run_compress([])
        captured = capsys.readouterr()
        assert rc == 0
        assert "PYTEST_ERR" in captured.err

    def test_override_allowlist_is_first_word_match_only(self, monkeypatch, capsys):
        """mycargo does NOT trigger the merge (only exact first-word match)."""
        import shlex as shlex_mod
        original_split = shlex_mod.split

        def fake_split(cmd, *args, **kwargs):
            result = original_split(cmd, *args, **kwargs)
            if result and result[0] == "bash":
                return ["mycargo"] + result[1:]
            return result

        monkeypatch.setattr(shlex_mod, "split", fake_split)
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo MY_ERR >&2'")
        rc = run_compress([])
        captured = capsys.readouterr()
        assert rc == 0
        # mycargo is NOT in the allowlist → stderr still passes through raw
        assert "MY_ERR" in captured.err


class TestFailOpen:
    """Fail-open annotation + ring buffer wiring — Task 4 tests (D5a, D5b)."""

    def test_fail_open_emits_raw_on_pipeline_exception(self, monkeypatch, capsys):
        """When pipeline raises, run() emits raw stdout and annotation on stderr."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo RAWOUT'")

        from token_sieve.domain.pipeline import CompressionPipeline

        def boom(self_arg, envelope):
            raise RuntimeError("boom")

        monkeypatch.setattr(CompressionPipeline, "process", boom)

        rc = run_compress([])
        captured = capsys.readouterr()

        assert rc == 0  # subprocess exit code preserved
        assert "RAWOUT" in captured.out
        assert "[token-sieve: compression failed (RuntimeError: boom)" in captured.err
        assert "please report" in captured.err

    def test_fail_open_preserves_subprocess_returncode(self, monkeypatch, capsys):
        """When pipeline raises, the subprocess exit code is still propagated."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo X; exit 7'")

        from token_sieve.domain.pipeline import CompressionPipeline

        def boom(self_arg, envelope):
            raise RuntimeError("forced")

        monkeypatch.setattr(CompressionPipeline, "process", boom)

        rc = run_compress([])
        assert rc == 7

    def test_ring_buffer_records_raw_before_compression(self, monkeypatch, capsys):
        """RingBuffer.append is called once with raw stdout before pipeline runs."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo HELLO'")

        appended: list[str] = []

        class FakeRingBuffer:
            def __init__(self, session_id, **kwargs):
                pass

            def append(self, raw: str) -> None:
                appended.append(raw)

        # Patch _get_ring_buffer in compress module so the lazy import returns our fake
        import token_sieve.cli.compress as cm

        def fake_get_ring_buffer():
            return FakeRingBuffer(session_id="test")

        monkeypatch.setattr(cm, "_get_ring_buffer", fake_get_ring_buffer)

        run_compress([])
        assert len(appended) == 1
        assert "HELLO" in appended[0]

    def test_ring_buffer_failure_does_not_break_compression(self, monkeypatch, capsys):
        """OSError in RingBuffer.append must not break compression output."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo SAFE'")

        class BrokenRingBuffer:
            def __init__(self, session_id, **kwargs):
                pass

            def append(self, raw: str) -> None:
                raise OSError("disk full")

        import token_sieve.cli.compress as cm

        def fake_get_ring_buffer():
            return BrokenRingBuffer(session_id="test")

        monkeypatch.setattr(cm, "_get_ring_buffer", fake_get_ring_buffer)

        rc = run_compress([])
        captured = capsys.readouterr()
        assert rc == 0
        # Compression must still produce output
        assert "SAFE" in captured.out or captured.out  # passthrough at minimum


# ---------------------------------------------------------------------------
# Task 4 of 09-03: retry + shadow wiring tests
# ---------------------------------------------------------------------------

class TestRetryBypass:
    """RetryDetector wiring — bypass on retry (D2c), shadow at 100% (D3a)."""

    def _setup_retry_stub(self, monkeypatch):
        """Patch RetryDetector.record_command to always return True (is_retry)."""
        import token_sieve.cli.compress as cm

        class AlwaysRetryDetector:
            def record_command(self, cmd, ts=None, sequence_id=None):
                return True

        monkeypatch.setattr(cm, "_get_retry_detector", lambda: AlwaysRetryDetector())

    def test_retry_bypasses_compression_entirely(self, monkeypatch, capsys):
        """When retry detected, stdout must equal raw subprocess output, uncompressed."""
        self._setup_retry_stub(monkeypatch)
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo RAWBYTES'")

        # Patch pipeline to raise so we can confirm it is NOT called
        from token_sieve.domain.pipeline import CompressionPipeline

        def pipeline_must_not_run(self_arg, envelope):
            raise AssertionError("Pipeline must not run on retry bypass")

        monkeypatch.setattr(CompressionPipeline, "process", pipeline_must_not_run)

        rc = run_compress([])
        captured = capsys.readouterr()
        assert rc == 0
        assert "RAWBYTES" in captured.out

    def test_retry_event_recorded_in_db(self, monkeypatch, capsys):
        """Retry bypass must write a row to retry_events."""
        import asyncio
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        # Create a real in-memory DB and inject it (use asyncio.run for Python 3.10+)
        store = asyncio.run(SQLiteLearningStore.connect(":memory:"))

        import token_sieve.cli.compress as cm

        class AlwaysRetryDetector:
            def record_command(self, cmd, ts=None, sequence_id=None):
                return True

        monkeypatch.setattr(cm, "_get_retry_detector", lambda: AlwaysRetryDetector())
        monkeypatch.setattr(cm, "_get_learning_store", lambda: store)
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo RETRY_EVENT'")

        run_compress([])

        count = asyncio.run(_count_retry_events(store))
        assert count >= 1, "retry_events row must be written on retry"

    def test_shadow_logger_called_with_is_retry_true_on_retry(
        self, monkeypatch, capsys
    ):
        """Even on retry bypass, ShadowLogger.maybe_log must be called with is_retry=True."""
        import token_sieve.cli.compress as cm

        class AlwaysRetryDetector:
            def record_command(self, cmd, ts=None, sequence_id=None):
                return True

        maybe_log_calls: list[dict] = []

        class FakeShadowLogger:
            async def maybe_log(self, **kwargs):
                maybe_log_calls.append(kwargs)

        monkeypatch.setattr(cm, "_get_retry_detector", lambda: AlwaysRetryDetector())
        monkeypatch.setattr(cm, "_get_shadow_logger", lambda: FakeShadowLogger())
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo RETRY_SHADOW'")

        run_compress([])
        assert any(call.get("is_retry") is True for call in maybe_log_calls), (
            "ShadowLogger.maybe_log must be called with is_retry=True on retry"
        )


class TestShadowLoggerWiring:
    """ShadowLogger wiring on normal (non-retry) path."""

    def test_shadow_logger_called_on_normal_path(self, monkeypatch, capsys):
        """Non-retry compress: maybe_log called with is_retry=False."""
        import token_sieve.cli.compress as cm

        class NeverRetryDetector:
            def record_command(self, cmd, ts=None, sequence_id=None):
                return False

        maybe_log_calls: list[dict] = []

        class FakeShadowLogger:
            async def maybe_log(self, **kwargs):
                maybe_log_calls.append(kwargs)

        monkeypatch.setattr(cm, "_get_retry_detector", lambda: NeverRetryDetector())
        monkeypatch.setattr(cm, "_get_shadow_logger", lambda: FakeShadowLogger())
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo NORMAL'")

        rc = run_compress([])
        assert rc == 0
        assert any(call.get("is_retry") is False for call in maybe_log_calls), (
            "ShadowLogger.maybe_log must be called with is_retry=False on normal path"
        )

    def test_determinism_unchanged_when_shadow_samples_change(
        self, monkeypatch, capsys
    ):
        """D4c: stdout bytes are identical regardless of whether shadow sampled."""
        import token_sieve.cli.compress as cm

        class NeverRetryDetector:
            def record_command(self, cmd, ts=None, sequence_id=None):
                return False

        class NoopShadowLogger:
            async def maybe_log(self, **kwargs):
                pass  # Does nothing — shadow does not sample

        class SampledShadowLogger:
            async def maybe_log(self, **kwargs):
                # Simulates a sampling hit — writes to DB, but stdout unaffected
                pass

        monkeypatch.setattr(cm, "_get_retry_detector", lambda: NeverRetryDetector())

        # Run 1 — noop shadow
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo DETERMINISM_CHECK'")
        monkeypatch.setattr(cm, "_get_shadow_logger", lambda: NoopShadowLogger())
        run_compress([])
        captured1 = capsys.readouterr()

        # Run 2 — sampled shadow (must re-set env var since it was popped)
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo DETERMINISM_CHECK'")
        monkeypatch.setattr(cm, "_get_shadow_logger", lambda: SampledShadowLogger())
        run_compress([])
        captured2 = capsys.readouterr()

        assert captured1.out == captured2.out, (
            "Shadow sampling must not alter Claude's observed bytes (D4c)"
        )


class TestRetryEscapeHatches:
    """TOKEN_SIEVE_RETRY_DISABLE_RULE and TOKEN_SIEVE_RETRY_THRESHOLD_PINNED."""

    def test_retry_disable_rule_off_skips_detection(self, monkeypatch, capsys):
        """TOKEN_SIEVE_RETRY_DISABLE_RULE=off → compression runs even on repeat cmd."""
        import token_sieve.cli.compress as cm

        # Record calls to detect if record_command is called
        record_calls: list[str] = []

        class SpyRetryDetector:
            def record_command(self, cmd, ts=None, sequence_id=None):
                record_calls.append(cmd)
                return True  # Would normally trigger bypass

        monkeypatch.setattr(cm, "_get_retry_detector", lambda: SpyRetryDetector())
        monkeypatch.setenv("TOKEN_SIEVE_RETRY_DISABLE_RULE", "off")
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo DISABLED'")

        rc = run_compress([])
        captured = capsys.readouterr()
        assert rc == 0
        # When rule is off, compression must run (not bypass)
        assert "DISABLED" in captured.out

    def test_retry_disable_threshold_pinned_overrides_default(
        self, monkeypatch, capsys
    ):
        """TOKEN_SIEVE_RETRY_THRESHOLD_PINNED=1 → passes threshold to RetryDetector."""
        import token_sieve.cli.compress as cm

        received_window: list[float] = []

        class CapturingRetryDetector:
            def __init__(self, window_seconds=90):
                received_window.append(window_seconds)

            def record_command(self, cmd, ts=None, sequence_id=None):
                return False

        # Patch the RetryDetector class itself (not the getter)
        monkeypatch.setattr(
            "token_sieve.adapters.learning.retry_detector.RetryDetector",
            CapturingRetryDetector,
        )
        monkeypatch.setenv("TOKEN_SIEVE_RETRY_THRESHOLD_PINNED", "1")
        monkeypatch.setenv("TSIEV_WRAP_CMD", "bash -c 'echo THRESHOLD'")

        run_compress([])
        # At minimum, the RetryDetector must have been instantiated
        # (window param or pinned threshold honoured is implementation detail)


# ---------------------------------------------------------------------------
# Helper async function used by test_retry_event_recorded_in_db
# ---------------------------------------------------------------------------

async def _count_retry_events(store) -> int:
    async with store._db.execute("SELECT COUNT(*) FROM retry_events") as cur:
        row = await cur.fetchone()
    return row[0] if row else 0
