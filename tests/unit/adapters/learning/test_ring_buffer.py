"""RED tests for RingBuffer — Task 1 of 09-01 CLI Compressor Foundation.

All tests in this file are written BEFORE production code (TDD RED phase).
"""
from __future__ import annotations

import logging
import sqlite3
from unittest.mock import patch

import pytest
import zstandard

from token_sieve.adapters.learning.ring_buffer import RingBuffer


class TestRingBuffer:
    """Unit tests for the session-scoped ring buffer of raw outputs."""

    # ------------------------------------------------------------------
    # test_append_stores_zstd_compressed_blob
    # ------------------------------------------------------------------
    def test_append_stores_zstd_compressed_blob(self, tmp_path):
        """append() stores zstd-compressed data; round-trip yields original."""
        buf = RingBuffer(session_id="s1", capacity=10, db_path=str(tmp_path / "rb.db"))
        buf.append("hello")

        raw = buf.get(1)
        assert raw == "hello"

    # ------------------------------------------------------------------
    # test_capacity_evicts_oldest
    # ------------------------------------------------------------------
    def test_capacity_evicts_oldest(self, tmp_path):
        """Capacity=10: appending 12 items evicts the two oldest."""
        buf = RingBuffer(session_id="s1", capacity=10, db_path=str(tmp_path / "rb.db"))
        for i in range(12):
            buf.append(f"item-{i}")

        # Should only hold items 2..11 (last 10)
        entries = [buf.get(n) for n in range(1, 11)]
        assert entries == [f"item-{i}" for i in range(11, 1, -1)]

    # ------------------------------------------------------------------
    # test_get_by_index_default_returns_most_recent
    # ------------------------------------------------------------------
    def test_get_by_index_default_returns_most_recent(self, tmp_path):
        """get() with no argument returns the most recently appended item."""
        buf = RingBuffer(session_id="s1", capacity=10, db_path=str(tmp_path / "rb.db"))
        buf.append("first")
        buf.append("second")
        buf.append("third")

        assert buf.get() == "third"

    # ------------------------------------------------------------------
    # test_get_by_index_n_returns_nth_from_end
    # ------------------------------------------------------------------
    def test_get_by_index_n_returns_nth_from_end(self, tmp_path):
        """get(2) returns the second-most-recent entry."""
        buf = RingBuffer(session_id="s1", capacity=10, db_path=str(tmp_path / "rb.db"))
        buf.append("a")
        buf.append("b")
        buf.append("c")

        assert buf.get(1) == "c"
        assert buf.get(2) == "b"
        assert buf.get(3) == "a"

    # ------------------------------------------------------------------
    # test_session_scoped_isolation
    # ------------------------------------------------------------------
    def test_session_scoped_isolation(self, tmp_path):
        """Two RingBuffer instances with different session_ids see no shared data."""
        db = str(tmp_path / "rb.db")
        buf_a = RingBuffer(session_id="session-A", capacity=10, db_path=db)
        buf_b = RingBuffer(session_id="session-B", capacity=10, db_path=db)

        buf_a.append("from-A")
        buf_b.append("from-B")

        assert buf_a.get() == "from-A"
        assert buf_b.get() == "from-B"

        # buf_a should have exactly 1 entry; buf_b same
        with pytest.raises(IndexError):
            buf_a.get(2)
        with pytest.raises(IndexError):
            buf_b.get(2)

    # ------------------------------------------------------------------
    # test_corrupted_store_fallback
    # ------------------------------------------------------------------
    def test_corrupted_store_fallback(self, tmp_path, caplog):
        """If sqlite init raises OperationalError, fall back to in-memory dict + warn."""
        with caplog.at_level(logging.WARNING, logger="token_sieve.adapters.learning.ring_buffer"):
            with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("corrupted")):
                buf = RingBuffer(session_id="s1", capacity=10, db_path=str(tmp_path / "rb.db"))

        # Should still work via in-memory fallback
        buf.append("fallback-data")
        assert buf.get() == "fallback-data"

        # Warning must have been logged
        assert any("ring buffer" in record.message.lower() or "fallback" in record.message.lower()
                   for record in caplog.records)


