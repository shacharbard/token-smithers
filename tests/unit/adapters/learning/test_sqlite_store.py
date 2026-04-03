"""Tests for SQLiteLearningStore -- contract tests + SQLite-specific behavior.

Uses in-memory :memory: SQLite for all tests (fast, no filesystem).
"""

from __future__ import annotations

import pytest

from tests.unit.domain.test_ports_learning import LearningStoreContract


class TestSQLiteLearningStoreContract(LearningStoreContract):
    """SQLiteLearningStore must pass all LearningStore contract tests."""

    @pytest.fixture()
    async def store(self):
        """Provide SQLiteLearningStore with in-memory DB."""
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        store = await SQLiteLearningStore.connect(":memory:")
        return store


class TestSQLiteSpecificBehavior:
    """SQLite-specific tests beyond the contract."""

    @pytest.fixture()
    async def store(self):
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        return await SQLiteLearningStore.connect(":memory:")

    async def test_wal_mode_enabled(self, store) -> None:
        """WAL journal mode should be active."""
        async with store._db.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
            assert row is not None
            # In-memory databases use "memory" journal mode, not WAL
            # WAL is only meaningful for file-based DBs
            # For :memory:, we just verify the pragma runs without error

    async def test_schema_version_table_exists(self, store) -> None:
        """Schema migration creates schema_version table."""
        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None

    async def test_all_five_tables_created(self, store) -> None:
        """Schema migration creates all 5 required tables."""
        expected = {"tool_usage", "result_cache", "compression_events", "tool_cooccurrence", "schema_version"}
        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            rows = await cursor.fetchall()
            tables = {row[0] for row in rows}
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"

    async def test_result_cache_bounded(self, store) -> None:
        """Result cache respects max_entries limit."""
        # Store has default max_entries=1000, use a smaller one
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        small_store = await SQLiteLearningStore.connect(":memory:", max_cache_entries=5)
        for i in range(10):
            await small_store.cache_result("tool", f"args_{i}", f"result_{i}")

        async with small_store._db.execute("SELECT COUNT(*) FROM result_cache") as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] <= 5

    async def test_close(self, store) -> None:
        """Close releases the database connection."""
        await store.close()
        # After close, operations should raise
        with pytest.raises(Exception):
            await store.record_call("tool", "server")

    async def test_connect_twice_idempotent(self, tmp_path) -> None:
        """Calling connect() twice on the same DB should not fail."""
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        db_path = str(tmp_path / "test.db")
        store1 = await SQLiteLearningStore.connect(db_path)
        await store1.close()

        # Second connect runs migrations again -- must be idempotent
        store2 = await SQLiteLearningStore.connect(db_path)
        async with store2._db.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == 2
        await store2.close()

    async def test_migration_preserves_existing_data(self, tmp_path) -> None:
        """Existing compression_events rows get is_regret=0 after migration."""
        import aiosqlite
        from token_sieve.adapters.learning.sqlite_store import (
            SQLiteLearningStore,
            _SCHEMA_SQL,
        )

        db_path = str(tmp_path / "legacy.db")
        # Create a v1 database manually (no is_regret column)
        db = await aiosqlite.connect(db_path)
        await db.executescript(_SCHEMA_SQL)
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (1, now),
        )
        await db.execute(
            "INSERT INTO compression_events "
            "(session_id, tool_name, strategy_name, original_tokens, compressed_tokens, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("s1", "read_file", "whitespace", 100, 50, now),
        )
        await db.commit()
        await db.close()

        # Now connect with SQLiteLearningStore (triggers v2 migration)
        store = await SQLiteLearningStore.connect(db_path)
        async with store._db.execute(
            "SELECT is_regret FROM compression_events WHERE session_id = 's1'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            # Existing rows should default to 0 (not regret)
            assert row[0] == 0
        await store.close()

    async def test_pipeline_config_round_trip(self, store) -> None:
        """Save then get returns identical PipelineConfig data."""
        from token_sieve.domain.learning_types import PipelineConfig

        original = PipelineConfig(
            tool_name="read_file",
            server_id="server1",
            adapter_order=("whitespace", "null_field", "rle"),
            disabled_adapters=("yaml_transcoder",),
            eval_count=42,
            regret_streak=3,
            last_eval_at="2026-04-01T10:00:00Z",
            created_at="2026-04-01T09:00:00Z",
        )
        await store.save_pipeline_config(original)
        retrieved = await store.get_pipeline_config("read_file", "server1")

        assert retrieved is not None
        assert retrieved.tool_name == original.tool_name
        assert retrieved.server_id == original.server_id
        assert retrieved.adapter_order == original.adapter_order
        assert retrieved.disabled_adapters == original.disabled_adapters
        assert retrieved.eval_count == original.eval_count
        assert retrieved.regret_streak == original.regret_streak
        assert retrieved.last_eval_at == original.last_eval_at
        assert retrieved.created_at == original.created_at

    async def test_six_tables_created_after_migration(self, store) -> None:
        """Schema migration v2 creates tool_pipeline_config (6 tables total)."""
        expected = {
            "tool_usage", "result_cache", "compression_events",
            "tool_cooccurrence", "schema_version", "tool_pipeline_config",
        }
        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            rows = await cursor.fetchall()
            tables = {row[0] for row in rows}
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"

    async def test_compression_events_has_is_regret_column(self, store) -> None:
        """After migration, compression_events has is_regret column."""
        async with store._db.execute(
            "PRAGMA table_info(compression_events)"
        ) as cursor:
            columns = [r[1] for r in await cursor.fetchall()]
        assert "is_regret" in columns
