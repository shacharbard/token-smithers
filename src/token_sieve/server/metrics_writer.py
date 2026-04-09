"""Periodic metrics file writer for dashboard CLI.

Flushes InMemoryMetricsCollector summary to JSON on disk.
"""
from __future__ import annotations

import json
import os
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
        flush_every_n: int = 1,
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
        """Write current metrics summary to disk as JSON.

        H3 fix: atomic write — serialize to a sibling ``.tmp`` file, fsync
        it, then ``os.replace()`` over the target path. This guarantees that
        any concurrent reader (e.g. ``ts stats``) sees either the previous
        full file or the new full file, never a zero-byte or partial write.

        M4 fix: take an exclusive ``fcntl.flock`` on the tmp file on POSIX so
        concurrent proxies serialize their atomic-write windows. Windows has
        no equivalent cheap primitive here — we skip the lock there and
        document the limitation.
        """
        path = Path(self._metrics_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "session_summary": self._collector.session_summary(),  # type: ignore[attr-defined]
            "strategy_breakdown": self._collector.strategy_breakdown(),  # type: ignore[attr-defined]
        }
        payload = json.dumps(data, indent=2)

        tmp_path = path.with_suffix(path.suffix + ".tmp")
        # Open the tmp file and hold it until after replace so the flock
        # (POSIX) remains valid across the rename.
        fd = os.open(
            str(tmp_path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o644,
        )
        try:
            # M4: POSIX advisory lock so concurrent proxies don't stomp.
            try:
                import fcntl  # POSIX only

                fcntl.flock(fd, fcntl.LOCK_EX)
            except (ImportError, OSError):
                # Windows or lock unavailable: fall back to best-effort.
                pass

            os.write(fd, payload.encode("utf-8"))
            os.fsync(fd)
            os.replace(str(tmp_path), str(path))
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
            # If replace() failed, the tmp file may still exist — remove it.
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

        self._events_since_flush = 0
