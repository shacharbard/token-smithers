"""Per-session ring buffer of raw outputs, backed by SQLite + optional zstd.

Decision D5b: store last N raw outputs (default 10) per session, compressed
when ``zstandard`` is available, in a dedicated SQLite file separate from
the learning store.

H7 fix:
- All DB operations are guarded by a ``threading.Lock`` so concurrent
  callers never share the underlying ``sqlite3.Connection`` unsynchronized
  (unsynchronized concurrent use of ``check_same_thread=False`` segfaults
  CPython).
- The ``zstandard`` dependency is now optional. If the import fails, the
  buffer stores plain UTF-8 bytes instead. Round-trip still works for
  consumers that treat the blob opaquely.
- File-backed DBs enable WAL mode so readers don't block writers.
- ``append()`` catches ``sqlite3.OperationalError`` and logs+drops — a
  transient disk/IO error must not crash the caller.

On sqlite init failure (OperationalError) falls back to an in-process list
and logs a WARNING so the audit trail failure is visible but non-fatal.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_ZSTD_LEVEL = 3  # fast compression; ring buffer is ephemeral

# H7 fix: zstd is now optional. If the import fails we fall back to plain
# UTF-8 bytes so the buffer still works for audit-trail retrieval.
try:
    import zstandard as _zstandard  # type: ignore[import-not-found]
    _HAS_ZSTD = True
except ImportError:  # pragma: no cover — exercised via monkeypatch in tests
    _zstandard = None  # type: ignore[assignment]
    _HAS_ZSTD = False


def _default_db_path() -> str:
    """Return $XDG_STATE_HOME/token-sieve/ring_buffer.db (or ~/.local/state/...)."""
    xdg = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
    path = Path(xdg) / "token-sieve" / "ring_buffer.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _compress(text: str) -> bytes:
    """Compress *text* with zstd if available, else return UTF-8 bytes."""
    data = text.encode("utf-8")
    # Honor the module-level sentinel so tests can monkeypatch _HAS_ZSTD off.
    import token_sieve.adapters.learning.ring_buffer as _self

    if not _self._HAS_ZSTD or _self._zstandard is None:
        return data
    cctx = _self._zstandard.ZstdCompressor(level=_ZSTD_LEVEL)
    return cctx.compress(data)


def _decompress(blob: bytes) -> str:
    """Decompress *blob* with zstd if available, else decode as UTF-8."""
    import token_sieve.adapters.learning.ring_buffer as _self

    if not _self._HAS_ZSTD or _self._zstandard is None:
        return blob.decode("utf-8")
    try:
        dctx = _self._zstandard.ZstdDecompressor()
        return dctx.decompress(blob).decode("utf-8")
    except Exception:
        # If the blob wasn't zstd-compressed (written under fallback mode),
        # fall through to plain UTF-8.
        return blob.decode("utf-8")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS ring_buffer (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    blob        BLOB    NOT NULL
);
CREATE INDEX IF NOT EXISTS ring_buffer_session ON ring_buffer (session_id, id);
"""


class RingBuffer:
    """Session-scoped ring buffer that stores the last *capacity* raw outputs.

    Storage is zstd-compressed SQLite blobs (or plain UTF-8 when zstd is
    unavailable), isolated by ``session_id``. Falls back to in-process list
    storage on SQLite init failure.

    H7 fix: all DB operations take ``self._lock`` to guarantee thread-safety
    even when the underlying ``sqlite3.Connection`` is shared across threads.
    """

    def __init__(
        self,
        session_id: str,
        capacity: int = 10,
        db_path: str | None = None,
    ) -> None:
        self._session_id = session_id
        self._capacity = capacity
        self._conn: sqlite3.Connection | None = None
        self._fallback: list[bytes] | None = None  # used when sqlite unavailable
        self._lock = threading.Lock()

        resolved_path = db_path if db_path is not None else _default_db_path()
        try:
            conn = sqlite3.connect(resolved_path, check_same_thread=False)
            # H7 fix: enable WAL so concurrent readers don't block writers.
            # In-memory DBs don't support WAL (it's a no-op), so only set it
            # for file-backed connections.
            if resolved_path != ":memory:":
                try:
                    conn.execute("PRAGMA journal_mode=WAL")
                except sqlite3.OperationalError as exc:
                    logger.warning(
                        "ring buffer: failed to enable WAL mode (%s) — continuing",
                        exc,
                    )
            conn.executescript(_SCHEMA)
            conn.commit()
            self._conn = conn
        except sqlite3.OperationalError as exc:
            logger.warning(
                "token_sieve ring buffer: sqlite init failed (%s) — "
                "falling back to ephemeral in-memory storage. "
                "Audit trail will not persist across processes.",
                exc,
            )
            self._fallback = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, raw: str) -> None:
        """Compress and store *raw*; evict oldest if over capacity.

        H7 fix: all SQLite operations are guarded by ``self._lock`` and the
        entire append is wrapped in a ``sqlite3.OperationalError`` guard
        so a transient disk error is logged and dropped instead of crashing
        the caller.
        """
        blob = _compress(raw)
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.execute(
                        "INSERT INTO ring_buffer (session_id, blob) VALUES (?, ?)",
                        (self._session_id, blob),
                    )
                    self._conn.commit()
                    self._evict_locked()
                except sqlite3.OperationalError as exc:
                    logger.warning(
                        "ring buffer: append OperationalError (%s) — dropped entry",
                        exc,
                    )
            else:
                assert self._fallback is not None
                self._fallback.append(blob)
                if len(self._fallback) > self._capacity:
                    self._fallback.pop(0)

    def get(self, n: int = 1) -> str:
        """Return the *n*-th most-recent entry (1 = most recent).

        Raises IndexError if *n* exceeds the number of stored entries.
        """
        if n < 1:
            raise ValueError(f"n must be >= 1, got {n}")

        with self._lock:
            if self._conn is not None:
                rows = self._conn.execute(
                    "SELECT blob FROM ring_buffer WHERE session_id = ? "
                    "ORDER BY id DESC LIMIT ?",
                    (self._session_id, n),
                ).fetchall()
                if len(rows) < n:
                    raise IndexError(
                        f"ring buffer has only {len(rows)} entries, requested index {n}"
                    )
                return _decompress(rows[n - 1][0])
            else:
                assert self._fallback is not None
                count = len(self._fallback)
                if n > count:
                    raise IndexError(
                        f"ring buffer has only {count} entries, requested index {n}"
                    )
                # fallback list is in append order; index from the end
                return _decompress(self._fallback[count - n])

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _evict_locked(self) -> None:
        """Delete oldest entries for this session beyond capacity.

        MUST be called with ``self._lock`` already held (invoked from
        ``append``).
        """
        assert self._conn is not None
        self._conn.execute(
            """
            DELETE FROM ring_buffer
            WHERE session_id = ?
              AND id NOT IN (
                  SELECT id FROM ring_buffer
                  WHERE session_id = ?
                  ORDER BY id DESC
                  LIMIT ?
              )
            """,
            (self._session_id, self._session_id, self._capacity),
        )
        self._conn.commit()
