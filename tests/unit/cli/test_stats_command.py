"""Tests for 'token-sieve stats' CLI command."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from token_sieve.cli.main import main


class TestStatsCommand:
    """token-sieve stats reads metrics.json and prints formatted table."""

    def test_stats_prints_formatted_table(
        self, capsys, tmp_path: Path, monkeypatch
    ) -> None:
        """stats command reads metrics.json and displays session summary."""
        metrics_data = {
            "session_summary": {
                "total_original_tokens": 1000,
                "total_compressed_tokens": 400,
                "total_savings_ratio": 0.6,
                "event_count": 5,
            },
            "strategy_breakdown": {
                "whitespace": {
                    "count": 3,
                    "total_original_tokens": 600,
                    "total_compressed_tokens": 200,
                },
                "null_elider": {
                    "count": 2,
                    "total_original_tokens": 400,
                    "total_compressed_tokens": 200,
                },
            },
        }

        metrics_path = tmp_path / "metrics.json"
        metrics_path.write_text(json.dumps(metrics_data))

        monkeypatch.setenv(
            "TOKEN_SIEVE_METRICS_PATH", str(metrics_path)
        )

        exit_code = main(["stats"])
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "1000" in captured.out
        assert "400" in captured.out
        assert "whitespace" in captured.out

    def test_stats_missing_file_shows_error(
        self, capsys, tmp_path: Path, monkeypatch
    ) -> None:
        """stats with no metrics file shows informative error."""
        monkeypatch.setenv(
            "TOKEN_SIEVE_METRICS_PATH",
            str(tmp_path / "nonexistent.json"),
        )

        exit_code = main(["stats"])
        assert exit_code == 1

        captured = capsys.readouterr()
        assert "no metrics" in captured.err.lower() or "not found" in captured.err.lower()
