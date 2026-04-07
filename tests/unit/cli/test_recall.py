"""RED tests for recall CLI subcommand — Task 5 of 09-01.

Tests cover: return last raw, indexed access, empty buffer, negative index,
and main() dispatch routing.
"""
from __future__ import annotations

import pytest

from token_sieve.cli.recall import run as run_recall
from token_sieve.cli.main import main


def _make_buffer(entries: list[str], tmp_path, session_id: str = "test-session"):
    """Helper: create a RingBuffer pre-populated with entries."""
    from token_sieve.adapters.learning.ring_buffer import RingBuffer

    buf = RingBuffer(
        session_id=session_id,
        capacity=10,
        db_path=str(tmp_path / "rb.db"),
    )
    for entry in entries:
        buf.append(entry)
    return buf


class TestRecall:
    """Unit tests for token-sieve recall subcommand."""

    def test_recall_returns_last_raw(self, monkeypatch, capsys, tmp_path):
        """run_recall([]) with 3 entries returns the most recent ('c')."""
        buf = _make_buffer(["a", "b", "c"], tmp_path)

        import token_sieve.cli.recall as recall_mod
        monkeypatch.setattr(recall_mod, "_get_ring_buffer", lambda: buf)

        rc = run_recall([])
        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out.strip() == "c"

    def test_recall_with_index_arg(self, monkeypatch, capsys, tmp_path):
        """run_recall(['2']) with entries a,b,c returns 'b' (2nd-most-recent)."""
        buf = _make_buffer(["a", "b", "c"], tmp_path)

        import token_sieve.cli.recall as recall_mod
        monkeypatch.setattr(recall_mod, "_get_ring_buffer", lambda: buf)

        rc = run_recall(["2"])
        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out.strip() == "b"

    def test_recall_index_out_of_range(self, monkeypatch, capsys, tmp_path):
        """Empty buffer + run_recall([]) → exit 1, stderr 'no recorded outputs'."""
        from token_sieve.adapters.learning.ring_buffer import RingBuffer

        empty_buf = RingBuffer(
            session_id="empty", capacity=10, db_path=str(tmp_path / "rb.db")
        )

        import token_sieve.cli.recall as recall_mod
        monkeypatch.setattr(recall_mod, "_get_ring_buffer", lambda: empty_buf)

        rc = run_recall([])
        captured = capsys.readouterr()
        assert rc == 1
        assert "no recorded outputs" in captured.err.lower()

    def test_recall_negative_index_rejected(self, monkeypatch, capsys, tmp_path):
        """run_recall(['-1']) → exit 2, stderr contains 'index must be >= 1'."""
        from token_sieve.adapters.learning.ring_buffer import RingBuffer

        buf = RingBuffer(
            session_id="s", capacity=10, db_path=str(tmp_path / "rb.db")
        )

        import token_sieve.cli.recall as recall_mod
        monkeypatch.setattr(recall_mod, "_get_ring_buffer", lambda: buf)

        rc = run_recall(["-1"])
        captured = capsys.readouterr()
        assert rc == 2
        assert "index must be >= 1" in captured.err.lower()

    def test_main_dispatches_recall(self, monkeypatch, capsys, tmp_path):
        """main(['recall']) routes to recall.run()."""
        from token_sieve.adapters.learning.ring_buffer import RingBuffer

        buf = RingBuffer(
            session_id="s", capacity=10, db_path=str(tmp_path / "rb.db")
        )
        buf.append("dispatch-test")

        import token_sieve.cli.recall as recall_mod
        monkeypatch.setattr(recall_mod, "_get_ring_buffer", lambda: buf)

        rc = main(["recall"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "dispatch-test" in captured.out
