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


class TestMigrationAtomicity:
    """C4 fix: each per-version migration step must be atomic.

    A crash mid-migration must leave the DB at a consistent version — either
    fully at N or fully at N+1, never with N+1's tables half-created while
    `schema_version` still says N.
    """

    async def test_v6_and_v7_ddl_only_run_inside_their_migration_blocks(
        self, tmp_path
    ) -> None:
        """C4 fix: v6/v7 tables must not exist until their migration block runs.

        The bug: the top-level `executescript(_SCHEMA_SQL + _V6_SCHEMA_SQL +
        _V7_SCHEMA_SQL)` ran unconditionally BEFORE version detection, so a
        DB that is only at v1 would already have v7 tables present when the
        migration block at the bottom ran — out of order, and if that
        migration block ever failed, the schema_version would not match
        the tables actually on disk.

        We build a v1 DB by hand, then patch the top-level executescript to
        fail, and assert that NO v7 tables exist afterwards. Before the fix,
        the top-level executescript has already created v7 tables. After
        the fix, v7 DDL only runs inside the `if current_version < 7`
        migration block.
        """
        db_path = str(tmp_path / "v1_hand.db")

        # Step 1: build a fresh v1 DB by hand with only tool_usage + schema_version.
        import sqlite3 as sync_sqlite
        conn = sync_sqlite.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE tool_usage (
                tool_name TEXT NOT NULL,
                server_id TEXT NOT NULL DEFAULT 'default',
                call_count INTEGER NOT NULL DEFAULT 0,
                last_called_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tool_name, server_id)
            );
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_version (version, applied_at) VALUES (1, '2026-01-01');
            """
        )
        conn.commit()
        conn.close()

        # Step 2: patch aiosqlite so the v7 migration INSERT schema_version raises.
        # This simulates a crash mid-v7. We only want to verify that v7 tables
        # do not exist as a side-effect of top-level setup code.
        import aiosqlite

        original_connect = aiosqlite.connect

        class _FailOnV7Insert:
            """Awaitable that raises when the INSERT schema_version(7) runs."""

            def __init__(self, inner) -> None:
                self._inner = inner

            # Intercept `execute` synchronously so the returned object is the
            # real aiosqlite Cursor (supports both `await` and `async with`).
            # Raise ONLY when the call is the v7 version-record insert —
            # simulate a crash mid-v7 migration.
            def execute(self, sql, *args, **kwargs):
                if (
                    "INSERT INTO schema_version" in sql
                    and args
                    and args[0]
                    and args[0][0] == 7
                ):
                    # Return a coroutine that raises on await.
                    async def _raise():
                        raise RuntimeError("injected crash mid-v7 migration")
                    return _raise()
                return self._inner.execute(sql, *args, **kwargs)

            def __getattr__(self, item):
                return getattr(self._inner, item)

        _CrashyConn = _FailOnV7Insert

        def _patched_connect(*args, **kwargs):
            real = original_connect(*args, **kwargs)

            class _Wrapper:
                def __await__(self):
                    async def _inner():
                        inner_conn = await real
                        return _CrashyConn(inner_conn)
                    return _inner().__await__()

            return _Wrapper()

        import token_sieve.adapters.learning.sqlite_store as mod
        mod.aiosqlite.connect = _patched_connect  # type: ignore[attr-defined]
        try:
            with pytest.raises(RuntimeError, match="injected crash"):
                await SQLiteLearningStore.connect(db_path)
        finally:
            mod.aiosqlite.connect = original_connect  # type: ignore[attr-defined]

        # Step 3: inspect the raw DB with sync sqlite3. Before the fix,
        # bypass_rules will already exist because the top-level
        # executescript created it outside any migration transaction.
        # After the fix, bypass_rules must NOT exist.
        conn = sync_sqlite.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        # schema_version must reflect what actually migrated. With a fix,
        # we expect bypass_rules/bypass_events to NOT exist since their
        # migration block did not complete.
        version_row = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        final_version = version_row[0] if version_row else None
        conn.close()

        assert "bypass_rules" not in tables or final_version == 7, (
            "C4 bug: bypass_rules table exists but schema_version != 7. "
            "Top-level DDL ran before the migration block — not atomic. "
            f"tables={tables}, final_version={final_version}"
        )
        assert "bypass_events" not in tables or final_version == 7, (
            "C4 bug: bypass_events table exists but schema_version != 7. "
            f"tables={tables}, final_version={final_version}"
        )

    async def _table_exists(self, store, table_name: str) -> bool:
        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ) as cursor:
            row = await cursor.fetchone()
        return row is not None
