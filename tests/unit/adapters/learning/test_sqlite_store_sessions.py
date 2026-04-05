"""Tests for session tracking tables and migration in SQLiteLearningStore.

Covers schema migration v4: sessions + tool_usage_sessions tables.
"""

from __future__ import annotations

import pytest

from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore


@pytest.mark.asyncio
class TestSessionSchemaExists:
    """Verify new session-tracking tables exist after store init."""

    @pytest.fixture()
    async def store(self):
        return await SQLiteLearningStore.connect(":memory:")

    async def test_sessions_table_exists(self, store: SQLiteLearningStore) -> None:
        """After store init, sessions table should exist in sqlite_master."""
        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None, "sessions table not found"

    async def test_tool_usage_sessions_table_exists(
        self, store: SQLiteLearningStore
    ) -> None:
        """After store init, tool_usage_sessions table should exist."""
        async with store._db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='tool_usage_sessions'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None, "tool_usage_sessions table not found"


@pytest.mark.asyncio
class TestSessionMigration:
    """Test migration from previous schema version adds session tables."""

    async def test_migration_from_previous_version(self, tmp_path) -> None:
        """Create store with old schema (v3), reopen with new code.

        Verify migration adds sessions tables without losing existing data.
        """
        import aiosqlite

        db_path = str(tmp_path / "learning.db")

        # Simulate a v3 database by creating it and inserting some data
        db = await aiosqlite.connect(db_path)
        await db.execute(
            "CREATE TABLE schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        await db.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (3, '2026-01-01')"
        )
        await db.execute(
            "CREATE TABLE tool_usage ("
            "tool_name TEXT NOT NULL, server_id TEXT NOT NULL, "
            "call_count INTEGER DEFAULT 0, last_called_at TEXT, "
            "updated_at TEXT, PRIMARY KEY (tool_name, server_id))"
        )
        await db.execute(
            "INSERT INTO tool_usage VALUES ('read_file', 'srv1', 5, "
            "'2026-01-01', '2026-01-01')"
        )
        # Create other required tables for _SCHEMA_SQL executescript
        await db.execute(
            "CREATE TABLE result_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "tool_name TEXT, args_hash TEXT, args_normalized TEXT, "
            "result_text TEXT, created_at TEXT, expires_at TEXT, hit_count INTEGER DEFAULT 0)"
        )
        await db.execute(
            "CREATE TABLE compression_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id TEXT, tool_name TEXT, strategy_name TEXT, "
            "original_tokens INTEGER, compressed_tokens INTEGER, "
            "created_at TEXT, is_regret BOOLEAN DEFAULT 0)"
        )
        await db.execute(
            "CREATE TABLE tool_cooccurrence (tool_a TEXT, tool_b TEXT, "
            "co_count INTEGER DEFAULT 1, last_seen TEXT, "
            "PRIMARY KEY (tool_a, tool_b))"
        )
        await db.execute(
            "CREATE TABLE reranker_state (server_id TEXT PRIMARY KEY, "
            "frozen_order TEXT, updated_at TEXT)"
        )
        await db.execute(
            "CREATE TABLE tool_pipeline_config ("
            "tool_name TEXT, server_id TEXT DEFAULT 'default', "
            "adapter_order TEXT DEFAULT '[]', disabled_adapters TEXT DEFAULT '[]', "
            "eval_count INTEGER DEFAULT 0, regret_streak INTEGER DEFAULT 0, "
            "last_eval_at TEXT, created_at TEXT, "
            "PRIMARY KEY (tool_name, server_id))"
        )
        await db.commit()
        await db.close()

        # Reopen with the new code -- migration should add session tables
        store = await SQLiteLearningStore.connect(db_path)

        # Verify old data preserved
        async with store._db.execute(
            "SELECT call_count FROM tool_usage WHERE tool_name='read_file'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None and row[0] == 5, "Existing data lost during migration"

        # Verify new tables exist
        async with store._db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='sessions'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None, "sessions table not created by migration"

        async with store._db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='tool_usage_sessions'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None, "tool_usage_sessions table not created by migration"

        await store.close()


@pytest.mark.asyncio
class TestSessionRecordingAndQuery:
    """Test record_session, get_session_count, record_tool_session_call,
    get_tool_usage_in_recent_sessions methods."""

    @pytest.fixture()
    async def store(self):
        return await SQLiteLearningStore.connect(":memory:")

    async def test_record_session(self, store: SQLiteLearningStore) -> None:
        """Record 3 sessions, get_session_count returns 3."""
        await store.record_session("s1")
        await store.record_session("s2")
        await store.record_session("s3")
        count = await store.get_session_count()
        assert count == 3

    async def test_record_session_idempotent(
        self, store: SQLiteLearningStore
    ) -> None:
        """Recording same session_id twice doesn't duplicate."""
        await store.record_session("s1")
        await store.record_session("s1")
        count = await store.get_session_count()
        assert count == 1

    async def test_record_tool_session_call(
        self, store: SQLiteLearningStore
    ) -> None:
        """Record calls for tool_a in session_1 and session_2, verify counts."""
        await store.record_session("s1")
        await store.record_session("s2")

        await store.record_tool_session_call("tool_a", "s1", "srv1")
        await store.record_tool_session_call("tool_a", "s1", "srv1")
        await store.record_tool_session_call("tool_a", "s2", "srv1")

        # Verify per-session counts via raw SQL
        async with store._db.execute(
            "SELECT call_count FROM tool_usage_sessions "
            "WHERE tool_name='tool_a' AND session_id='s1'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None and row[0] == 2

        async with store._db.execute(
            "SELECT call_count FROM tool_usage_sessions "
            "WHERE tool_name='tool_a' AND session_id='s2'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None and row[0] == 1

    async def test_get_tool_usage_in_recent_sessions(
        self, store: SQLiteLearningStore
    ) -> None:
        """5 sessions, tool_a called in sessions 3 and 5.

        get_tool_usage_in_recent_sessions("tool_a", 3) should return
        sum of calls in sessions 3, 4, 5 (last 3).
        """
        for i in range(1, 6):
            await store.record_session(f"s{i}")

        # tool_a called 2x in s3, 1x in s5
        await store.record_tool_session_call("tool_a", "s3", "srv1")
        await store.record_tool_session_call("tool_a", "s3", "srv1")
        await store.record_tool_session_call("tool_a", "s5", "srv1")

        result = await store.get_tool_usage_in_recent_sessions("tool_a", 3)
        assert result == 3  # 2 from s3 + 1 from s5

    async def test_tool_not_called_in_recent_sessions(
        self, store: SQLiteLearningStore
    ) -> None:
        """Tool never called returns 0."""
        await store.record_session("s1")
        await store.record_session("s2")
        result = await store.get_tool_usage_in_recent_sessions("unknown_tool", 5)
        assert result == 0
