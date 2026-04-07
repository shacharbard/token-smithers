"""RED tests for schema migration v7 — bypass_rules + bypass_events tables.

Task 2 of 09-04: verify the v7 migration is idempotent, creates both new
tables with correct columns, and leaves existing v1-v6 tables untouched.

NOTE: The plan (09-04) called these "v6 tables" but wave-3 already consumed
schema version 6 for shadow_pattern_stats + retry_events. The actual
implementation uses migration v7 as the correct sequential number. This file is
named _v6 for plan traceability (DEVN-01 deviation from plan numbering).
"""
from __future__ import annotations

import tempfile

import pytest

from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore


class TestV7Migration:
    """Tests that target schema migration v7 (bypass_rules + bypass_events)."""

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

    async def test_v6_creates_bypass_rules(self, store) -> None:
        """bypass_rules table must exist with the required columns."""
        assert await self._table_exists(store, "bypass_rules"), (
            "bypass_rules table not found"
        )
        cols = await self._get_table_columns(store, "bypass_rules")
        required = {
            "pattern",
            "source",
            "created_at",
            "last_reinforced_at",
            "session_count",
            "is_active",
        }
        missing = required - set(cols)
        assert not missing, f"bypass_rules missing columns: {missing}"

    async def test_v6_creates_bypass_events(self, store) -> None:
        """bypass_events table must exist with the required columns."""
        assert await self._table_exists(store, "bypass_events"), (
            "bypass_events table not found"
        )
        cols = await self._get_table_columns(store, "bypass_events")
        required = {"id", "pattern", "occurred_at", "kind", "session_id", "ci_detected"}
        missing = required - set(cols)
        assert not missing, f"bypass_events missing columns: {missing}"

    async def test_v6_idempotent(self) -> None:
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

    async def test_v6_schema_version_recorded(self, store) -> None:
        """schema_version table must contain a row with version=7 (bypass tables).

        NOTE: Plan called this 'v6' but actual schema uses v7 (DEVN-01 naming).
        """
        async with store._db.execute(
            "SELECT version FROM schema_version WHERE version = 7"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None, "schema_version missing version=7 row (bypass tables)"

    async def test_v6_does_not_drop_v5_tables(self, store) -> None:
        """All v1-v6 tables must still exist after v7 migration."""
        expected_tables = [
            "tool_usage",
            "tool_pipeline_config",
            "tool_cooccurrence",
            "schema_version",
            "shadow_pattern_stats",
            "retry_events",
        ]
        for table in expected_tables:
            exists = await self._table_exists(store, table)
            assert exists, f"Pre-existing table '{table}' was lost after v7 migration"
