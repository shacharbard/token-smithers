"""RED tests for bypass + denylist wiring in compress CLI.

Task 4 of 09-04: verify all 4 D5c bypass layers work end-to-end through
the compress subcommand, and that bypass check happens BEFORE retry detection.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from token_sieve.cli import compress as compress_module


def _make_subprocess_result(stdout: str = "hello output", returncode: int = 0):
    """Create a mock subprocess.CompletedProcess."""
    mock = MagicMock()
    mock.stdout = stdout
    mock.stderr = ""
    mock.returncode = returncode
    return mock


@pytest.fixture()
async def bypass_store_with_db():
    """Create a real BypassStore backed by an in-memory SQLiteLearningStore."""
    from token_sieve.adapters.learning.bypass_store import BypassStore
    from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

    store = await SQLiteLearningStore.connect(":memory:")
    bs = BypassStore(store=store)
    try:
        yield store, bs
    finally:
        await store.close()


class TestDenylistBypass:
    """Layer 1: built-in sensitive denylist."""

    def test_denylist_command_bypasses_compression(self, capsys, monkeypatch) -> None:
        """TSIEV_WRAP_CMD=aws sts ... → raw stdout, no compression pipeline."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "aws sts get-caller-identity")

        mock_result = _make_subprocess_result(stdout='{"Account": "123"}')
        pipeline_called = []

        with patch("subprocess.run", return_value=mock_result):
            with patch.object(
                compress_module, "_get_ring_buffer", return_value=MagicMock()
            ):
                with patch.object(
                    compress_module, "_get_retry_detector", return_value=MagicMock()
                ) as mock_retry_factory:
                    mock_retry_factory.return_value.record_command.side_effect = (
                        lambda _: pipeline_called.append(True) or False
                    )
                    with patch.object(
                        compress_module, "_get_learning_store", return_value=None
                    ):
                        rc = compress_module.run([])

        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out == '{"Account": "123"}'
        # RetryDetector.record_command must NOT be called (bypass short-circuits)
        assert not pipeline_called, "RetryDetector.record_command should not be called on denylist bypass"


class TestInlineNoCompressBypass:
    """Layer 2/3: inline NO_COMPRESS=1 with auto-learn recording."""

    def test_inline_no_compress_bypasses_and_counts(
        self, capsys, monkeypatch
    ) -> None:
        """TSIEV_WRAP_CMD=... + TSIEV_INLINE_NO_COMPRESS=1 → bypass + event recorded."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "pytest tests/auth")
        monkeypatch.setenv("TSIEV_INLINE_NO_COMPRESS", "1")

        mock_result = _make_subprocess_result(stdout="10 passed")
        recorded_events = []

        mock_bs = AsyncMock()
        mock_bs.is_bypassed.return_value = False
        mock_bs.record_inline_bypass.side_effect = lambda *a, **kw: recorded_events.append(("inline", a, kw)) or asyncio.coroutine(lambda: None)()

        with patch("subprocess.run", return_value=mock_result):
            with patch.object(compress_module, "_get_ring_buffer", return_value=MagicMock()):
                with patch.object(compress_module, "_get_retry_detector", return_value=MagicMock()):
                    with patch.object(compress_module, "_get_learning_store", return_value=None):
                        with patch.object(compress_module, "_get_bypass_store", return_value=mock_bs):
                            rc = compress_module.run([])

        captured = capsys.readouterr()
        assert rc == 0
        assert "10 passed" in captured.out
        # record_inline_bypass must have been called
        assert mock_bs.record_inline_bypass.called, "Should have called record_inline_bypass for inline marker"

    def test_inherited_no_compress_bypasses_but_does_not_count(
        self, capsys, monkeypatch
    ) -> None:
        """NO_COMPRESS=1 in os.environ (no TSIEV_INLINE) → bypass, no event recorded."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "pytest tests/")
        monkeypatch.setenv("NO_COMPRESS", "1")
        # Ensure TSIEV_INLINE_NO_COMPRESS is absent
        monkeypatch.delenv("TSIEV_INLINE_NO_COMPRESS", raising=False)

        mock_result = _make_subprocess_result(stdout="5 passed")
        mock_bs = AsyncMock()
        mock_bs.is_bypassed.return_value = False

        with patch("subprocess.run", return_value=mock_result):
            with patch.object(compress_module, "_get_ring_buffer", return_value=MagicMock()):
                with patch.object(compress_module, "_get_retry_detector", return_value=MagicMock()):
                    with patch.object(compress_module, "_get_learning_store", return_value=None):
                        with patch.object(compress_module, "_get_bypass_store", return_value=mock_bs):
                            rc = compress_module.run([])

        captured = capsys.readouterr()
        assert rc == 0
        assert "5 passed" in captured.out
        # record_inline_bypass must NOT have been called
        assert not mock_bs.record_inline_bypass.called, (
            "record_inline_bypass should NOT be called for inherited NO_COMPRESS"
        )


