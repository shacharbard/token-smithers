"""RED tests for `token-sieve stats --shadow` subcommand.

Task 5 of 09-03: verify run_stats_shadow() reads shadow_pattern_stats and
formats output correctly.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import patch

import pytest

from token_sieve.cli.stats_shadow import run_stats_shadow


class TestStatsShadowDrillDown:
    """run_stats_shadow() reads shadow_pattern_stats and formats output."""

    @pytest.fixture()
    def populated_db(self, tmp_path):
        """Create a file-backed SQLite DB populated with 3 shadow_pattern_stats rows."""
        import aiosqlite
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        db_path = str(tmp_path / "test.db")

        async def _setup():
            store = await SQLiteLearningStore.connect(db_path)
            now = datetime.now(timezone.utc).isoformat()
            rows = [
                ("hash_aaa", "adapter_x", 10, 1000, 200, 700, 150, 1, now, now),
                ("hash_bbb", "adapter_y", 5, 500, 100, 400, 80, 0, now, now),
                ("hash_ccc", "adapter_x", 30, 3000, 300, 1500, 200, 3, now, now),
            ]
            for row in rows:
                await store._db.execute(
                    """
                    INSERT INTO shadow_pattern_stats
                        (pattern_hash, adapter_name, sample_count, raw_bytes_sum,
                         raw_bytes_max, compressed_bytes_sum, compressed_bytes_max,
                         retry_count, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    row,
                )
            await store._db.commit()
            await store.close()
            return db_path

        return asyncio.run(_setup())

    def test_stats_shadow_drill_down(self, populated_db, capsys):
        """Output must include pattern_hash, adapter, sample_count, mean_savings_pct,
        retry_count, last_seen for each row."""
        rc = run_stats_shadow(db_path=populated_db)
        captured = capsys.readouterr()
        out = captured.out

        # Each pattern hash must appear
        assert "hash_aaa" in out
        assert "hash_bbb" in out
        assert "hash_ccc" in out

        # Adapter names must appear
        assert "adapter_x" in out
        assert "adapter_y" in out

        assert rc == 0

    def test_stats_shadow_empty_store(self, tmp_path, capsys):
        """Empty shadow_pattern_stats → output should say 'No shadow data' or similar."""
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        db_path = str(tmp_path / "empty.db")
        asyncio.run(
            _connect_and_close(db_path)
        )

        rc = run_stats_shadow(db_path=db_path)
        captured = capsys.readouterr()
        out = captured.out.lower()

        assert "no shadow" in out or "no data" in out or "empty" in out, (
            f"Expected 'no shadow data' message, got: {captured.out!r}"
        )
        assert rc == 0

    def test_stats_shadow_sorts_by_sample_count_desc(self, tmp_path, capsys):
        """Rows sorted by sample_count DESC: 100, 30, 5."""
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        db_path = str(tmp_path / "sorted.db")

        async def _setup():
            store = await SQLiteLearningStore.connect(db_path)
            now = datetime.now(timezone.utc).isoformat()
            # Insert in non-descending order
            for hash_val, count in [("z_hash", 5), ("a_hash", 100), ("m_hash", 30)]:
                await store._db.execute(
                    """
                    INSERT INTO shadow_pattern_stats
                        (pattern_hash, adapter_name, sample_count, raw_bytes_sum,
                         raw_bytes_max, compressed_bytes_sum, compressed_bytes_max,
                         retry_count, first_seen, last_seen)
                    VALUES (?, 'adp', ?, 100, 100, 80, 80, 0, ?, ?)
                    """,
                    (hash_val, count, now, now),
                )
            await store._db.commit()
            await store.close()

        asyncio.run(_setup())

        run_stats_shadow(db_path=db_path)
        captured = capsys.readouterr()
        out = captured.out

        # All three must appear
        pos_100 = out.find("a_hash")
        pos_30 = out.find("m_hash")
        pos_5 = out.find("z_hash")

        assert pos_100 < pos_30 < pos_5, (
            f"Output not sorted by sample_count DESC: positions {pos_100}, {pos_30}, {pos_5}\n{out}"
        )


class TestMainDispatchesStatsShadow:
    """main() routes 'stats --shadow' to run_stats_shadow."""

    def test_main_dispatches_stats_shadow(self, monkeypatch, capsys):
        """main(['stats', '--shadow']) must call run_stats_shadow."""
        from token_sieve.cli.main import main

        called: list[bool] = []

        def fake_run_stats_shadow(db_path=None):
            called.append(True)
            print("shadow output")
            return 0

        monkeypatch.setattr(
            "token_sieve.cli.stats_shadow.run_stats_shadow",
            fake_run_stats_shadow,
        )

        # Patch the import inside main.py
        import token_sieve.cli.stats_shadow as ss_mod
        monkeypatch.setattr(ss_mod, "run_stats_shadow", fake_run_stats_shadow)

        rc = main(["stats", "--shadow"])
        assert rc == 0


# ---------------------------------------------------------------------------
# Helper coroutine
# ---------------------------------------------------------------------------

async def _connect_and_close(db_path: str) -> None:
    from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

    store = await SQLiteLearningStore.connect(db_path)
    await store.close()
