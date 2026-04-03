"""StatisticalReranker -- usage-based tool list reordering.

Tracks call frequency and recency per tool, then reorders tools/list
responses so that frequently and recently used tools appear first.
Tools that have never been called are moved to the end but never removed.

Bounded storage: stats are capped at max_tools entries. When the cap is
exceeded, the least-used entry is evicted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from token_sieve.domain.tool_metadata import ToolMetadata


@dataclass
class ToolUsageStats:
    """Per-tool usage statistics."""

    call_count: int = 0
    last_called_at: int = 0


class StatisticalReranker:
    """Reranks tool lists by frequency + recency score.

    Implements the ToolListTransformer Protocol.

    Score = (1 - recency_weight) * normalized_frequency
            + recency_weight * normalized_recency

    Tools not in stats receive score 0 and retain their original order
    at the end of the list.
    """

    def __init__(
        self,
        max_tools: int = 500,
        recency_weight: float = 0.3,
    ) -> None:
        self._max_tools = max_tools
        self._recency_weight = recency_weight
        self._stats: dict[str, ToolUsageStats] = {}
        self._call_counter: int = 0
        self._frozen_order: list[str] | None = None

    def record_call(self, tool_name: str) -> None:
        """Record that a tool was called."""
        self._call_counter += 1

        if tool_name in self._stats:
            entry = self._stats[tool_name]
            entry.call_count += 1
            entry.last_called_at = self._call_counter
        else:
            self._stats[tool_name] = ToolUsageStats(
                call_count=1,
                last_called_at=self._call_counter,
            )
            self._evict_if_needed()

    @property
    def is_frozen(self) -> bool:
        """Whether the tool order is currently frozen."""
        return self._frozen_order is not None

    def freeze(self) -> None:
        """Freeze the current computed order from stats.

        Sets ``_frozen_order`` to the tool name ranking derived from current
        stats. Subsequent ``transform()`` calls will use this order instead of
        recomputing.
        """
        if not self._stats:
            return
        self._frozen_order = self._ranked_names_from_stats()

    def unfreeze(self) -> None:
        """Reset frozen order, allowing recomputation on next transform()."""
        self._frozen_order = None

    def transform(self, tools: list[ToolMetadata]) -> list[ToolMetadata]:
        """Reorder tools by usage score (most-used first).

        On the first call, computes the order and freezes it. Subsequent calls
        return tools in the frozen order. Tools not in the frozen order are
        appended at the end, preserving their relative input order.
        """
        if not tools:
            return list(tools)

        # If frozen, apply the frozen order
        if self._frozen_order is not None:
            return self._apply_frozen_order(tools)

        # No stats: freeze input order as-is (cold start)
        if not self._stats:
            self._frozen_order = [t.name for t in tools]
            return list(tools)

        # Compute order from stats
        computed = self._compute_order(tools)
        self._frozen_order = [t.name for t in computed]
        return computed

    def _ranked_names_from_stats(self) -> list[str]:
        """Compute a ranked list of tool names from current stats."""
        max_freq = max(s.call_count for s in self._stats.values())
        max_recency = max(s.last_called_at for s in self._stats.values())

        scored: list[tuple[float, str]] = []
        for name, stats in self._stats.items():
            score = self._score(stats, max_freq, max_recency)
            scored.append((score, name))
        scored.sort(key=lambda t: -t[0])
        return [name for _, name in scored]

    def _score(
        self,
        stats: ToolUsageStats,
        max_freq: int,
        max_recency: int,
    ) -> float:
        """Compute combined frequency+recency score for a single tool."""
        norm_freq = stats.call_count / max_freq if max_freq > 0 else 0.0
        norm_recency = (
            stats.last_called_at / max_recency if max_recency > 0 else 0.0
        )
        return (
            (1 - self._recency_weight) * norm_freq
            + self._recency_weight * norm_recency
        )

    def _compute_order(self, tools: list[ToolMetadata]) -> list[ToolMetadata]:
        """Compute tool order from current stats (unfrozen logic)."""
        max_freq = max(s.call_count for s in self._stats.values())
        max_recency = max(s.last_called_at for s in self._stats.values())

        scored: list[tuple[float, int, ToolMetadata]] = []
        unscored: list[ToolMetadata] = []

        for idx, tool in enumerate(tools):
            stats = self._stats.get(tool.name)
            if stats is not None:
                score = self._score(stats, max_freq, max_recency)
                scored.append((score, idx, tool))
            else:
                unscored.append(tool)

        scored.sort(key=lambda t: (-t[0], t[1]))
        return [t for _, _, t in scored] + unscored

    def _apply_frozen_order(self, tools: list[ToolMetadata]) -> list[ToolMetadata]:
        """Reorder tools according to the frozen order.

        Tools in the frozen order are placed first (in frozen order).
        Tools not in the frozen order are appended at the end, preserving
        their relative input order.
        """
        frozen_set = set(self._frozen_order)  # type: ignore[arg-type]
        tool_by_name: dict[str, ToolMetadata] = {t.name: t for t in tools}
        input_names = {t.name for t in tools}

        result: list[ToolMetadata] = []
        # Add frozen tools that are present in input, in frozen order
        for name in self._frozen_order:  # type: ignore[union-attr]
            if name in input_names:
                result.append(tool_by_name[name])

        # Add non-frozen tools in their original input order
        for tool in tools:
            if tool.name not in frozen_set:
                result.append(tool)

        return result

    def reset_stats(self) -> None:
        """Clear all usage tracking data."""
        self._stats.clear()
        self._call_counter = 0

    def _evict_if_needed(self) -> None:
        """If stats exceed max_tools, evict the least-used entry."""
        while len(self._stats) > self._max_tools:
            # Find the entry with the lowest call_count
            least_used = min(self._stats, key=lambda k: self._stats[k].call_count)
            del self._stats[least_used]