class TestLearnedRuleBypass:
    """Layer 3: learned + manual bypass rules."""

    def test_active_learned_rule_silently_bypasses_and_reinforces(
        self, capsys, monkeypatch
    ) -> None:
        """Active learned rule for command → bypass + passive reinforcement."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "pytest tests/auth/test_login.py")
        monkeypatch.delenv("NO_COMPRESS", raising=False)
        monkeypatch.delenv("TSIEV_INLINE_NO_COMPRESS", raising=False)

        mock_result = _make_subprocess_result(stdout="passed")
        mock_bs = AsyncMock()
        mock_bs.is_bypassed.return_value = True

        with patch("subprocess.run", return_value=mock_result):
            with patch.object(compress_module, "_get_ring_buffer", return_value=MagicMock()):
                with patch.object(compress_module, "_get_retry_detector", return_value=MagicMock()):
                    with patch.object(compress_module, "_get_learning_store", return_value=None):
                        with patch.object(compress_module, "_get_bypass_store", return_value=mock_bs):
                            rc = compress_module.run([])

        captured = capsys.readouterr()
        assert rc == 0
        assert "passed" in captured.out
        assert mock_bs.record_passive_reinforcement.called, (
            "Passive reinforcement should be called when a learned rule fires"
        )

    def test_manual_added_rule_bypasses(self, capsys, monkeypatch) -> None:
        """Manual bypass rule → bypass executes."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "kubectl get secret mysecret")
        monkeypatch.delenv("NO_COMPRESS", raising=False)
        monkeypatch.delenv("TSIEV_INLINE_NO_COMPRESS", raising=False)

        mock_result = _make_subprocess_result(stdout="apiVersion: v1")
        mock_bs = AsyncMock()
        mock_bs.is_bypassed.return_value = True

        with patch("subprocess.run", return_value=mock_result):
            with patch.object(compress_module, "_get_ring_buffer", return_value=MagicMock()):
                with patch.object(compress_module, "_get_retry_detector", return_value=MagicMock()):
                    with patch.object(compress_module, "_get_learning_store", return_value=None):
                        with patch.object(compress_module, "_get_bypass_store", return_value=mock_bs):
                            rc = compress_module.run([])

        captured = capsys.readouterr()
        assert rc == 0
        assert "apiVersion" in captured.out

    def test_decayed_rule_does_not_bypass(self, capsys, monkeypatch) -> None:
        """Decayed rule (is_active=False via is_bypassed→False) → compression runs."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "pytest tests/stale")
        monkeypatch.delenv("NO_COMPRESS", raising=False)
        monkeypatch.delenv("TSIEV_INLINE_NO_COMPRESS", raising=False)

        mock_result = _make_subprocess_result(stdout="some output")
        mock_bs = AsyncMock()
        mock_bs.is_bypassed.return_value = False

        pipeline_ran = []

        class FakePipeline:
            def process(self, envelope):
                pipeline_ran.append(True)
                return envelope, []

        with patch("subprocess.run", return_value=mock_result):
            with patch.object(compress_module, "_get_ring_buffer", return_value=MagicMock()):
                with patch.object(compress_module, "_get_retry_detector", return_value=MagicMock(return_value=MagicMock(record_command=lambda _: False))):
                    with patch.object(compress_module, "_get_learning_store", return_value=None):
                        with patch.object(compress_module, "_get_bypass_store", return_value=mock_bs):
                            with patch("token_sieve.cli.main.create_pipeline") as mock_cp:
                                mock_cp.return_value = (FakePipeline(), MagicMock())
                                rc = compress_module.run([])

        assert rc == 0
        assert pipeline_ran, "Compression pipeline should run when rule is decayed/absent"


class TestCIBypassSkipsRecording:
    """CI detection test."""

    def test_ci_env_skips_auto_learn_recording(
        self, capsys, monkeypatch
    ) -> None:
        """CI=true + inline bypass → bypass happens but record_inline_bypass NOT called."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "pytest tests/")
        monkeypatch.setenv("TSIEV_INLINE_NO_COMPRESS", "1")
        monkeypatch.setenv("CI", "true")

        mock_result = _make_subprocess_result(stdout="ci output")
        mock_bs = AsyncMock()
        mock_bs.is_bypassed.return_value = False

        with patch("subprocess.run", return_value=mock_result):
            with patch.object(compress_module, "_get_ring_buffer", return_value=MagicMock()):
                with patch.object(compress_module, "_get_retry_detector", return_value=MagicMock()):
                    with patch.object(compress_module, "_get_learning_store", return_value=None):
                        with patch.object(compress_module, "_get_bypass_store", return_value=mock_bs):
                            rc = compress_module.run([])

        captured = capsys.readouterr()
        assert rc == 0
        # Bypass should still happen (raw output)
        assert "ci output" in captured.out
        # But record_inline_bypass should NOT be called (CI detection)
        assert not mock_bs.record_inline_bypass.called, (
            "CI=true should skip record_inline_bypass"
        )