class TestRingBufferHardening:
    """H7 fix: thread-safety, optional zstd, WAL mode, resilience to OperationalError."""

    def test_concurrent_appends_from_multiple_threads(self, tmp_path):
        """Many threads appending concurrently must not raise and must preserve entries.

        Run in a subprocess because concurrent unsynchronized access to a
        Python sqlite3 Connection with check_same_thread=False can segfault
        the interpreter — subprocess isolation ensures a segfault fails the
        test cleanly rather than tearing down the whole pytest runner.
        """
        import subprocess
        import sys
        import textwrap

        db = str(tmp_path / "rb-concurrent.db")
        script = textwrap.dedent(
            f"""
            import threading, sqlite3, sys
            from token_sieve.adapters.learning.ring_buffer import RingBuffer
            buf = RingBuffer(session_id="concurrent", capacity=200, db_path={db!r})
            errors = []
            N_THREADS, PER_THREAD = 8, 20
            def worker(tid):
                try:
                    for i in range(PER_THREAD):
                        buf.append(f"t{{tid}}-i{{i}}")
                except Exception as exc:
                    errors.append(exc)
            ts = [threading.Thread(target=worker, args=(t,)) for t in range(N_THREADS)]
            for t in ts: t.start()
            for t in ts: t.join()
            if errors:
                print("ERRORS:", errors, file=sys.stderr)
                sys.exit(2)
            conn = sqlite3.connect({db!r})
            row = conn.execute(
                "SELECT COUNT(*) FROM ring_buffer WHERE session_id = 'concurrent'"
            ).fetchone()
            conn.close()
            if row[0] != N_THREADS * PER_THREAD:
                print(f"EXPECTED {{N_THREADS * PER_THREAD}} GOT {{row[0]}}", file=sys.stderr)
                sys.exit(3)
            sys.exit(0)
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"Concurrent append subprocess failed with rc={result.returncode}: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_zstd_import_failure_falls_back_to_plain_bytes(self, tmp_path, monkeypatch):
        """H7 fix: zstd must be optional. If import fails, use plain UTF-8 bytes.

        The current module unconditionally imports `zstandard` at top-level,
        so if the package is missing the module can't even be loaded. The fix
        must (a) make the import try/except, (b) expose a public `_HAS_ZSTD`
        sentinel, and (c) route append/get through that sentinel so plain
        UTF-8 bytes are used as a fallback.
        """
        import token_sieve.adapters.learning.ring_buffer as rb_mod

        # The module must expose _HAS_ZSTD.
        assert hasattr(rb_mod, "_HAS_ZSTD"), (
            "ring_buffer must expose _HAS_ZSTD sentinel for optional zstd"
        )

        monkeypatch.setattr(rb_mod, "_HAS_ZSTD", False)

        buf = RingBuffer(
            session_id="nozstd", capacity=5, db_path=str(tmp_path / "rb-nozstd.db")
        )
        buf.append("plain-bytes-roundtrip")
        assert buf.get(1) == "plain-bytes-roundtrip"

    def test_append_tolerates_operational_error(self, tmp_path, caplog):
        """H7 fix: sqlite.OperationalError during append must be caught, logged, and dropped.

        Previously, an OperationalError from append() would propagate and crash
        the caller.
        """
        buf = RingBuffer(
            session_id="s1", capacity=10, db_path=str(tmp_path / "rb-oe.db")
        )

        # Wrap the underlying connection so execute() raises on INSERT.
        real_conn = buf._conn
        assert real_conn is not None

        class _FailingConn:
            def __init__(self, inner):
                self._inner = inner

            def execute(self, sql, *args, **kwargs):
                if "INSERT INTO ring_buffer" in sql:
                    raise sqlite3.OperationalError("disk I/O error")
                return self._inner.execute(sql, *args, **kwargs)

            def commit(self):
                return self._inner.commit()

            def __getattr__(self, item):
                return getattr(self._inner, item)

        buf._conn = _FailingConn(real_conn)  # type: ignore[assignment]

        with caplog.at_level(
            logging.WARNING, logger="token_sieve.adapters.learning.ring_buffer"
        ):
            # Must NOT raise.
            buf.append("should-be-dropped")

        assert any(
            "OperationalError" in record.message or "dropped" in record.message
            for record in caplog.records
        )

    def test_wal_mode_enabled_on_file_db(self, tmp_path):
        """H7 fix: file-backed ring buffer must use WAL for concurrent readers."""
        db = str(tmp_path / "rb-wal.db")
        buf = RingBuffer(session_id="s1", capacity=5, db_path=db)
        buf.append("x")

        # PRAGMA journal_mode returns the current mode.
        row = buf._conn.execute("PRAGMA journal_mode").fetchone()  # type: ignore[union-attr]
        assert row[0].lower() == "wal", f"expected WAL mode, got {row[0]!r}"
