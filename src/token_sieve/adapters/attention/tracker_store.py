"""In-memory bounded AttentionTracker implementation.

Tracks tool result references with time-decayed scoring and bounded storage.
Structurally satisfies the AttentionTracker Protocol.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from token_sieve.domain.attention_score import AttentionScore


@dataclass
class _ToolEntry:
    """Internal mutable tracking state for a single tool."""

    reference_count: int = 0
    last_referenced: float = 0.0


class AttentionTrackerStore:
    """In-memory attention tracker with bounded storage and decay scoring.

    Args:
        max_tools: Maximum number of tools to track. When exceeded,
            the tool with the lowest score is evicted.
    """

    def __init__(self, max_tools: int = 500) -> None:
        self._max_tools = max_tools
        self._entries: dict[str, _ToolEntry] = {}

    def record_reference(self, tool_name: str, session_id: str) -> None:
        """Record that a tool result was referenced."""
        now = time.monotonic()
        entry = self._entries.get(tool_name)
        if entry is None:
            self._entries[tool_name] = _ToolEntry(
                reference_count=1, last_referenced=now
            )
            self._maybe_evict()
        else:
            entry.reference_count += 1
            entry.last_referenced = now

    def get_score(self, tool_name: str) -> AttentionScore | None:
        """Get the attention score for a tool, or None if untracked."""
        entry = self._entries.get(tool_name)
        if entry is None:
            return None
        return self._to_score(tool_name, entry)

    def get_all_scores(self) -> list[AttentionScore]:
        """Get all tracked attention scores."""
        return [
            self._to_score(name, entry)
            for name, entry in self._entries.items()
        ]

    def _to_score(
        self, tool_name: str, entry: _ToolEntry, now: float | None = None
    ) -> AttentionScore:
        """Convert internal entry to AttentionScore with computed decay."""
        if now is None:
            now = time.monotonic()
        elapsed = now - entry.last_referenced
        # Exponential decay: score halves every 300 seconds (5 minutes)
        half_life = 300.0
        decay = math.exp(-0.693 * elapsed / half_life)
        decay_score = entry.reference_count * decay
        return AttentionScore(
            tool_name=tool_name,
            reference_count=entry.reference_count,
            last_referenced=entry.last_referenced,
            decay_score=decay_score,
        )

    def _maybe_evict(self) -> None:
        """Evict the lowest-scoring tool if storage exceeds the cap."""
        if len(self._entries) <= self._max_tools:
            return
        # Use a single timestamp snapshot so all entries are scored fairly.
        now = time.monotonic()
        # Find the tool with the lowest computed score.
        # Tiebreaker: evict the one with the oldest last_referenced.
        worst_name: str | None = None
        worst_key: tuple[float, float] = (float("inf"), float("inf"))
        for name, entry in self._entries.items():
            score = self._to_score(name, entry, now=now)
            key = (score.decay_score, entry.last_referenced)
            if key < worst_key:
                worst_key = key
                worst_name = name
        if worst_name is not None:
            del self._entries[worst_name]
