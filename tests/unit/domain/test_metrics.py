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

    # --- H4: O(1) amortized summaries via rolling totals ---

    def test_session_summary_is_o1_not_full_scan(self, make_event):
        """session_summary() must not iterate the events collection.

        We enforce this by monkeypatching the events collection's __iter__ to
        raise; any code that still scans events will blow up. Rolling totals
        held on the collector itself should make this unnecessary.
        """
        from token_sieve.domain.metrics import InMemoryMetricsCollector

        collector = InMemoryMetricsCollector()
        for i in range(100):
            collector.record(
                make_event(
                    original_tokens=10,
                    compressed_tokens=4,
                    strategy_name="alpha" if i % 2 == 0 else "beta",
                )
            )

        # Sabotage the events container: summary code MUST NOT iterate it.
        class _Tripwire:
            def __iter__(self):
                raise AssertionError(
                    "session_summary / strategy_breakdown must not iterate _events"
                )

            def __len__(self):
                return 100

        collector._events = _Tripwire()  # type: ignore[assignment]

        summary = collector.session_summary()
        assert summary["total_original_tokens"] == 1000
        assert summary["total_compressed_tokens"] == 400
        assert summary["event_count"] == 100
        assert summary["total_savings_ratio"] == pytest.approx(0.6)

        breakdown = collector.strategy_breakdown()
        assert set(breakdown.keys()) == {"alpha", "beta"}
        assert breakdown["alpha"]["count"] == 50
        assert breakdown["beta"]["count"] == 50
        assert breakdown["alpha"]["total_original_tokens"] == 500
        assert breakdown["beta"]["total_compressed_tokens"] == 200

    def test_rolling_totals_correct_after_deque_eviction(self, make_event):
        """When max_events bound forces eviction, rolling totals must decrement
        for evicted events — otherwise they diverge from reality."""
        from token_sieve.domain.metrics import InMemoryMetricsCollector

        collector = InMemoryMetricsCollector(max_events=3)
        # Record 5 events; first 2 will be evicted.
        for i in range(5):
            collector.record(
                make_event(
                    original_tokens=100,
                    compressed_tokens=40,
                    strategy_name="s",
                )
            )

        summary = collector.session_summary()
        # Only the 3 retained events should count.
        assert summary["event_count"] == 3
        assert summary["total_original_tokens"] == 300
        assert summary["total_compressed_tokens"] == 120

        breakdown = collector.strategy_breakdown()
        assert breakdown["s"]["count"] == 3
        assert breakdown["s"]["total_original_tokens"] == 300
        assert breakdown["s"]["total_compressed_tokens"] == 120

    def test_rolling_totals_drop_strategy_when_all_evicted(self, make_event):
        """After a strategy's last event is evicted, it should disappear from
        strategy_breakdown (count == 0 entries must not linger)."""
        from token_sieve.domain.metrics import InMemoryMetricsCollector

        collector = InMemoryMetricsCollector(max_events=2)
        collector.record(make_event(strategy_name="old", original_tokens=10, compressed_tokens=5))
        collector.record(make_event(strategy_name="new", original_tokens=20, compressed_tokens=8))
        collector.record(make_event(strategy_name="new", original_tokens=30, compressed_tokens=12))
        # "old" should now be evicted.

        breakdown = collector.strategy_breakdown()
        assert "old" not in breakdown
        assert breakdown["new"]["count"] == 2
