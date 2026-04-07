"""Tests for MetricsFileWriter — periodic JSON flush to disk."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from token_sieve.domain.model import CompressionEvent, ContentType


class TestMetricsFileWriter:
    """MetricsFileWriter writes collector summary to JSON file."""

    def test_flush_writes_valid_json(self, tmp_path: Path) -> None:
        """flush() writes valid JSON containing session summary + breakdown."""
        from token_sieve.domain.metrics import InMemoryMetricsCollector
        from token_sieve.server.metrics_writer import MetricsFileWriter

        collector = InMemoryMetricsCollector()
        collector.record(
            CompressionEvent(
                original_tokens=200,
                compressed_tokens=80,
                strategy_name="whitespace",
                content_type=ContentType.TEXT,
            )
        )

        metrics_path = tmp_path / "metrics.json"
        writer = MetricsFileWriter(
            collector=collector, metrics_path=str(metrics_path)
        )
        writer.flush()

        data = json.loads(metrics_path.read_text())
        assert "session_summary" in data
        assert "strategy_breakdown" in data
        assert data["session_summary"]["event_count"] == 1

    def test_flush_after_threshold_events(self, tmp_path: Path) -> None:
        """Writer auto-flushes after configured event threshold."""
        from token_sieve.domain.metrics import InMemoryMetricsCollector
        from token_sieve.server.metrics_writer import MetricsFileWriter

        collector = InMemoryMetricsCollector()
        metrics_path = tmp_path / "metrics.json"
        writer = MetricsFileWriter(
            collector=collector,
            metrics_path=str(metrics_path),
            flush_every_n=3,
        )

        for i in range(3):
            event = CompressionEvent(
                original_tokens=100,
                compressed_tokens=50,
                strategy_name="test",
                content_type=ContentType.TEXT,
            )
            writer.record_and_maybe_flush(event)

        assert metrics_path.exists()
        data = json.loads(metrics_path.read_text())
        assert data["session_summary"]["event_count"] == 3

    def test_default_flush_every_n_is_one_so_first_event_writes_file(
        self, tmp_path: Path
    ) -> None:
        """Default flush_every_n must be 1 so the first event flushes to disk.

        Locks in the early-visibility default: a single CompressionEvent
        recorded via record_and_maybe_flush() must produce metrics.json on
        disk without any explicit flush() call.
        """
        from token_sieve.domain.metrics import InMemoryMetricsCollector
        from token_sieve.server.metrics_writer import MetricsFileWriter

        collector = InMemoryMetricsCollector()
        metrics_path = tmp_path / "m.json"
        writer = MetricsFileWriter(
            collector=collector, metrics_path=str(metrics_path)
        )

        # Lock in the default explicitly so future regressions are obvious.
        assert writer._flush_every_n == 1

        writer.record_and_maybe_flush(
            CompressionEvent(
                original_tokens=120,
                compressed_tokens=40,
                strategy_name="whitespace",
                content_type=ContentType.TEXT,
            )
        )

        assert metrics_path.exists()

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        """Writer creates parent directories if they don't exist."""
        from token_sieve.domain.metrics import InMemoryMetricsCollector
        from token_sieve.server.metrics_writer import MetricsFileWriter

        collector = InMemoryMetricsCollector()
        collector.record(
            CompressionEvent(
                original_tokens=100,
                compressed_tokens=50,
                strategy_name="test",
                content_type=ContentType.TEXT,
            )
        )

        metrics_path = tmp_path / "subdir" / "metrics.json"
        writer = MetricsFileWriter(
            collector=collector, metrics_path=str(metrics_path)
        )
        writer.flush()
        assert metrics_path.exists()
