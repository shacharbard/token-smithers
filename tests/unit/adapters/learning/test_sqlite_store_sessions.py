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
