"""Metrics collection: InMemoryMetricsCollector.

Records CompressionEvents and produces session summaries and strategy breakdowns.
Zero external dependencies -- stdlib only.
"""

from __future__ import annotations

from token_sieve.domain.model import CompressionEvent


class InMemoryMetricsCollector:
    """List-backed metrics collector for Phase 1.

    Satisfies MetricsCollector Protocol structurally.
    """

    def __init__(self) -> None:
        self._events: list[CompressionEvent] = []

    def record(self, event: CompressionEvent) -> None:
        """Record a compression event."""
        self._events.append(event)

    def session_summary(self) -> dict:
        """Return totals for the current session.

        Keys: total_original_tokens, total_compressed_tokens,
              total_savings_ratio, event_count.
        """
        total_original = sum(e.original_tokens for e in self._events)
        total_compressed = sum(e.compressed_tokens for e in self._events)
        if total_original == 0:
            savings = 0.0
        else:
            savings = 1.0 - (total_compressed / total_original)

        return {
            "total_original_tokens": total_original,
            "total_compressed_tokens": total_compressed,
            "total_savings_ratio": savings,
            "event_count": len(self._events),
        }

    def strategy_breakdown(self) -> dict:
        """Return per-strategy metrics breakdown.

        Returns dict keyed by strategy_name, each with count,
        total_original_tokens, total_compressed_tokens.
        """
        breakdown: dict[str, dict] = {}
        for event in self._events:
            name = event.strategy_name
            if name not in breakdown:
                breakdown[name] = {
                    "count": 0,
                    "total_original_tokens": 0,
                    "total_compressed_tokens": 0,
                }
            breakdown[name]["count"] += 1
            breakdown[name]["total_original_tokens"] += event.original_tokens
            breakdown[name]["total_compressed_tokens"] += event.compressed_tokens
        return breakdown
