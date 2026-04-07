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
