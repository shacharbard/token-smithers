"""Tests for `token-sieve stats --full` enhanced session report."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from token_sieve.cli.main import main


class TestStatsFullFlag:
    """Tests for --full flag on stats subcommand."""

    def test_stats_full_flag_accepted(self, tmp_path: Path, monkeypatch) -> None:
        """token-sieve stats --full doesn't error when metrics exist."""
        metrics = {
            "session_summary": {
                "event_count": 5,
                "total_original_tokens": 1000,
                "total_compressed_tokens": 600,
                "total_savings_ratio": 0.4,
            },
            "strategy_breakdown": {},
        }
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps(metrics))
        monkeypatch.setenv("TOKEN_SIEVE_METRICS_PATH", str(metrics_file))

        result = main(["stats", "--full"])
        assert result == 0

    def test_stats_full_shows_per_tool(self, tmp_path: Path, capsys, monkeypatch) -> None:
        """--full output includes per-tool token breakdown."""
        metrics = {
            "session_summary": {
                "event_count": 5,
                "total_original_tokens": 1000,
                "total_compressed_tokens": 600,
                "total_savings_ratio": 0.4,
            },
            "strategy_breakdown": {},
        }
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps(metrics))
        monkeypatch.setenv("TOKEN_SIEVE_METRICS_PATH", str(metrics_file))

        # Mock the learning DB query to return tool data
        tool_data = [
            {"tool_name": "read_file", "event_count": 10, "total_original": 5000,
             "total_compressed": 3000, "total_saved": 2000},
            {"tool_name": "grep", "event_count": 5, "total_original": 2000,
             "total_compressed": 1000, "total_saved": 1000},
        ]
        with patch(
            "token_sieve.cli.report_formatter.query_learning_telemetry",
            return_value={"tool_breakdown": tool_data, "adapter_effectiveness": [], "cross_server": [], "suggestions": []},
        ):
            main(["stats", "--full"])

        out = capsys.readouterr().out
        assert "read_file" in out
        assert "grep" in out

    def test_stats_full_shows_top_waste(self, tmp_path: Path, capsys, monkeypatch) -> None:
        """--full output includes top waste sources section."""
        metrics = {
            "session_summary": {
                "event_count": 5,
                "total_original_tokens": 1000,
                "total_compressed_tokens": 600,
                "total_savings_ratio": 0.4,
            },
            "strategy_breakdown": {},
        }
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps(metrics))
        monkeypatch.setenv("TOKEN_SIEVE_METRICS_PATH", str(metrics_file))

        adapter_data = [
            {"strategy_name": "whitespace", "event_count": 20, "total_original": 10000,
             "total_compressed": 5000, "total_saved": 5000},
        ]
        with patch(
            "token_sieve.cli.report_formatter.query_learning_telemetry",
            return_value={"tool_breakdown": [], "adapter_effectiveness": adapter_data, "cross_server": [], "suggestions": []},
        ):
            main(["stats", "--full"])

        out = capsys.readouterr().out
        assert "Adapter Effectiveness" in out or "whitespace" in out

    def test_stats_full_shows_cross_server(self, tmp_path: Path, capsys, monkeypatch) -> None:
        """--full output includes cross-server comparison."""
        metrics = {
            "session_summary": {
                "event_count": 5,
                "total_original_tokens": 1000,
                "total_compressed_tokens": 600,
                "total_savings_ratio": 0.4,
            },
            "strategy_breakdown": {},
        }
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps(metrics))
        monkeypatch.setenv("TOKEN_SIEVE_METRICS_PATH", str(metrics_file))

        cross_data = [
            {"tool_name": "tool_a", "event_count": 15, "total_original": 8000,
             "total_compressed": 4000, "total_saved": 4000},
        ]
        with patch(
            "token_sieve.cli.report_formatter.query_learning_telemetry",
            return_value={"tool_breakdown": [], "adapter_effectiveness": [], "cross_server": cross_data, "suggestions": []},
        ):
            main(["stats", "--full"])

        out = capsys.readouterr().out
        assert "Cross-Server" in out or "tool_a" in out


class TestStatsResource:
    """Tests for token-sieve://stats MCP resource."""

    @pytest.mark.asyncio
    async def test_stats_resource_includes_session_id(self) -> None:
        """token-sieve://stats resource response includes session_id."""
        from token_sieve.server.proxy import ProxyServer

        metrics_collector = MagicMock()
        metrics_collector.session_summary.return_value = {"total_original_tokens": 100}
        metrics_collector.strategy_breakdown.return_value = {}

        # Create a minimal proxy with session_id
        connector = AsyncMock()
        connector.list_tools = AsyncMock(return_value=[])

        from token_sieve.domain.counters import CharEstimateCounter
        from token_sieve.domain.pipeline import CompressionPipeline
        from token_sieve.server.metrics_sink import StderrMetricsSink
        from token_sieve.server.tool_filter import ToolFilter

        proxy = ProxyServer(
            backend_connector=connector,
            tool_filter=ToolFilter(mode="passthrough"),
            pipeline=CompressionPipeline(counter=CharEstimateCounter()),
            metrics_sink=StderrMetricsSink(),
            metrics_collector=metrics_collector,
        )

        result = await proxy.handle_read_resource("token-sieve://stats")
        data = json.loads(result)
        assert "session_id" in data
