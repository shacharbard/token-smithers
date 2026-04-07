"""RED tests for schema migration v5 — shadow_pattern_stats + retry_events tables.

Task 1 of 09-03: verify the v5 migration is idempotent, creates both new tables
with correct columns, primary keys, and leaves existing v1-v4 tables untouched.
"""
from __future__ import annotations

import tempfile

import pytest

from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore


class TestV5Migration:
    """Tests that target schema migration v5 specifics."""

    @pytest.fixture()
    async def store(self):
        s = await SQLiteLearningStore.connect(":memory:")
        try:
            yield s
        finally:
            await s.close()

    async def _get_table_columns(self, store, table_name: str) -> list[str]:
        """Return column names for a given table."""
        async with store._db.execute(
            f"PRAGMA table_info({table_name})"
        ) as cursor:
            rows = await cursor.fetchall()
        return [row[1] for row in rows]

    async def _table_exists(self, store, table_name: str) -> bool:
        """Return True if the named table exists in the DB."""
        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ) as cursor:
            row = await cursor.fetchone()
        return row is not None

    async def test_v5_creates_shadow_pattern_stats(self, store) -> None:
        """shadow_pattern_stats table must exist with the full column set."""
        assert await self._table_exists(store, "shadow_pattern_stats"), (
            "shadow_pattern_stats table not found"
        )
        cols = await self._get_table_columns(store, "shadow_pattern_stats")
        required = {
            "pattern_hash",
            "adapter_name",
            "sample_count",
            "raw_bytes_sum",
            "raw_bytes_max",
            "compressed_bytes_sum",
            "compressed_bytes_max",
            "retry_count",
            "first_seen",
            "last_seen",
            "representative_blob",
        }
        missing = required - set(cols)
        assert not missing, f"shadow_pattern_stats missing columns: {missing}"

    async def test_v5_creates_retry_events(self, store) -> None:
        """retry_events table must exist with the full column set."""
        assert await self._table_exists(store, "retry_events"), (
            "retry_events table not found"
        )
        cols = await self._get_table_columns(store, "retry_events")
        required = {"id", "pattern_hash", "occurred_at", "threshold_at_event", "session_id"}
        missing = required - set(cols)
        assert not missing, f"retry_events missing columns: {missing}"

    async def test_v5_primary_key_on_shadow_stats(self, store) -> None:
        """shadow_pattern_stats PRIMARY KEY (pattern_hash, adapter_name) enforced."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()

        # First insert succeeds
        await store._db.execute(
            """
            INSERT INTO shadow_pattern_stats
                (pattern_hash, adapter_name, sample_count, raw_bytes_sum,
                 raw_bytes_max, compressed_bytes_sum, compressed_bytes_max,
                 retry_count, first_seen, last_seen)
            VALUES ('hash1', 'adapter_x', 1, 100, 100, 80, 80, 0, ?, ?)
            """,
            (now, now),
        )
        await store._db.commit()

        # Second insert with same PK should raise (or be handled by INSERT OR REPLACE)
        # We test with plain INSERT — must fail
        import aiosqlite
        with pytest.raises(aiosqlite.IntegrityError):
            await store._db.execute(
                """
                INSERT INTO shadow_pattern_stats
                    (pattern_hash, adapter_name, sample_count, raw_bytes_sum,
                     raw_bytes_max, compressed_bytes_sum, compressed_bytes_max,
                     retry_count, first_seen, last_seen)
                VALUES ('hash1', 'adapter_x', 2, 200, 200, 150, 150, 0, ?, ?)
                """,
                (now, now),
            )
            await store._db.commit()
        # Roll back the aborted transaction so the connection's teardown does
        # not deadlock on connection cleanup at fixture exit.
        await store._db.rollback()

    async def test_v5_idempotent(self) -> None:
        """Connecting twice to the same file-backed db must not raise."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            store1 = await SQLiteLearningStore.connect(db_path)
            await store1.close()

            # Second connect — must complete without error (migration is idempotent)
            store2 = await SQLiteLearningStore.connect(db_path)
            await store2.close()
        finally:
            import os
            for ext in ["", "-wal", "-shm"]:
                try:
                    os.unlink(db_path + ext)
                except FileNotFoundError:
                    pass

    async def test_v5_schema_version_recorded(self, store) -> None:
        """schema_version table must contain a row with version=6 (shadow tables).

        NOTE: The plan called this 'v5' but wave-2 already used v5 for
        sessions.ended_at. Shadow tables land in migration v6 as a DEVN-01
        deviation from the plan's numbering.
        """
        async with store._db.execute(
            "SELECT version FROM schema_version WHERE version = 6"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None, "schema_version missing version=6 row (shadow+retry tables)"

    async def test_existing_tables_unchanged(self, store) -> None:
        """All v1-v4 tables must still exist after v5 migration."""
        for table in ["tool_usage", "tool_pipeline_config", "tool_cooccurrence", "schema_version"]:
            exists = await self._table_exists(store, table)
            assert exists, f"Pre-existing table '{table}' was lost after v5 migration"
