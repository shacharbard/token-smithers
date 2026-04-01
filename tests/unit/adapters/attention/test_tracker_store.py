"""Tests for AttentionTrackerStore — in-memory bounded implementation."""

from __future__ import annotations

import time

import pytest


class TestAttentionTrackerStoreBasic:
    """Basic record and retrieve operations."""

    def test_record_reference_creates_entry(self) -> None:
        from token_sieve.adapters.attention.tracker_store import (
            AttentionTrackerStore,
        )

        store = AttentionTrackerStore()
        store.record_reference("read_file", "session-1")
        score = store.get_score("read_file")
        assert score is not None
        assert score.tool_name == "read_file"
        assert score.reference_count == 1

    def test_record_reference_increments_count(self) -> None:
        from token_sieve.adapters.attention.tracker_store import (
            AttentionTrackerStore,
        )

        store = AttentionTrackerStore()
        store.record_reference("read_file", "s1")
        store.record_reference("read_file", "s1")
        store.record_reference("read_file", "s2")
        score = store.get_score("read_file")
        assert score is not None
        assert score.reference_count == 3

    def test_get_score_unknown_tool_returns_none(self) -> None:
        from token_sieve.adapters.attention.tracker_store import (
            AttentionTrackerStore,
        )

        store = AttentionTrackerStore()
        assert store.get_score("nonexistent") is None

    def test_get_all_scores_returns_all_tracked(self) -> None:
        from token_sieve.adapters.attention.tracker_store import (
            AttentionTrackerStore,
        )

        store = AttentionTrackerStore()
        store.record_reference("tool_a", "s1")
        store.record_reference("tool_b", "s1")
        store.record_reference("tool_c", "s1")
        scores = store.get_all_scores()
        names = {s.tool_name for s in scores}
        assert names == {"tool_a", "tool_b", "tool_c"}

    def test_get_score_returns_attention_score_type(self) -> None:
        from token_sieve.adapters.attention.tracker_store import (
            AttentionTrackerStore,
        )
        from token_sieve.domain.attention_score import AttentionScore

        store = AttentionTrackerStore()
        store.record_reference("t", "s")
        score = store.get_score("t")
        assert isinstance(score, AttentionScore)


class TestAttentionTrackerStoreDecay:
    """Decay score decreases for older references."""

    def test_decay_score_positive_for_recent(self) -> None:
        from token_sieve.adapters.attention.tracker_store import (
            AttentionTrackerStore,
        )

        store = AttentionTrackerStore()
        store.record_reference("tool", "s1")
        score = store.get_score("tool")
        assert score is not None
        assert score.decay_score > 0.0

    def test_decay_score_monotonically_decreasing(self) -> None:
        """A tool referenced earlier has a lower decay score than one referenced later."""
        from token_sieve.adapters.attention.tracker_store import (
            AttentionTrackerStore,
        )

        store = AttentionTrackerStore()
        store.record_reference("old_tool", "s1")
        # Small sleep to ensure monotonic clock advances
        time.sleep(0.01)
        store.record_reference("new_tool", "s1")

        old_score = store.get_score("old_tool")
        new_score = store.get_score("new_tool")
        assert old_score is not None
        assert new_score is not None
        assert new_score.decay_score >= old_score.decay_score


class TestAttentionTrackerStoreBounded:
    """Bounded storage evicts least-referenced when cap exceeded."""

    def test_default_max_tools(self) -> None:
        from token_sieve.adapters.attention.tracker_store import (
            AttentionTrackerStore,
        )

        store = AttentionTrackerStore()
        assert store._max_tools == 500

    def test_custom_max_tools(self) -> None:
        from token_sieve.adapters.attention.tracker_store import (
            AttentionTrackerStore,
        )

        store = AttentionTrackerStore(max_tools=10)
        assert store._max_tools == 10

    def test_evicts_when_exceeding_cap(self) -> None:
        from token_sieve.adapters.attention.tracker_store import (
            AttentionTrackerStore,
        )

        store = AttentionTrackerStore(max_tools=3)
        # Add 3 tools, boosting "b" and "c" significantly
        store.record_reference("a", "s")
        for _ in range(5):
            store.record_reference("b", "s")
            store.record_reference("c", "s")
        # "a" has count=1, "b" and "c" have count=5
        # Add a 4th tool -- should evict "a" (lowest score)
        store.record_reference("d", "s")

        assert len(store.get_all_scores()) == 3
        assert store.get_score("a") is None
        assert store.get_score("b") is not None
        assert store.get_score("c") is not None
        assert store.get_score("d") is not None

    def test_evicts_correct_tool(self) -> None:
        """When multiple tools have same count, evicts one with oldest reference."""
        from token_sieve.adapters.attention.tracker_store import (
            AttentionTrackerStore,
        )

        store = AttentionTrackerStore(max_tools=2)
        store.record_reference("first", "s")
        time.sleep(0.01)
        store.record_reference("second", "s")
        # Both have count=1, but "first" is older
        time.sleep(0.01)
        store.record_reference("third", "s")

        assert len(store.get_all_scores()) == 2
        assert store.get_score("first") is None


class TestAttentionTrackerStoreProtocol:
    """AttentionTrackerStore structurally satisfies AttentionTracker Protocol."""

    def test_isinstance_attention_tracker(self) -> None:
        from token_sieve.adapters.attention.tracker_store import (
            AttentionTrackerStore,
        )
        from token_sieve.domain.ports_attention import AttentionTracker

        store = AttentionTrackerStore()
        assert isinstance(store, AttentionTracker)
