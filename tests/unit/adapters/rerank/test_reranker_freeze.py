"""Tests for StatisticalReranker freeze/unfreeze session stability.

Verifies that once the reranker freezes its tool order (on first transform()),
subsequent calls return identical order regardless of record_call() changes.
This enables Anthropic prompt cache hits on tool definitions.
"""

from __future__ import annotations

import pytest

from token_sieve.adapters.rerank.statistical_reranker import StatisticalReranker
from token_sieve.domain.tool_metadata import ToolMetadata


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
# Freeze stability
# ---------------------------------------------------------------------------


class TestFreezeOnFirstTransform:
    """After first transform(), order is locked for the session."""

    def test_second_transform_identical_after_record_call(self) -> None:
        """transform() returns identical order even after record_call() changes stats."""
        reranker = StatisticalReranker()
        reranker.record_call("alpha")
        reranker.record_call("alpha")
        reranker.record_call("beta")

        tools = [_tool("alpha"), _tool("beta"), _tool("gamma")]

        first = reranker.transform(tools)

        # Mutate stats -- beta becomes most-called
        reranker.record_call("beta")
        reranker.record_call("beta")
        reranker.record_call("beta")

        second = reranker.transform(tools)

        assert [t.name for t in first] == [t.name for t in second]

    def test_many_transforms_all_identical(self) -> None:
        """10 consecutive transforms after freeze all return same order."""
        reranker = StatisticalReranker()
        reranker.record_call("x")
        reranker.record_call("y")

        tools = [_tool("x"), _tool("y"), _tool("z")]
        first = reranker.transform(tools)
        first_names = [t.name for t in first]

        for _ in range(10):
            reranker.record_call("z")  # z is now most-called
            result = reranker.transform(tools)
            assert [t.name for t in result] == first_names


# ---------------------------------------------------------------------------
# Stats still accumulate after freeze
# ---------------------------------------------------------------------------


