"""Tests for InMemoryMetricsCollector -- event recording and summaries.

TDD RED phase: these tests define the metrics contract before implementation.
"""

from __future__ import annotations

import pytest

from token_sieve.domain.model import CompressionEvent, ContentType
from token_sieve.domain.ports import MetricsCollector


class TestInMemoryMetricsCollector:
    """InMemoryMetricsCollector records events and produces summaries."""

    def test_record_stores_event(self, make_event):
        from token_sieve.domain.metrics import InMemoryMetricsCollector

        collector = InMemoryMetricsCollector()
        event = make_event()
        collector.record(event)

        assert len(collector._events) == 1
        assert collector._events[0] is event

    def test_session_summary_returns_totals(self, make_event):
        from token_sieve.domain.metrics import InMemoryMetricsCollector

        collector = InMemoryMetricsCollector()
        collector.record(make_event(original_tokens=100, compressed_tokens=60))
        collector.record(make_event(original_tokens=200, compressed_tokens=80))

        summary = collector.session_summary()
        assert summary["total_original_tokens"] == 300
        assert summary["total_compressed_tokens"] == 140
        assert summary["total_savings_ratio"] == pytest.approx(
            1.0 - 140 / 300
        )
        assert summary["event_count"] == 2

    def test_strategy_breakdown_groups_by_strategy(self, make_event):
        from token_sieve.domain.metrics import InMemoryMetricsCollector

        collector = InMemoryMetricsCollector()
        collector.record(
            make_event(
                strategy_name="truncate",
                original_tokens=100,
                compressed_tokens=60,
            )
        )
        collector.record(
            make_event(
                strategy_name="truncate",
                original_tokens=200,
                compressed_tokens=80,
            )
        )
        collector.record(
            make_event(
                strategy_name="dedup",
                original_tokens=50,
                compressed_tokens=10,
            )
        )

        breakdown = collector.strategy_breakdown()
        assert "truncate" in breakdown
        assert "dedup" in breakdown
        assert breakdown["truncate"]["count"] == 2
        assert breakdown["truncate"]["total_original_tokens"] == 300
        assert breakdown["truncate"]["total_compressed_tokens"] == 140
        assert breakdown["dedup"]["count"] == 1
        assert breakdown["dedup"]["total_original_tokens"] == 50
        assert breakdown["dedup"]["total_compressed_tokens"] == 10

    def test_empty_collector_returns_zero_summary(self):
        from token_sieve.domain.metrics import InMemoryMetricsCollector

        collector = InMemoryMetricsCollector()
        summary = collector.session_summary()

        assert summary["total_original_tokens"] == 0
        assert summary["total_compressed_tokens"] == 0
        assert summary["total_savings_ratio"] == 0.0
        assert summary["event_count"] == 0

    def test_empty_collector_returns_empty_breakdown(self):
        from token_sieve.domain.metrics import InMemoryMetricsCollector

        collector = InMemoryMetricsCollector()
        breakdown = collector.strategy_breakdown()
        assert breakdown == {}

    def test_satisfies_metrics_collector_protocol(self):
        from token_sieve.domain.metrics import InMemoryMetricsCollector

        collector = InMemoryMetricsCollector()
        assert hasattr(collector, "record")
        assert hasattr(collector, "session_summary")
        assert hasattr(collector, "strategy_breakdown")
        assert callable(collector.record)
        assert callable(collector.session_summary)
        assert callable(collector.strategy_breakdown)

    # --- Finding 6: bounded growth ---

    def test_evicts_oldest_at_max_events(self, make_event):
        from token_sieve.domain.metrics import InMemoryMetricsCollector

        collector = InMemoryMetricsCollector(max_events=3)
        for i in range(5):
            collector.record(make_event(original_tokens=i))

        assert len(collector._events) == 3
        # Oldest (i=0, i=1) evicted; remaining are i=2, i=3, i=4
        assert collector._events[0].original_tokens == 2
        assert collector._events[-1].original_tokens == 4

    def test_default_max_events_is_10000(self):
        from token_sieve.domain.metrics import (
            DEFAULT_MAX_EVENTS,
            InMemoryMetricsCollector,
        )

        assert DEFAULT_MAX_EVENTS == 10_000
        collector = InMemoryMetricsCollector()
        assert collector._events.maxlen == 10_000
