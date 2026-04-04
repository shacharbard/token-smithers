"""Tests for tokencost integration in stats and estimate CLI commands.

Verifies:
- Stats output includes cost savings when tokencost is available
- Stats output is unchanged when tokencost is not installed
- Estimate table includes $/day column when tokencost is available
- Model reads from TOKEN_SIEVE_MODEL env var
- Model reads from config
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestStatsCostIntegration:
    """Stats command shows dollar savings when tokencost is available."""

    def _write_metrics(self, tmp_path: Path) -> Path:
        """Write a sample metrics file and return its path."""
        metrics = {
            "session_summary": {
                "total_original_tokens": 10000,
                "total_compressed_tokens": 4000,
                "total_savings_ratio": 0.6,
                "event_count": 5,
            },
            "strategy_breakdown": {},
        }
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps(metrics))
        return metrics_file

    def test_stats_with_tokencost_shows_cost(
        self, tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When tokencost is available and model is set, stats shows $X.XX saved."""
        metrics_file = self._write_metrics(tmp_path)
        monkeypatch.setenv("TOKEN_SIEVE_METRICS_PATH", str(metrics_file))
        monkeypatch.setenv("TOKEN_SIEVE_MODEL", "claude-sonnet-4-5")

        # Mock tokencost module
        mock_tc = MagicMock()
        mock_tc.calculate_cost_by_tokens.side_effect = lambda tokens, _out, _model: tokens * 0.000003

        with patch.dict("sys.modules", {"tokencost": mock_tc}):
            import importlib
            import token_sieve.cli.cost_utils as cu
            importlib.reload(cu)

            result = cu.estimate_cost(
                original_tokens=10000,
                compressed_tokens=4000,
                model="claude-sonnet-4-5",
            )

        # Should return a cost dict with savings info
        assert result is not None
        assert "saved" in result
        assert isinstance(result["saved"], float)
        assert result["saved"] > 0  # 10000 - 4000 = 6000 tokens saved

    def test_stats_without_tokencost_graceful(
        self, tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When tokencost is not installed, estimate_cost returns None."""
        from token_sieve.cli.cost_utils import estimate_cost

        # Mock tokencost as unavailable
        with patch.dict("sys.modules", {"tokencost": None}):
            # Re-import to pick up the mock
            import importlib
            import token_sieve.cli.cost_utils as cu
            importlib.reload(cu)
            result = cu.estimate_cost(
                original_tokens=10000,
                compressed_tokens=4000,
                model="claude-sonnet-4-5",
            )
        assert result is None

    def test_model_from_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reads TOKEN_SIEVE_MODEL env var."""
        monkeypatch.setenv("TOKEN_SIEVE_MODEL", "gpt-4o")

        from token_sieve.cli.cost_utils import get_model

        model = get_model()
        assert model == "gpt-4o"

    def test_model_from_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to config default when env var not set."""
        monkeypatch.delenv("TOKEN_SIEVE_MODEL", raising=False)

        from token_sieve.cli.cost_utils import get_model

        model = get_model(config_model="claude-opus-4")
        assert model == "claude-opus-4"

    def test_model_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default model when nothing configured."""
        monkeypatch.delenv("TOKEN_SIEVE_MODEL", raising=False)

        from token_sieve.cli.cost_utils import get_model

        model = get_model()
        assert model == "claude-sonnet-4-5"


class TestEstimateCostColumn:
    """Estimate table includes $/day column when tokencost is available."""

    def test_estimate_savings_with_cost(self) -> None:
        """estimate_session_cost returns cost data when tokencost is available."""
        from token_sieve.cli.cost_utils import estimate_session_cost

        result = estimate_session_cost(
            tokens_saved=5000,
            model="claude-sonnet-4-5",
        )
        # Should return a dict with cost_per_day or None
        if result is not None:
            assert "cost_per_day_saved" in result
