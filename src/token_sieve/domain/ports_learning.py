"""LearningStore port interface (Protocol class).

Defines the contract for cross-session persistence of tool usage,
result caching, compression metrics, and co-occurrence patterns.
Zero external dependencies -- stdlib-only imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from token_sieve.domain.learning_types import (
        CooccurrenceRecord,
        PipelineConfig,
        ToolUsageRecord,
    )
    from token_sieve.domain.model import CompressionEvent


@runtime_checkable
class LearningStore(Protocol):
    """Interface for cross-session learning persistence.

    Implementations record tool usage, cache results, track compression
    metrics, and store co-occurrence patterns. All methods are async to
    support non-blocking I/O (e.g., SQLite via aiosqlite).
    """

    async def record_call(self, tool_name: str, server_id: str) -> None:
        """Record a tool call for usage statistics."""
        ...

    async def get_usage_stats(self, server_id: str) -> list[ToolUsageRecord]:
        """Get usage statistics for all tools on a server."""
        ...

    async def cache_result(
        self, tool_name: str, args_normalized: str, result: str
    ) -> None:
        """Cache a tool result for later similarity lookup."""
        ...

    async def lookup_similar(
        self, tool_name: str, args_normalized: str, threshold: float
    ) -> str | None:
        """Look up a cached result by tool name and normalized args.

        Returns the cached result text if a match is found above the
        similarity threshold, or None otherwise.
        """
        ...

    async def record_compression_event(
        self, session_id: str, event: CompressionEvent, tool_name: str
    ) -> None:
        """Record a compression event for auto-tuning analytics."""
        ...

    async def record_cooccurrence(self, tool_a: str, tool_b: str) -> None:
        """Record that two tools were called together in a session."""
        ...

    async def get_cooccurrence(self, tool_name: str) -> list[CooccurrenceRecord]:
        """Get co-occurrence records for a tool."""
        ...

    async def get_pipeline_config(
        self, tool_name: str, server_id: str
    ) -> PipelineConfig | None:
        """Get per-tool pipeline configuration, or None if not yet stored."""
        ...

    async def save_pipeline_config(self, config: PipelineConfig) -> None:
        """Upsert per-tool pipeline configuration."""
        ...

    async def increment_regret_streak(
        self, tool_name: str, server_id: str
    ) -> int:
        """Increment regret streak counter, return new value."""
        ...

    async def reset_regret_streak(
        self, tool_name: str, server_id: str
    ) -> None:
        """Reset regret streak counter to zero."""
        ...

    async def save_frozen_order(
        self, server_id: str, order: list[str]
    ) -> None:
        """Persist reranker frozen tool order for a server."""
        ...

    async def load_frozen_order(self, server_id: str) -> list[str] | None:
        """Load persisted frozen tool order, or None if not stored."""
        ...

    async def get_session_report(self, session_id: str) -> dict:
        """Get per-tool and per-strategy breakdowns for a session."""
        ...

    async def get_cross_server_stats(self) -> list[dict]:
        """Get per-tool aggregation across all compression events."""
        ...

    async def get_adapter_effectiveness(self, limit: int = 10) -> list[dict]:
        """Get strategies ranked by total tokens saved (descending)."""
        ...

    async def get_savings_trend(self, sessions: int = 10) -> list[dict]:
        """Get session-level rollups for the last N sessions."""
        ...

    async def get_suggestion_candidates(self, session_id: str) -> list[dict]:
        """Get CLAUDE.md suggestion candidates based on session patterns."""
        ...
