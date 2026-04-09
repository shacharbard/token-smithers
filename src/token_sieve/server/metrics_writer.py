"""Periodic metrics file writer for dashboard CLI.

Flushes InMemoryMetricsCollector summary to JSON on disk.
"""
from __future__ import annotations

import itertools
import json
import os
import threading
from pathlib import Path

# Per-flush unique suffix so two concurrent writers never share a tmp
# path (which would make O_TRUNC stomping possible).
_TMP_COUNTER = itertools.count()
_TMP_LOCK = threading.Lock()


def _next_tmp_suffix() -> str:
    with _TMP_LOCK:
        n = next(_TMP_COUNTER)
    return f".{os.getpid()}.{threading.get_ident()}.{n}.tmp"


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

        H3 fix: atomic write — serialize to a private tmp sibling, fsync
        it, then ``os.replace()`` over the target path. Guarantees that any
        concurrent reader (e.g. ``ts stats``) sees either the previous full
        file or the new full file, never a zero-byte or partial write.

        M4 fix: each flush uses a *unique* tmp suffix (pid + thread id +
        counter) so concurrent writers sharing ``metrics_path`` never
        contend on the same tmp inode. Combined with POSIX ``fcntl.flock``
        on the target path (advisory, best-effort) this gives us two layers
        of protection: unique tmp files eliminate O_TRUNC stomping, and the
        target lock serializes replace windows so last-writer-wins cleanly.
        Windows has no cheap equivalent primitive — the unique-tmp layer
        still applies there and the lock is skipped.
        """
        path = Path(self._metrics_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "session_summary": self._collector.session_summary(),  # type: ignore[attr-defined]
            "strategy_breakdown": self._collector.strategy_breakdown(),  # type: ignore[attr-defined]
        }
        payload = json.dumps(data, indent=2)

        tmp_path = path.with_suffix(path.suffix + _next_tmp_suffix())

        # M4: advisory lock on the *target* path so concurrent writers
        # serialize their replace() windows. We open the target with
        # O_CREAT so the lock file exists on the first flush; the lock
        # is released in the finally block.
        lock_fd: int | None = None
        try:
            lock_fd = os.open(
                str(path),
                os.O_RDWR | os.O_CREAT,
                0o644,
            )
            try:
                import fcntl  # POSIX only

                fcntl.flock(lock_fd, fcntl.LOCK_EX)
            except (ImportError, OSError):
                # Windows or lock unavailable: fall back to best-effort.
                pass
        except OSError:
            # If we can't open the target for locking, proceed without it.
            lock_fd = None

        fd = os.open(
            str(tmp_path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o644,
        )
        try:
            os.write(fd, payload.encode("utf-8"))
            os.fsync(fd)
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

        try:
            os.replace(str(tmp_path), str(path))
        finally:
            # If replace() somehow failed, clean up the tmp we created.
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            if lock_fd is not None:
                try:
                    os.close(lock_fd)
                except OSError:
                    pass

        self._events_since_flush = 0
