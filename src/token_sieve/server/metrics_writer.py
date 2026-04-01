"""Periodic metrics file writer for dashboard CLI.

Flushes InMemoryMetricsCollector summary to JSON on disk.
"""
from __future__ import annotations

import json
from pathlib import Path


class MetricsFileWriter:
    """Write metrics collector summary to JSON file periodically.

    Flushes after every ``flush_every_n`` events recorded via
    ``record_and_maybe_flush()``, or on explicit ``flush()`` calls.
    """

    def __init__(
        self,
        collector: object,
        metrics_path: str,
        flush_every_n: int = 10,
    ) -> None:
        self._collector = collector
        self._metrics_path = metrics_path
        self._flush_every_n = flush_every_n
        self._events_since_flush = 0

    def record_and_maybe_flush(self, event: object) -> None:
        """Record event to collector and flush if threshold reached."""
        self._collector.record(event)  # type: ignore[attr-defined]
        self._events_since_flush += 1
        if self._events_since_flush >= self._flush_every_n:
            self.flush()

    def flush(self) -> None:
        """Write current metrics summary to disk as JSON."""
        path = Path(self._metrics_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "session_summary": self._collector.session_summary(),  # type: ignore[attr-defined]
            "strategy_breakdown": self._collector.strategy_breakdown(),  # type: ignore[attr-defined]
        }
        path.write_text(json.dumps(data, indent=2))
        self._events_since_flush = 0
