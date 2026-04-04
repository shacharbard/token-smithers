"""Tests for SQLiteLearningStore telemetry query methods.

Tests unified telemetry queries: session reports, cross-server stats,
adapter effectiveness, and savings trends.
"""

from __future__ import annotations

import pytest

from token_sieve.domain.model import CompressionEvent, ContentType


@pytest.fixture()
async def store():
    """Provide SQLiteLearningStore with in-memory DB."""
    from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

    store = await SQLiteLearningStore.connect(":memory:")
    yield store
    await store.close()


async def _insert_events(
    store,
    session_id: str,
    tool_name: str,
    strategy_name: str,
    original: int,
    compressed: int,
    count: int = 1,
) -> None:
    """Helper to insert multiple compression events."""
    for _ in range(count):
        event = CompressionEvent(
            original_tokens=original,
            compressed_tokens=compressed,
            strategy_name=strategy_name,
            content_type=ContentType.JSON,
        )
        await store.record_compression_event(session_id, event, tool_name)


class TestGetSessionReport:
    """Tests for get_session_report() telemetry method."""

    @pytest.mark.asyncio
    async def test_get_session_report_returns_breakdown(self, store) -> None:
        """Insert events for multiple tools/strategies, verify breakdowns."""
        await _insert_events(store, "s1", "read_file", "whitespace", 1000, 800, count=3)
        await _insert_events(store, "s1", "grep", "null_elider", 500, 300, count=2)
        await _insert_events(store, "s1", "read_file", "null_elider", 200, 100, count=1)

        report = await store.get_session_report("s1")

        assert "tool_breakdown" in report
        assert "strategy_breakdown" in report
        assert "totals" in report

        # Tool breakdown
        tools = {t["tool_name"]: t for t in report["tool_breakdown"]}
        assert "read_file" in tools
        assert "grep" in tools
        assert tools["read_file"]["total_original"] == 3 * 1000 + 200
        assert tools["read_file"]["total_compressed"] == 3 * 800 + 100
        assert tools["read_file"]["event_count"] == 4

        # Strategy breakdown
        strategies = {s["strategy_name"]: s for s in report["strategy_breakdown"]}
        assert "whitespace" in strategies
        assert "null_elider" in strategies

        # Totals
        assert report["totals"]["total_original"] == 3 * 1000 + 2 * 500 + 200
        assert report["totals"]["total_compressed"] == 3 * 800 + 2 * 300 + 100
        assert report["totals"]["event_count"] == 6

    @pytest.mark.asyncio
    async def test_get_session_report_empty_session(self, store) -> None:
        """Empty session returns zero-filled report."""
        report = await store.get_session_report("nonexistent")

        assert report["tool_breakdown"] == []
        assert report["strategy_breakdown"] == []
        assert report["totals"]["event_count"] == 0


class TestGetCrossServerStats:
    """Tests for get_cross_server_stats()."""

    @pytest.mark.asyncio
    async def test_get_cross_server_comparison(self, store) -> None:
        """Insert events for multiple server_ids, verify aggregation."""
        # Record calls for different servers
        await store.record_call("tool_a", "server_1")
        await store.record_call("tool_a", "server_1")
        await store.record_call("tool_b", "server_2")

        # Insert compression events with different sessions
        await _insert_events(store, "s1", "tool_a", "whitespace", 1000, 600, count=2)
        await _insert_events(store, "s2", "tool_b", "null_elider", 500, 200, count=1)

        stats = await store.get_cross_server_stats()

        assert len(stats) >= 1
        # Should have per-tool aggregation
        tool_map = {s["tool_name"]: s for s in stats}
        assert "tool_a" in tool_map
        assert tool_map["tool_a"]["total_saved"] == 2 * (1000 - 600)


class TestGetAdapterEffectiveness:
    """Tests for get_adapter_effectiveness()."""

    @pytest.mark.asyncio
    async def test_get_adapter_effectiveness(self, store) -> None:
        """Verify adapters ranked by total tokens saved."""
        await _insert_events(store, "s1", "tool_a", "whitespace", 1000, 600, count=5)
        await _insert_events(store, "s1", "tool_a", "null_elider", 500, 100, count=3)
        await _insert_events(store, "s1", "tool_b", "toon", 2000, 500, count=1)

        results = await store.get_adapter_effectiveness(limit=10)

        assert len(results) == 3
        # whitespace: 5*(1000-600)=2000, toon: 1*(2000-500)=1500, null_elider: 3*(500-100)=1200
        assert results[0]["strategy_name"] == "whitespace"
        assert results[0]["total_saved"] == 2000
        assert results[1]["strategy_name"] == "toon"
        assert results[1]["total_saved"] == 1500
        assert results[2]["strategy_name"] == "null_elider"
        assert results[2]["total_saved"] == 1200

    @pytest.mark.asyncio
    async def test_get_adapter_effectiveness_sorted(self, store) -> None:
        """Ensure results sorted by total saved descending."""
        await _insert_events(store, "s1", "t", "low_saver", 100, 90, count=1)  # 10
        await _insert_events(store, "s1", "t", "high_saver", 1000, 100, count=1)  # 900
        await _insert_events(store, "s1", "t", "mid_saver", 500, 200, count=1)  # 300

        results = await store.get_adapter_effectiveness(limit=10)

        names = [r["strategy_name"] for r in results]
        assert names == ["high_saver", "mid_saver", "low_saver"]

    @pytest.mark.asyncio
    async def test_get_adapter_effectiveness_limit(self, store) -> None:
        """Limit parameter caps result count."""
        await _insert_events(store, "s1", "t", "a", 100, 50, count=1)
        await _insert_events(store, "s1", "t", "b", 100, 50, count=1)
        await _insert_events(store, "s1", "t", "c", 100, 50, count=1)

        results = await store.get_adapter_effectiveness(limit=2)
        assert len(results) == 2


class TestGetSavingsTrend:
    """Tests for get_savings_trend()."""

    @pytest.mark.asyncio
    async def test_get_savings_trend(self, store) -> None:
        """Insert events across sessions, verify trend data."""
        await _insert_events(store, "session_1", "tool_a", "ws", 1000, 600, count=2)
        await _insert_events(store, "session_2", "tool_a", "ws", 800, 400, count=1)
        await _insert_events(store, "session_3", "tool_b", "ne", 500, 200, count=3)

        trend = await store.get_savings_trend(sessions=10)

        assert len(trend) == 3
        # Each entry should have session_id, total_original, total_compressed, total_saved
        session_ids = [t["session_id"] for t in trend]
        assert "session_1" in session_ids
        assert "session_2" in session_ids
        assert "session_3" in session_ids

        s1 = next(t for t in trend if t["session_id"] == "session_1")
        assert s1["total_original"] == 2000
        assert s1["total_compressed"] == 1200
        assert s1["total_saved"] == 800

    @pytest.mark.asyncio
    async def test_get_savings_trend_limit(self, store) -> None:
        """Limit caps the number of sessions returned."""
        for i in range(5):
            await _insert_events(store, f"s{i}", "tool", "ws", 100, 50, count=1)

        trend = await store.get_savings_trend(sessions=3)
        assert len(trend) == 3
