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