class TestBypassOrderBeforeRetryDetection:
    """Bypass must short-circuit before retry detection."""

    def test_bypass_check_runs_BEFORE_retry_detection(
        self, monkeypatch
    ) -> None:
        """When bypass applies, RetryDetector.record_command is NOT called."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "aws sts get-caller-identity")
        monkeypatch.delenv("NO_COMPRESS", raising=False)
        monkeypatch.delenv("TSIEV_INLINE_NO_COMPRESS", raising=False)

        mock_result = _make_subprocess_result()
        retry_record_calls = []

        mock_retry = MagicMock()
        mock_retry.record_command.side_effect = lambda _: retry_record_calls.append(True) or False

        with patch("subprocess.run", return_value=mock_result):
            with patch.object(compress_module, "_get_ring_buffer", return_value=MagicMock()):
                with patch.object(compress_module, "_get_retry_detector", return_value=mock_retry):
                    with patch.object(compress_module, "_get_learning_store", return_value=None):
                        compress_module.run([])

        assert not retry_record_calls, (
            "RetryDetector.record_command should NOT be called when denylist bypasses"
        )


class TestFailOpenTelemetry:
    """D5d: fail-open compression error telemetry."""

    def test_fail_open_telemetry_recorded(
        self, capsys, monkeypatch
    ) -> None:
        """Pipeline exception → raw stdout + annotation; compression_errors recorded."""
        monkeypatch.setenv("TSIEV_WRAP_CMD", "echo hello")
        monkeypatch.delenv("NO_COMPRESS", raising=False)
        monkeypatch.delenv("TSIEV_INLINE_NO_COMPRESS", raising=False)

        mock_result = _make_subprocess_result(stdout="hello")
        error_rows = []

        mock_store = AsyncMock()
        mock_store._db = AsyncMock()

        async def fake_execute(sql, params=None):
            if "compression_errors" in sql and "INSERT" in sql:
                error_rows.append(params)
            return AsyncMock()

        mock_store._db.execute = fake_execute
        mock_store._db.commit = AsyncMock()

        mock_bs = AsyncMock()
        mock_bs.is_bypassed.return_value = False

        class BrokenPipeline:
            def process(self, _envelope):
                raise RuntimeError("adapter exploded")

        with patch("subprocess.run", return_value=mock_result):
            with patch.object(compress_module, "_get_ring_buffer", return_value=MagicMock()):
                with patch.object(compress_module, "_get_retry_detector", return_value=MagicMock(return_value=MagicMock(record_command=lambda _: False))):
                    with patch.object(compress_module, "_get_learning_store", return_value=mock_store):
                        with patch.object(compress_module, "_get_bypass_store", return_value=mock_bs):
                            with patch("token_sieve.cli.main.create_pipeline") as mock_cp:
                                mock_cp.return_value = (BrokenPipeline(), MagicMock())
                                rc = compress_module.run([])

        captured = capsys.readouterr()
        assert rc == 0
        assert "hello" in captured.out
        # Fail-open annotation on stderr
        assert "compression failed" in captured.err
        # compression_errors telemetry should be recorded
        assert error_rows, "Should record compression_errors row on pipeline exception"