class TestStatsAccumulateAfterFreeze:
    """record_call() after freeze still updates _stats for persistence."""

    def test_record_call_after_freeze_increments_stats(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("alpha")

        tools = [_tool("alpha"), _tool("beta")]
        reranker.transform(tools)  # triggers freeze

        # Stats before
        count_before = reranker._stats["alpha"].call_count

        reranker.record_call("alpha")

        assert reranker._stats["alpha"].call_count == count_before + 1

    def test_new_tool_stats_tracked_after_freeze(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("alpha")

        tools = [_tool("alpha")]
        reranker.transform(tools)  # triggers freeze

        reranker.record_call("new_tool")

        assert "new_tool" in reranker._stats
        assert reranker._stats["new_tool"].call_count == 1


# ---------------------------------------------------------------------------
# New tools appended at end in stable position
# ---------------------------------------------------------------------------


class TestNewToolsAppendedAtEnd:
    """Tools not in _frozen_order appear at the end, preserving input order."""

    def test_new_tools_at_end(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("alpha")
        reranker.record_call("beta")

        original_tools = [_tool("alpha"), _tool("beta")]
        reranker.transform(original_tools)  # freeze with [alpha, beta]

        # Now add new tools to the input list
        extended_tools = [
            _tool("alpha"),
            _tool("new_one"),
            _tool("beta"),
            _tool("new_two"),
        ]
        result = reranker.transform(extended_tools)
        names = [t.name for t in result]

        # Frozen tools keep their frozen order, new ones at end in input order
        assert names.index("alpha") < names.index("new_one")
        assert names.index("beta") < names.index("new_one")
        assert names.index("new_one") < names.index("new_two")

    def test_new_tools_stable_across_calls(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("alpha")

        reranker.transform([_tool("alpha")])  # freeze

        extended = [_tool("alpha"), _tool("x"), _tool("y")]
        first = [t.name for t in reranker.transform(extended)]
        second = [t.name for t in reranker.transform(extended)]

        assert first == second


# ---------------------------------------------------------------------------
# Unfreeze allows recomputation
# ---------------------------------------------------------------------------


class TestUnfreeze:
    """unfreeze() resets _frozen_order, allowing recomputation on next transform()."""

    def test_unfreeze_allows_new_order(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("alpha")
        reranker.record_call("alpha")
        reranker.record_call("beta")

        tools = [_tool("alpha"), _tool("beta"), _tool("gamma")]
        first = reranker.transform(tools)

        # Make beta dominant
        for _ in range(10):
            reranker.record_call("beta")

        reranker.unfreeze()
        after_unfreeze = reranker.transform(tools)

        # beta should now be first because it has far more calls
        assert after_unfreeze[0].name == "beta"
        # The order should differ from the frozen one
        assert [t.name for t in after_unfreeze] != [t.name for t in first]

    def test_unfreeze_resets_frozen_order(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("alpha")
        reranker.transform([_tool("alpha")])

        assert reranker.is_frozen is True

        reranker.unfreeze()

        assert reranker.is_frozen is False
        assert reranker._frozen_order is None


# ---------------------------------------------------------------------------
# Explicit freeze()
# ---------------------------------------------------------------------------


class TestExplicitFreeze:
    """freeze() locks the current computed order without needing a tool list."""

    def test_freeze_sets_frozen_order(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("alpha")
        reranker.record_call("alpha")
        reranker.record_call("beta")

        reranker.freeze()

        assert reranker.is_frozen is True

    def test_freeze_then_transform_uses_frozen(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("alpha")
        reranker.record_call("alpha")
        reranker.record_call("beta")

        reranker.freeze()

        # Make beta dominant
        for _ in range(10):
            reranker.record_call("beta")

        tools = [_tool("alpha"), _tool("beta"), _tool("gamma")]
        result = reranker.transform(tools)

        # alpha should still be first because freeze captured original order
        assert result[0].name == "alpha"


# ---------------------------------------------------------------------------
# is_frozen property
# ---------------------------------------------------------------------------


class TestIsFrozenProperty:
    """is_frozen reflects the freeze state."""

    def test_not_frozen_initially(self) -> None:
        reranker = StatisticalReranker()
        assert reranker.is_frozen is False

    def test_frozen_after_first_transform(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("alpha")
        reranker.transform([_tool("alpha")])
        assert reranker.is_frozen is True

    def test_frozen_after_explicit_freeze(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("alpha")
        reranker.freeze()
        assert reranker.is_frozen is True

    def test_not_frozen_after_unfreeze(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("alpha")
        reranker.transform([_tool("alpha")])
        reranker.unfreeze()
        assert reranker.is_frozen is False


# ---------------------------------------------------------------------------
# Edge cases: cold start, single tool, max_tools boundary
# ---------------------------------------------------------------------------


class TestColdStartFreeze:
    """When reranker has no stats (cold start), first transform() freezes input order."""

    def test_cold_start_freezes_input_order(self) -> None:
        reranker = StatisticalReranker()
        tools = [_tool("c"), _tool("a"), _tool("b")]

        result = reranker.transform(tools)

        # With no stats, input order is preserved and frozen
        assert [t.name for t in result] == ["c", "a", "b"]
        assert reranker.is_frozen is True
        assert reranker._frozen_order == ["c", "a", "b"]

    def test_cold_start_frozen_order_stable(self) -> None:
        reranker = StatisticalReranker()
        tools = [_tool("c"), _tool("a"), _tool("b")]

        first = reranker.transform(tools)

        # Record calls after freeze -- should not change order
        reranker.record_call("b")
        reranker.record_call("b")
        reranker.record_call("b")

        second = reranker.transform(tools)
        assert [t.name for t in first] == [t.name for t in second]


class TestSingleToolFreeze:
    """Freeze works correctly with a single tool."""

    def test_single_tool_freezes(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("only")

        result = reranker.transform([_tool("only")])
        assert [t.name for t in result] == ["only"]
        assert reranker.is_frozen is True

    def test_single_tool_cold_start(self) -> None:
        reranker = StatisticalReranker()
        result = reranker.transform([_tool("only")])
        assert [t.name for t in result] == ["only"]
        assert reranker.is_frozen is True


class TestMaxToolsBoundaryFreeze:
    """Freeze works at the max_tools boundary (500+ tools)."""

    def test_freeze_with_many_tools(self) -> None:
        reranker = StatisticalReranker(max_tools=500)

        # Record calls for 500 tools
        for i in range(500):
            reranker.record_call(f"tool_{i:04d}")

        tools = [_tool(f"tool_{i:04d}") for i in range(500)]
        # Add some beyond max
        tools.extend([_tool(f"extra_{i}") for i in range(10)])

        first = reranker.transform(tools)
        first_names = [t.name for t in first]

        # Record more calls after freeze
        for i in range(10):
            reranker.record_call(f"extra_{i}")

        second = reranker.transform(tools)
        second_names = [t.name for t in second]

        assert first_names == second_names
        assert len(first_names) == 510

    def test_empty_tool_list(self) -> None:
        reranker = StatisticalReranker()
        reranker.record_call("alpha")

        result = reranker.transform([])
        assert result == []
        # Empty list should not freeze
        assert reranker.is_frozen is False


# ---------------------------------------------------------------------------
# cache_aligned auto-freeze
# ---------------------------------------------------------------------------


class TestCacheAlignedAutoFreeze:
    """When cache_aligned=True, reranker auto-freezes after first transform with stats."""

    def test_cache_aligned_auto_freeze(self) -> None:
        """cache_aligned=True causes freeze after first transform() with stats."""
        reranker = StatisticalReranker()
        reranker.set_cache_aligned(True)
        reranker.record_call("alpha")
        reranker.record_call("beta")

        tools = [_tool("alpha"), _tool("beta"), _tool("gamma")]
        result1 = reranker.transform(tools)

        assert reranker.is_frozen is True

        # Mutate stats -- should NOT affect order because frozen
        for _ in range(10):
            reranker.record_call("gamma")

        result2 = reranker.transform(tools)
        assert [t.name for t in result1] == [t.name for t in result2]

    def test_cache_aligned_no_stats_still_freezes(self) -> None:
        """cache_aligned=True with no stats freezes on cold start."""
        reranker = StatisticalReranker()
        reranker.set_cache_aligned(True)

        tools = [_tool("x"), _tool("y")]
        reranker.transform(tools)

        assert reranker.is_frozen is True

    def test_cache_aligned_false_does_not_auto_freeze(self) -> None:
        """cache_aligned=False (default) does NOT change existing freeze behavior."""
        reranker = StatisticalReranker()
        # Default is False
        reranker.record_call("alpha")

        tools = [_tool("alpha")]
        reranker.transform(tools)

        # transform() already freezes by default (existing behavior)
        assert reranker.is_frozen is True

    def test_cache_aligned_only_freezes_once(self) -> None:
        """Auto-freeze fires on first transform, not on every subsequent one."""
        reranker = StatisticalReranker()
        reranker.set_cache_aligned(True)
        reranker.record_call("alpha")

        tools = [_tool("alpha"), _tool("beta")]
        reranker.transform(tools)
        frozen_order_1 = list(reranker._frozen_order)

        # Unfreeze and add new stats
        reranker.unfreeze()
        reranker.record_call("beta")
        reranker.record_call("beta")
        reranker.record_call("beta")

        # Second transform should re-freeze with new stats
        reranker.transform(tools)
        assert reranker.is_frozen is True
