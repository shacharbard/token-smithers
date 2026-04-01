"""Reranker persistence for cross-session bootstrap.

Bridges StatisticalReranker with LearningStore to pre-populate usage
stats from prior sessions and persist new call/co-occurrence data.
"""

from __future__ import annotations

import itertools
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from token_sieve.adapters.rerank.statistical_reranker import StatisticalReranker
    from token_sieve.domain.ports_learning import LearningStore

logger = logging.getLogger(__name__)


class RerankerPersistence:
    """Cross-session persistence bridge for StatisticalReranker.

    - bootstrap(): loads historical usage stats into reranker's _stats dict
    - persist_call(): records a tool call to the LearningStore
    - persist_cooccurrence(): records pairwise co-occurrence for recent tools
    """

    async def bootstrap(
        self,
        reranker: StatisticalReranker,
        learning_store: LearningStore,
        server_id: str,
    ) -> None:
        """Pre-populate reranker from cross-session usage data.

        Loads get_usage_stats() from the LearningStore and injects into
        the reranker's internal _stats dict. If no data exists (cold start),
        the reranker starts empty -- Phase 03 behavior.
        """
        from token_sieve.adapters.rerank.statistical_reranker import ToolUsageStats

        try:
            records = await learning_store.get_usage_stats(server_id)
        except Exception:
            logger.debug("bootstrap: failed to load usage stats", exc_info=True)
            return

        if not records:
            return

        # Pre-populate reranker stats from historical data
        for record in records:
            reranker._stats[record.tool_name] = ToolUsageStats(
                call_count=record.call_count,
                last_called_at=reranker._call_counter,
            )
            # Advance counter so each tool gets a unique recency value
            reranker._call_counter += 1

    async def persist_call(
        self,
        learning_store: LearningStore,
        tool_name: str,
        server_id: str,
    ) -> None:
        """Record a tool call to the LearningStore for future sessions."""
        try:
            await learning_store.record_call(tool_name, server_id)
        except Exception:
            logger.debug("persist_call: failed to record", exc_info=True)

    async def persist_cooccurrence(
        self,
        learning_store: LearningStore,
        recent_tools: list[str],
    ) -> None:
        """Record pairwise co-occurrence for a sliding window of recent tools.

        Given tools [A, B, C], records pairs: (A,B), (A,C), (B,C).
        """
        if len(recent_tools) < 2:
            return

        try:
            for tool_a, tool_b in itertools.combinations(recent_tools, 2):
                await learning_store.record_cooccurrence(tool_a, tool_b)
        except Exception:
            logger.debug("persist_cooccurrence: failed to record", exc_info=True)
