"""Tests for RerankerPersistence cross-session bootstrap."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from token_sieve.adapters.rerank.reranker_persistence import RerankerPersistence
from token_sieve.adapters.rerank.statistical_reranker import StatisticalReranker
from token_sieve.domain.learning_types import CooccurrenceRecord, ToolUsageRecord
from token_sieve.domain.ports_learning import LearningStore


class FakeLearningStore:
    """In-memory fake for LearningStore Protocol.

    Enough to test bootstrap and persistence without SQLite.
    """

    def __init__(self) -> None:
        self._usage: list[ToolUsageRecord] = []
        self._calls: list[tuple[str, str]] = []
        self._cooccurrences: list[tuple[str, str]] = []

    def seed_usage(self, records: list[ToolUsageRecord]) -> None:
        self._usage = list(records)

    async def record_call(self, tool_name: str, server_id: str) -> None:
        self._calls.append((tool_name, server_id))

    async def get_usage_stats(self, server_id: str) -> list[ToolUsageRecord]:
        return [r for r in self._usage if r.server_id == server_id]

    async def cache_result(
        self, tool_name: str, args_normalized: str, result: str
    ) -> None:
        pass

    async def lookup_similar(
        self, tool_name: str, args_normalized: str, threshold: float
    ) -> str | None:
        return None

    async def record_compression_event(
        self, session_id: str, event: Any, tool_name: str
    ) -> None:
        pass

    async def record_cooccurrence(self, tool_a: str, tool_b: str) -> None:
        self._cooccurrences.append((tool_a, tool_b))

    async def get_cooccurrence(
        self, tool_name: str
    ) -> list[CooccurrenceRecord]:
        return []

    async def save_frozen_order(
        self, server_id: str, order: list[str]
    ) -> None:
        self._frozen_orders = getattr(self, "_frozen_orders", {})
        self._frozen_orders[server_id] = order

    async def load_frozen_order(self, server_id: str) -> list[str] | None:
        self._frozen_orders = getattr(self, "_frozen_orders", {})
        return self._frozen_orders.get(server_id)


@pytest.fixture
def fake_store() -> FakeLearningStore:
    return FakeLearningStore()


@pytest.fixture
def reranker() -> StatisticalReranker:
    return StatisticalReranker()


@pytest.fixture
def persistence() -> RerankerPersistence:
    return RerankerPersistence()


class TestBootstrap:
    """bootstrap() pre-populates reranker stats from LearningStore."""

    @pytest.mark.asyncio
    async def test_bootstrap_populates_stats(
        self,
        persistence: RerankerPersistence,
        reranker: StatisticalReranker,
        fake_store: FakeLearningStore,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        fake_store.seed_usage([
            ToolUsageRecord(
                tool_name="read_file", server_id="s1", call_count=10, last_called_at=now
            ),
            ToolUsageRecord(
                tool_name="write_file", server_id="s1", call_count=5, last_called_at=now
            ),
        ])

        await persistence.bootstrap(reranker, fake_store, "s1")

        # Reranker should now have stats for both tools
        assert reranker._stats["read_file"].call_count == 10
        assert reranker._stats["write_file"].call_count == 5

    @pytest.mark.asyncio
    async def test_empty_db_leaves_reranker_empty(
        self,
        persistence: RerankerPersistence,
        reranker: StatisticalReranker,
        fake_store: FakeLearningStore,
    ) -> None:
        await persistence.bootstrap(reranker, fake_store, "s1")
        assert len(reranker._stats) == 0

    @pytest.mark.asyncio
    async def test_bootstrapped_reranker_ranks_used_tools_higher(
        self,
        persistence: RerankerPersistence,
        reranker: StatisticalReranker,
        fake_store: FakeLearningStore,
    ) -> None:
        from token_sieve.domain.tool_metadata import ToolMetadata

        now = datetime.now(timezone.utc).isoformat()
        fake_store.seed_usage([
            ToolUsageRecord(
                tool_name="popular_tool", server_id="s1",
                call_count=100, last_called_at=now,
            ),
        ])
        await persistence.bootstrap(reranker, fake_store, "s1")

        tools = [
            ToolMetadata(name="unknown_tool", title=None, description="", input_schema={}),
            ToolMetadata(name="popular_tool", title=None, description="", input_schema={}),
        ]
        reranked = reranker.transform(tools)
        assert reranked[0].name == "popular_tool"


class TestPersistCall:
    """persist_call records tool calls to LearningStore."""

    @pytest.mark.asyncio
    async def test_persist_call_records_to_store(
        self,
        persistence: RerankerPersistence,
        fake_store: FakeLearningStore,
    ) -> None:
        await persistence.persist_call(fake_store, "read_file", "s1")
        assert ("read_file", "s1") in fake_store._calls


class TestPersistCooccurrence:
    """persist_cooccurrence records pairwise co-occurrences."""

    @pytest.mark.asyncio
    async def test_cooccurrence_records_pairs(
        self,
        persistence: RerankerPersistence,
        fake_store: FakeLearningStore,
    ) -> None:
        recent_tools = ["read_file", "write_file", "list_dir"]
        await persistence.persist_cooccurrence(fake_store, recent_tools)

        # Should record all pairs: (read_file,write_file), (read_file,list_dir), (write_file,list_dir)
        assert len(fake_store._cooccurrences) == 3
        pairs = {tuple(sorted(p)) for p in fake_store._cooccurrences}
        assert ("read_file", "write_file") in pairs
        assert ("list_dir", "read_file") in pairs
        assert ("list_dir", "write_file") in pairs

    @pytest.mark.asyncio
    async def test_single_tool_no_cooccurrence(
        self,
        persistence: RerankerPersistence,
        fake_store: FakeLearningStore,
    ) -> None:
        await persistence.persist_cooccurrence(fake_store, ["read_file"])
        assert len(fake_store._cooccurrences) == 0

    @pytest.mark.asyncio
    async def test_empty_list_no_cooccurrence(
        self,
        persistence: RerankerPersistence,
        fake_store: FakeLearningStore,
    ) -> None:
        await persistence.persist_cooccurrence(fake_store, [])
        assert len(fake_store._cooccurrences) == 0


class TestInjectStatsPublicAPI:
    """M19: bootstrap must use inject_stats() instead of private attr mutation."""

    def test_inject_stats_sets_state(self) -> None:
        """inject_stats() must properly set stats, counter, and frozen_order."""
        from token_sieve.adapters.rerank.statistical_reranker import ToolUsageStats

        reranker = StatisticalReranker()
        stats = {"tool_a": ToolUsageStats(call_count=5, last_called_at=0)}
        reranker.inject_stats(stats, call_counter=1, frozen_order=["tool_a"])

        assert reranker._stats == stats
        assert reranker._call_counter == 1
        assert reranker._frozen_order == ["tool_a"]

    @pytest.mark.asyncio
    async def test_bootstrap_uses_inject_stats(self) -> None:
        """bootstrap() should not directly write to _stats, _call_counter, _frozen_order."""
        from unittest.mock import patch

        reranker = StatisticalReranker()
        fake_store = FakeLearningStore()
        fake_store.seed_usage([
            ToolUsageRecord(tool_name="tool_x", server_id="s", call_count=3, last_called_at="t"),
        ])
        await fake_store.save_frozen_order("s", ["tool_x"])

        persistence = RerankerPersistence()

        with patch.object(reranker, "inject_stats", wraps=reranker.inject_stats) as mock_inject:
            await persistence.bootstrap(reranker, fake_store, "s")
            mock_inject.assert_called_once()

        assert "tool_x" in reranker._stats
