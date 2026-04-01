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

    def transform(self, tools: list[ToolMetadata]) -> list[ToolMetadata]:
        """Reorder tools by usage score (most-used first).

        Tools without stats retain their original relative order at the end.
        """
        if not self._stats or not tools:
            return list(tools)

        max_freq = max(s.call_count for s in self._stats.values())
        max_recency = max(s.last_called_at for s in self._stats.values())

        scored: list[tuple[float, int, ToolMetadata]] = []
        unscored: list[ToolMetadata] = []

        for idx, tool in enumerate(tools):
            stats = self._stats.get(tool.name)
            if stats is not None:
                norm_freq = stats.call_count / max_freq if max_freq > 0 else 0.0
                norm_recency = (
                    stats.last_called_at / max_recency if max_recency > 0 else 0.0
                )
                score = (
                    (1 - self._recency_weight) * norm_freq
                    + self._recency_weight * norm_recency
                )
                scored.append((score, idx, tool))
            else:
                unscored.append(tool)

        # Sort scored tools by score descending; stable sort preserves
        # insertion order for equal scores (use negative index as tiebreak).
        scored.sort(key=lambda t: (-t[0], t[1]))

        return [t for _, _, t in scored] + unscored

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
