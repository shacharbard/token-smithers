"""Tests for reranker frozen order persistence round-trip.

Verifies that frozen_order can be persisted to the learning store
and restored on bootstrap, producing identical tool ordering across
proxy restarts.
"""

from __future__ import annotations

import pytest

from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore
from token_sieve.adapters.rerank.reranker_persistence import RerankerPersistence
from token_sieve.adapters.rerank.statistical_reranker import StatisticalReranker
from token_sieve.domain.tool_metadata import ToolMetadata


def _tool(name: str) -> ToolMetadata:
    return ToolMetadata(
        name=name,
        title=None,
        description=f"Tool {name}",
        input_schema={"type": "object"},
    )


class TestFrozenOrderRoundTrip:
    """Freeze reranker, persist, restore, verify identical ordering."""

    @pytest.mark.asyncio
    async def test_frozen_order_round_trip(self, tmp_path) -> None:
        """Freeze, persist, create new reranker, restore, assert same order."""
        db_path = str(tmp_path / "test.db")
        store = await SQLiteLearningStore.connect(db_path)

        try:
            # Session 1: build stats, freeze, persist
            reranker1 = StatisticalReranker()
            reranker1.record_call("alpha")
            reranker1.record_call("alpha")
            reranker1.record_call("beta")
            reranker1.record_call("gamma")

            tools = [_tool("alpha"), _tool("beta"), _tool("gamma")]
            order1 = reranker1.transform(tools)
            order1_names = [t.name for t in order1]

            # Persist frozen order
            assert reranker1.is_frozen
            await store.save_frozen_order("s1", reranker1._frozen_order)

            # Session 2: new reranker, restore frozen order
            reranker2 = StatisticalReranker()
            frozen = await store.load_frozen_order("s1")
            assert frozen is not None
            reranker2._frozen_order = frozen

            order2 = reranker2.transform(tools)
            order2_names = [t.name for t in order2]

            assert order1_names == order2_names
        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_load_frozen_order_missing(self, tmp_path) -> None:
        """load_frozen_order returns None when no order is stored."""
        db_path = str(tmp_path / "test.db")
        store = await SQLiteLearningStore.connect(db_path)

        try:
            result = await store.load_frozen_order("nonexistent")
            assert result is None
        finally:
            await store.close()


class TestBootstrapRestoresFrozenOrder:
    """bootstrap() restores frozen_order from learning store."""

    @pytest.mark.asyncio
    async def test_bootstrap_restores_frozen_order(self, tmp_path) -> None:
        """bootstrap loads frozen_order, not just stats."""
        db_path = str(tmp_path / "test.db")
        store = await SQLiteLearningStore.connect(db_path)

        try:
            # Persist a frozen order
            frozen_order = ["gamma", "alpha", "beta"]
            await store.save_frozen_order("s1", frozen_order)

            # Also record some usage stats
            await store.record_call("alpha", "s1")
            await store.record_call("alpha", "s1")
            await store.record_call("beta", "s1")

            # Bootstrap a new reranker
            reranker = StatisticalReranker()
            persistence = RerankerPersistence()
            await persistence.bootstrap(reranker, store, "s1")

            # Reranker should have the frozen order from persistence
            assert reranker.is_frozen
            assert reranker._frozen_order == frozen_order

            # Transform should use the frozen order
            tools = [_tool("alpha"), _tool("beta"), _tool("gamma")]
            result = reranker.transform(tools)
            assert [t.name for t in result] == frozen_order
        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_bootstrap_without_frozen_order_uses_stats(self, tmp_path) -> None:
        """When no frozen_order is stored, bootstrap only loads stats."""
        db_path = str(tmp_path / "test.db")
        store = await SQLiteLearningStore.connect(db_path)

        try:
            await store.record_call("alpha", "s1")
            await store.record_call("alpha", "s1")
            await store.record_call("beta", "s1")

            reranker = StatisticalReranker()
            persistence = RerankerPersistence()
            await persistence.bootstrap(reranker, store, "s1")

            # Stats loaded but no frozen order
            assert not reranker.is_frozen
            assert len(reranker._stats) == 2
        finally:
            await store.close()
