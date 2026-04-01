"""Tests for StatisticalReranker adapter.

Inherits ToolListTransformerContract and adds specific tests for
frequency+recency scoring, bounded storage, and reset behavior.
"""

from __future__ import annotations

import pytest

from token_sieve.adapters.rerank.statistical_reranker import StatisticalReranker
from token_sieve.domain.ports_rerank import ToolListTransformer
from token_sieve.domain.tool_metadata import ToolMetadata

from tests.unit.adapters.conftest import ToolListTransformerContract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool(name: str) -> ToolMetadata:
    return ToolMetadata(
        name=name,
        title=None,
        description=f"Tool {name}",
        input_schema={"type": "object"},
    )


# ---------------------------------------------------------------------------
# Contract tests (inherited)
# ---------------------------------------------------------------------------


class TestStatisticalRerankerContract(ToolListTransformerContract):
    """StatisticalReranker must pass all ToolListTransformer contract tests."""

    @pytest.fixture()
    def transformer(self):
        return StatisticalReranker()


# ---------------------------------------------------------------------------
# Structural subtyping
# ---------------------------------------------------------------------------


class TestStatisticalRerankerProtocol:
    """StatisticalReranker satisfies the ToolListTransformer Protocol."""

    def test_isinstance_check(self) -> None:
        reranker = StatisticalReranker()
        assert isinstance(reranker, ToolListTransformer)


# ---------------------------------------------------------------------------
# Frequency tracking
# ---------------------------------------------------------------------------


class TestRecordCall:
    """record_call() tracks tool usage."""

    def test_increments_frequency(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("tool-a")
        reranker.record_call("tool-a")
        reranker.record_call("tool-a")
        stats = reranker._stats  # noqa: SLF001
        assert stats["tool-a"].call_count == 3

    def test_tracks_multiple_tools(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("tool-a")
        reranker.record_call("tool-b")
        reranker.record_call("tool-a")
        stats = reranker._stats  # noqa: SLF001
        assert stats["tool-a"].call_count == 2
        assert stats["tool-b"].call_count == 1

    def test_updates_recency(self) -> None:
        """Later calls should have a higher last_called_at counter."""
        reranker = StatisticalReranker()
        reranker.record_call("tool-a")
        first_recency = reranker._stats["tool-a"].last_called_at  # noqa: SLF001
        reranker.record_call("tool-b")
        reranker.record_call("tool-a")
        second_recency = reranker._stats["tool-a"].last_called_at  # noqa: SLF001
        assert second_recency > first_recency


# ---------------------------------------------------------------------------
# Transform ordering
# ---------------------------------------------------------------------------


class TestTransformOrdering:
    """transform() reorders tools by frequency+recency score."""

    def test_most_called_first(self) -> None:
        """Tools with more calls should appear earlier."""
        reranker = StatisticalReranker()
        reranker.record_call("tool-b")
        reranker.record_call("tool-b")
        reranker.record_call("tool-b")
        reranker.record_call("tool-a")

        tools = [_tool("tool-a"), _tool("tool-b"), _tool("tool-c")]
        result = reranker.transform(tools)
        names = [t.name for t in result]
        assert names[0] == "tool-b"
        assert names[1] == "tool-a"

    def test_uncalled_tools_at_end(self) -> None:
        """Tools with no recorded calls should be at the end but not removed."""
        reranker = StatisticalReranker()
        reranker.record_call("tool-a")
        reranker.record_call("tool-a")

        tools = [_tool("tool-c"), _tool("tool-a"), _tool("tool-b")]
        result = reranker.transform(tools)
        names = [t.name for t in result]
        assert names[0] == "tool-a"
        # tool-c and tool-b should be after tool-a (both uncalled)
        assert "tool-c" in names
        assert "tool-b" in names

    def test_preserves_all_tools(self) -> None:
        """transform() must not remove any tools."""
        reranker = StatisticalReranker()
        reranker.record_call("tool-a")

        tools = [_tool("x"), _tool("y"), _tool("z")]
        result = reranker.transform(tools)
        assert {t.name for t in result} == {"x", "y", "z"}

    def test_recency_boosts_ranking(self) -> None:
        """A recently-called tool should rank higher than a tool called
        many times long ago, when counts are close."""
        reranker = StatisticalReranker(recency_weight=0.7)
        # tool-a called once early
        reranker.record_call("tool-a")
        # Pad with many calls to other tools to push recency counter
        for _ in range(20):
            reranker.record_call("tool-filler")
        # tool-b called once recently
        reranker.record_call("tool-b")

        tools = [_tool("tool-a"), _tool("tool-b")]
        result = reranker.transform(tools)
        names = [t.name for t in result]
        # With high recency weight, tool-b (recent) should beat tool-a (old)
        assert names[0] == "tool-b"

    def test_no_calls_preserves_original_order(self) -> None:
        """With no recorded calls, original order is preserved."""
        reranker = StatisticalReranker()
        tools = [_tool("c"), _tool("a"), _tool("b")]
        result = reranker.transform(tools)
        names = [t.name for t in result]
        assert names == ["c", "a", "b"]


# ---------------------------------------------------------------------------
# Bounded storage
# ---------------------------------------------------------------------------


class TestBoundedStorage:
    """Stats storage is bounded by max_tools."""

    def test_default_max_tools(self) -> None:
        reranker = StatisticalReranker()
        assert reranker._max_tools == 500  # noqa: SLF001

    def test_custom_max_tools(self) -> None:
        reranker = StatisticalReranker(max_tools=10)
        assert reranker._max_tools == 10  # noqa: SLF001

    def test_evicts_least_used(self) -> None:
        """When stats exceed max_tools, least-used entries are evicted."""
        reranker = StatisticalReranker(max_tools=3)
        reranker.record_call("tool-a")
        reranker.record_call("tool-a")
        reranker.record_call("tool-b")
        reranker.record_call("tool-b")
        reranker.record_call("tool-c")

        # Now adding a 4th should evict the least-used (tool-c with count=1)
        reranker.record_call("tool-d")
        stats = reranker._stats  # noqa: SLF001
        assert len(stats) <= 3
        assert "tool-d" in stats
        # tool-c had fewest calls, should be evicted
        assert "tool-c" not in stats


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    """reset_stats() clears all tracking data."""

    def test_reset_clears_stats(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("tool-a")
        reranker.record_call("tool-b")
        reranker.reset_stats()
        assert len(reranker._stats) == 0  # noqa: SLF001

    def test_reset_resets_counter(self) -> None:
        """After reset, the monotonic counter restarts."""
        reranker = StatisticalReranker()
        reranker.record_call("tool-a")
        reranker.reset_stats()
        reranker.record_call("tool-b")
        stats = reranker._stats  # noqa: SLF001
        # Counter should be low again (1)
        assert stats["tool-b"].last_called_at == 1


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    """StatisticalReranker constructor parameters."""

    def test_default_recency_weight(self) -> None:
        reranker = StatisticalReranker()
        assert reranker._recency_weight == 0.3  # noqa: SLF001

    def test_custom_recency_weight(self) -> None:
        reranker = StatisticalReranker(recency_weight=0.5)
        assert reranker._recency_weight == 0.5  # noqa: SLF001
