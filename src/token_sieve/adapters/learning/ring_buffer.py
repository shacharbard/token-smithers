"""Per-session ring buffer of raw outputs, backed by SQLite + zstd compression.

Decision D5b: store last N raw outputs (default 10) per session, zstd-compressed,
in a dedicated SQLite file separate from the learning store.

On sqlite init failure (OperationalError) falls back to an in-process dict
and logs a WARNING so the audit trail failure is visible but non-fatal.
"""
from __future__ import annotations

import logging
import sqlite3
import os
from pathlib import Path
from typing import Any

import zstandard

logger = logging.getLogger(__name__)

_ZSTD_LEVEL = 3  # fast compression; ring buffer is ephemeral


def _default_db_path() -> str:
    """Return $XDG_STATE_HOME/token-sieve/ring_buffer.db (or ~/.local/state/...)."""
    xdg = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
    path = Path(xdg) / "token-sieve" / "ring_buffer.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _compress(text: str) -> bytes:
    cctx = zstandard.ZstdCompressor(level=_ZSTD_LEVEL)
    return cctx.compress(text.encode("utf-8"))


def _decompress(blob: bytes) -> str:
    dctx = zstandard.ZstdDecompressor()
    return dctx.decompress(blob).decode("utf-8")


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

    Storage is zstd-compressed SQLite blobs, isolated by ``session_id``.
    Falls back to in-process dict storage on SQLite init failure.
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

        resolved_path = db_path if db_path is not None else _default_db_path()
        try:
            conn = sqlite3.connect(resolved_path, check_same_thread=False)
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
        """Compress and store *raw*; evict oldest if over capacity."""
        blob = _compress(raw)
        if self._conn is not None:
            self._conn.execute(
                "INSERT INTO ring_buffer (session_id, blob) VALUES (?, ?)",
                (self._session_id, blob),
            )
            self._conn.commit()
            self._evict()
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

    def _evict(self) -> None:
        """Delete oldest entries for this session beyond capacity."""
        self._conn.execute(  # type: ignore[union-attr]
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
        self._conn.commit()  # type: ignore[union-attr]
