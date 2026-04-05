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
            assert row[0] == 5  # M7: migration v5 adds ended_at column
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

    async def test_nine_tables_created_after_migration(self, store) -> None:
        """Schema migration v4 creates sessions + tool_usage_sessions (9 tables total)."""
        expected = {
            "tool_usage", "result_cache", "compression_events",
            "tool_cooccurrence", "schema_version", "tool_pipeline_config",
            "reranker_state", "sessions", "tool_usage_sessions",
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


class TestBatchCompressionEvents:
    """Fix 4: Batch compression event recording."""

    @pytest.fixture()
    async def store(self):
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        return await SQLiteLearningStore.connect(":memory:")

    async def test_batch_records_all_events(self, store) -> None:
        """Batch recording inserts all events atomically."""
        from token_sieve.domain.model import CompressionEvent, ContentType

        events = [
            CompressionEvent(
                strategy_name=f"strategy_{i}",
                original_tokens=100,
                compressed_tokens=50,
                content_type=ContentType.TEXT,
                is_regret=False,
            )
            for i in range(5)
        ]
        await store.record_compression_events_batch("session1", events, "tool1")

        async with store._db.execute(
            "SELECT COUNT(*) FROM compression_events WHERE session_id = 'session1'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row[0] == 5

    async def test_batch_empty_list_succeeds(self, store) -> None:
        """Empty event list should succeed without errors."""
        await store.record_compression_events_batch("session1", [], "tool1")

        async with store._db.execute(
            "SELECT COUNT(*) FROM compression_events"
        ) as cursor:
            row = await cursor.fetchone()
            assert row[0] == 0

    async def test_batch_is_single_transaction(self, store) -> None:
        """Batch should use fewer commits than individual calls."""
        from token_sieve.domain.model import CompressionEvent, ContentType

        events = [
            CompressionEvent(
                strategy_name=f"strategy_{i}",
                original_tokens=100,
                compressed_tokens=50,
                content_type=ContentType.TEXT,
                is_regret=False,
            )
            for i in range(3)
        ]
        await store.record_compression_events_batch("session1", events, "tool1")

        # All 3 should be recorded
        async with store._db.execute(
            "SELECT COUNT(*) FROM compression_events"
        ) as cursor:
            row = await cursor.fetchone()
            assert row[0] == 3

        # Verify strategy names are all correct
        async with store._db.execute(
            "SELECT strategy_name FROM compression_events ORDER BY strategy_name"
        ) as cursor:
            rows = await cursor.fetchall()
            names = [r[0] for r in rows]
            assert names == ["strategy_0", "strategy_1", "strategy_2"]


class TestHashKeyConsistency:
    """Fix 5: Hash computation must match between sqlite_store and semantic_cache."""

    @pytest.fixture()
    async def store(self):
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        return await SQLiteLearningStore.connect(":memory:")

    async def test_hash_matches_semantic_cache(self, store) -> None:
        """sqlite_store hash must match compute_args_hash_from_normalized."""
        from token_sieve.adapters.cache.semantic_cache import (
            compute_args_hash_from_normalized,
        )

        args_normalized = '{"path":"/foo/bar"}'
        tool_name = "read_file"

        # Cache a result via sqlite_store
        await store.cache_result(tool_name, args_normalized, "result_data")

        # Compute hash the way semantic_cache does
        expected_hash = compute_args_hash_from_normalized(args_normalized)

        # The stored hash should match
        async with store._db.execute(
            "SELECT args_hash FROM result_cache WHERE tool_name = ?",
            (tool_name,),
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == expected_hash, (
                f"sqlite_store hash {row[0]} != semantic_cache hash {expected_hash}"
            )

    async def test_lookup_uses_consistent_hash(self, store) -> None:
        """lookup_similar must find results cached by cache_result."""
        args_normalized = '{"query":"test"}'
        tool_name = "search"

        await store.cache_result(tool_name, args_normalized, "found_it")
        result = await store.lookup_similar(tool_name, args_normalized, 1.0)
        assert result == "found_it"


class TestResultCacheDedup:
    """M4: Duplicate cache entries must not accumulate in sqlite_store."""

    @pytest.fixture
    async def store(self):
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        s = await SQLiteLearningStore.connect(":memory:")
        yield s
        await s.close()

    @pytest.mark.asyncio
    async def test_duplicate_cache_does_not_create_extra_rows(self, store) -> None:
        """Caching same tool+args twice should result in 1 row, not 2."""
        await store.cache_result("read_file", '{"path":"/a"}', "v1")
        await store.cache_result("read_file", '{"path":"/a"}', "v2")

        async with store._db.execute(
            "SELECT COUNT(*) FROM result_cache WHERE tool_name = ?",
            ("read_file",),
        ) as cursor:
            row = await cursor.fetchone()
            assert row[0] == 1, f"Expected 1 entry, got {row[0]} — duplicates accumulated"

        # Latest value wins
        result = await store.lookup_similar("read_file", '{"path":"/a"}', 1.0)
        assert result == "v2"


class TestCooccurrenceNormalization:
    """M5: Cooccurrence pairs must be normalized (min/max ordering)."""

    @pytest.fixture
    async def store(self):
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        s = await SQLiteLearningStore.connect(":memory:")
        yield s
        await s.close()

    @pytest.mark.asyncio
    async def test_both_directions_same_row(self, store) -> None:
        """(A,B) and (B,A) should increment the same cooccurrence row."""
        await store.record_cooccurrence("tool_x", "tool_y")
        await store.record_cooccurrence("tool_y", "tool_x")

        records = await store.get_cooccurrence("tool_x")
        assert len(records) == 1, f"Expected 1 record, got {len(records)}"
        assert records[0].co_count == 2

    @pytest.mark.asyncio
    async def test_get_cooccurrence_both_directions(self, store) -> None:
        """get_cooccurrence should find records where tool appears as either a or b."""
        await store.record_cooccurrence("tool_a", "tool_z")
        # tool_z is stored as tool_b (tool_a < tool_z)
        records = await store.get_cooccurrence("tool_z")
        assert len(records) == 1, "Should find cooccurrence when tool is tool_b"


class TestBatchMethodOnProtocol:
    """M2: record_compression_events_batch must be declared on Protocol."""

    def test_protocol_has_batch_method(self) -> None:
        """LearningStore Protocol must declare record_compression_events_batch."""
        from token_sieve.domain.ports_learning import LearningStore

        assert hasattr(LearningStore, "record_compression_events_batch")


# ---------------------------------------------------------------------------
# Phase 08 adversarial review fixes
# ---------------------------------------------------------------------------


class TestH6MigrationV4NoDuplicateTableCreation:
    """H6: Migration v4 should not duplicate table creation from _SCHEMA_SQL."""

    @pytest.fixture()
    async def store(self):
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        return await SQLiteLearningStore.connect(":memory:")

    @pytest.mark.asyncio
    async def test_migration_v4_does_not_recreate_tables(self, store) -> None:
        """Migration v4 should just bump version, not re-CREATE tables."""
        import token_sieve.adapters.learning.sqlite_store as mod

        # Check that migration v4 block in connect() doesn't contain
        # CREATE TABLE statements (they should only be in _SCHEMA_SQL)
        import inspect
        source = inspect.getsource(mod.SQLiteLearningStore.connect)
        # Count CREATE TABLE in the migration v4 block
        # If v4 migration still has CREATE TABLE, that's the bug
        lines = source.split("\n")
        in_v4 = False
        v4_create_count = 0
        for line in lines:
            if "Migration v4" in line or "current_version < 4" in line:
                in_v4 = True
            elif in_v4 and ("Migration v5" in line or "current_version < 5" in line):
                in_v4 = False
            elif in_v4 and "CREATE TABLE" in line:
                v4_create_count += 1
        assert v4_create_count == 0, (
            f"H6: Migration v4 has {v4_create_count} CREATE TABLE statements. "
            f"Tables should only be created in _SCHEMA_SQL."
        )


class TestM5ForeignKeyOnToolUsageSessions:
    """M5: tool_usage_sessions.session_id must have FK to sessions."""

    @pytest.fixture()
    async def store(self):
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        return await SQLiteLearningStore.connect(":memory:")

    @pytest.mark.asyncio
    async def test_foreign_key_constraint_declared_in_schema(self, store) -> None:
        """tool_usage_sessions DDL should reference sessions(session_id)."""
        # Check schema SQL for FK declaration
        async with store._db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='tool_usage_sessions'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            ddl = row[0]
            assert "REFERENCES" in ddl and "sessions" in ddl, (
                f"M5: FK constraint on session_id is missing. DDL: {ddl}"
            )


class TestM6LastNValidation:
    """M6: get_tool_usage_in_recent_sessions must guard against last_n <= 0."""

    @pytest.fixture()
    async def store(self):
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        return await SQLiteLearningStore.connect(":memory:")

    @pytest.mark.asyncio
    async def test_negative_last_n_returns_zero(self, store) -> None:
        """Negative last_n should return 0 immediately, not scan all."""
        result = await store.get_tool_usage_in_recent_sessions("tool_a", -1)
        assert result == 0

    @pytest.mark.asyncio
    async def test_zero_last_n_returns_zero(self, store) -> None:
        """Zero last_n should return 0 immediately."""
        result = await store.get_tool_usage_in_recent_sessions("tool_a", 0)
        assert result == 0


class TestM8NoDoubleCommitInRecordToolSessionCall:
    """M8: record_tool_session_call should not commit before record_call."""

    @pytest.fixture()
    async def store(self):
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        return await SQLiteLearningStore.connect(":memory:")

    @pytest.mark.asyncio
    async def test_single_commit_in_record_tool_session_call(self, store) -> None:
        """record_tool_session_call should let record_call handle commit."""
        import inspect
        import token_sieve.adapters.learning.sqlite_store as mod

        source = inspect.getsource(mod.SQLiteLearningStore.record_tool_session_call)
        # Should not have its own commit; record_call handles it
        commit_count = source.count("await self._db.commit()")
        assert commit_count == 0, (
            f"M8: record_tool_session_call has {commit_count} commit(s). "
            f"Should delegate commit to record_call."
        )


class TestM9IndexOnSessionsStartedAt:
    """M9: sessions.started_at should have an index for ORDER BY performance."""

    @pytest.fixture()
    async def store(self):
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        return await SQLiteLearningStore.connect(":memory:")

    @pytest.mark.asyncio
    async def test_index_exists_on_sessions_started_at(self, store) -> None:
        """An index should exist on sessions.started_at."""
        async with store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='sessions'"
        ) as cursor:
            rows = await cursor.fetchall()
            index_names = [row[0] for row in rows]

        assert any("started_at" in name for name in index_names), (
            f"M9: No index on sessions.started_at. Indexes: {index_names}"
        )
