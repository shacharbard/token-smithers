"""Metrics collection: InMemoryMetricsCollector.

Records CompressionEvents and produces session summaries and strategy breakdowns.
Zero external dependencies -- stdlib only.
"""

from __future__ import annotations

from collections import deque

from token_sieve.domain.model import CompressionEvent

DEFAULT_MAX_EVENTS = 10_000


class InMemoryMetricsCollector:
    """Deque-backed metrics collector for Phase 1.

    Satisfies MetricsCollector Protocol structurally.
    Evicts oldest events when max_events is reached.

    H4 fix: maintains rolling totals (session + per-strategy) that are
    updated incrementally in ``record()``. ``session_summary()`` and
    ``strategy_breakdown()`` are O(1) amortized — they read the rolling
    accumulators and never rescan ``_events``. Eviction is eviction-aware:
    when an event falls off the bounded deque we decrement the totals for
    its contribution and drop empty per-strategy entries.
    """

    def __init__(self, max_events: int = DEFAULT_MAX_EVENTS) -> None:
        self._events: deque[CompressionEvent] = deque(maxlen=max_events)
        # Rolling session totals — updated in record(), decremented on eviction.
        self._total_original: int = 0
        self._total_compressed: int = 0
        # Per-strategy rolling totals, keyed by strategy_name.
        self._strategy_totals: dict[str, dict[str, int]] = {}

    def record(self, event: CompressionEvent) -> None:
        """Record a compression event.

        Maintains O(1) rolling totals. If the bounded deque is full, the
        oldest event is evicted and its contribution is subtracted from the
        totals before the new event's contribution is added.
        """
        # Detect and handle eviction BEFORE the append so we can read the
        # evictee. A full deque with maxlen will drop _events[0] on append.
        if self._events.maxlen is not None and len(self._events) == self._events.maxlen:
            evicted = self._events[0]
            self._subtract(evicted)

        self._events.append(event)
        self._add(event)

    def _add(self, event: CompressionEvent) -> None:
        """Incorporate ``event`` into rolling totals."""
        self._total_original += event.original_tokens
        self._total_compressed += event.compressed_tokens
        bucket = self._strategy_totals.get(event.strategy_name)
        if bucket is None:
            self._strategy_totals[event.strategy_name] = {
                "count": 1,
                "total_original_tokens": event.original_tokens,
                "total_compressed_tokens": event.compressed_tokens,
            }
        else:
            bucket["count"] += 1
            bucket["total_original_tokens"] += event.original_tokens
            bucket["total_compressed_tokens"] += event.compressed_tokens

    def _subtract(self, event: CompressionEvent) -> None:
        """Remove ``event``'s contribution from rolling totals (on eviction)."""
        self._total_original -= event.original_tokens
        self._total_compressed -= event.compressed_tokens
        bucket = self._strategy_totals.get(event.strategy_name)
        if bucket is None:
            return
        bucket["count"] -= 1
        bucket["total_original_tokens"] -= event.original_tokens
        bucket["total_compressed_tokens"] -= event.compressed_tokens
        if bucket["count"] <= 0:
            # Drop empty strategy entries so they don't linger in breakdowns.
            del self._strategy_totals[event.strategy_name]

    def session_summary(self) -> dict:
        """Return totals for the current session (O(1)).

        Keys: total_original_tokens, total_compressed_tokens,
              total_savings_ratio, event_count.
        """
        total_original = self._total_original
        total_compressed = self._total_compressed
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
        """Return per-strategy metrics breakdown (O(strategies), not O(events)).

        Returns dict keyed by strategy_name, each with count,
        total_original_tokens, total_compressed_tokens.
        """
        # Return shallow copies so callers can't mutate our internal buckets.
        return {
            name: dict(bucket) for name, bucket in self._strategy_totals.items()
        }
