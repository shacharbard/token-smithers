"""Tests for SQLiteSemanticCache adapter."""

from __future__ import annotations

import sqlite3

import pytest

from tests.unit.domain.test_ports_cache import SemanticCacheContract
from token_sieve.adapters.cache.semantic_cache import SQLiteSemanticCache
from token_sieve.domain.ports_cache import SemanticCachePort


@pytest.fixture
async def sqlite_cache() -> SQLiteSemanticCache:
    """Create an in-memory SQLite semantic cache for testing."""
    cache = SQLiteSemanticCache(db_path=":memory:", max_entries=100, ttl_seconds=3600)
    await cache.initialize()
    return cache


class TestSQLiteSemanticCacheContract(SemanticCacheContract):
    """SQLiteSemanticCache must pass all SemanticCachePort contract tests."""

    @pytest.fixture
    async def strategy(self, sqlite_cache: SQLiteSemanticCache) -> SemanticCachePort:
        return sqlite_cache


class TestSQLiteSemanticCacheProtocol:
    """SQLiteSemanticCache satisfies the SemanticCachePort Protocol."""

    @pytest.mark.asyncio
    async def test_isinstance_check(self, sqlite_cache: SQLiteSemanticCache) -> None:
        assert isinstance(sqlite_cache, SemanticCachePort)


class TestExactMatchFirst:
    """Exact hash match should be preferred over fuzzy scan."""

    @pytest.mark.asyncio
    async def test_exact_match_returns_before_fuzzy(
        self, sqlite_cache: SQLiteSemanticCache
    ) -> None:
        # Cache two entries with similar args
        await sqlite_cache.cache_result(
            "read_file", '{"path":"/src/main.py"}', "hash_exact", "exact result"
        )
        await sqlite_cache.cache_result(
            "read_file", '{"path":"/src/main.py","extra":"x"}', "hash_fuzzy", "fuzzy result"
        )
        # Lookup with exact hash should return exact match
        hit = await sqlite_cache.lookup_similar(
            "read_file", '{"path":"/src/main.py"}', 0.85
        )
        assert hit is not None
        assert hit.result_text == "exact result"
        assert hit.similarity_score == 1.0


class TestMaxEntriesEviction:
    """Cache should evict oldest entries when exceeding max_entries."""

    @pytest.mark.asyncio
    async def test_eviction_at_max(self) -> None:
        cache = SQLiteSemanticCache(
            db_path=":memory:", max_entries=3, ttl_seconds=3600
        )
        await cache.initialize()

        for i in range(5):
            await cache.cache_result(
                "tool", f'{{"i":{i}}}', f"hash_{i}", f"result_{i}"
            )

        # Only 3 most recent should remain
        # Oldest (i=0, i=1) should be evicted
        hit_0 = await cache.lookup_similar("tool", '{"i":0}', 0.99)
        hit_4 = await cache.lookup_similar("tool", '{"i":4}', 0.99)

        assert hit_0 is None  # evicted
        assert hit_4 is not None  # retained
        assert hit_4.result_text == "result_4"


class TestDBErrorGracefulDegradation:
    """DB errors should not propagate -- return None/0 instead."""

    @pytest.mark.asyncio
    async def test_lookup_on_closed_db_returns_none(self) -> None:
        cache = SQLiteSemanticCache(
            db_path=":memory:", max_entries=100, ttl_seconds=3600
        )
        await cache.initialize()
        await cache.cache_result("tool", '{"k":"v"}', "h1", "data")

        # Sabotage the connection
        await cache.close()

        hit = await cache.lookup_similar("tool", '{"k":"v"}', 0.85)
        assert hit is None

    @pytest.mark.asyncio
    async def test_cache_result_on_closed_db_no_error(self) -> None:
        cache = SQLiteSemanticCache(
            db_path=":memory:", max_entries=100, ttl_seconds=3600
        )
        await cache.initialize()
        await cache.close()

        # Should not raise
        await cache.cache_result("tool", '{"k":"v"}', "h1", "data")

    @pytest.mark.asyncio
    async def test_evict_expired_on_closed_db_returns_zero(self) -> None:
        cache = SQLiteSemanticCache(
            db_path=":memory:", max_entries=100, ttl_seconds=3600
        )
        await cache.initialize()
        await cache.close()

        count = await cache.evict_expired()
        assert count == 0


class TestNoneConnectionGuards:
    """Methods must return None/early when _conn is None, not crash via assert."""

    @pytest.mark.asyncio
    async def test_exact_lookup_returns_none_when_conn_is_none(self) -> None:
        cache = SQLiteSemanticCache(
            db_path=":memory:", max_entries=100, ttl_seconds=3600
        )
        # Never initialize -- _conn stays None
        result = await cache._exact_lookup("tool", "some_hash")
        assert result is None

    @pytest.mark.asyncio
    async def test_fuzzy_lookup_returns_none_when_conn_is_none(self) -> None:
        cache = SQLiteSemanticCache(
            db_path=":memory:", max_entries=100, ttl_seconds=3600
        )
        result = await cache._fuzzy_lookup("tool", '{"k":"v"}', 0.85)
        assert result is None

    @pytest.mark.asyncio
    async def test_evict_overflow_returns_early_when_conn_is_none(self) -> None:
        cache = SQLiteSemanticCache(
            db_path=":memory:", max_entries=100, ttl_seconds=3600
        )
        # Should not raise
        await cache._evict_overflow()

    @pytest.mark.asyncio
    async def test_evict_overflow_handles_none_row(self) -> None:
        """Even if COUNT(*) somehow returns None row, evict should not crash."""
        cache = SQLiteSemanticCache(
            db_path=":memory:", max_entries=100, ttl_seconds=3600
        )
        await cache.initialize()
        # Normal case: empty table, row should exist with count=0
        # This validates the guard path exists (row is not None in practice,
        # but the guard protects against edge cases)
        await cache._evict_overflow()  # should not raise


class TestHitCountIncrement:
    """Hit count should increment on repeated lookups."""

    @pytest.mark.asyncio
    async def test_hit_count_increases(
        self, sqlite_cache: SQLiteSemanticCache
    ) -> None:
        await sqlite_cache.cache_result(
            "read_file", '{"path":"/a"}', "hash_a", "content"
        )
        hit1 = await sqlite_cache.lookup_similar("read_file", '{"path":"/a"}', 0.85)
        assert hit1 is not None
        assert hit1.hit_count == 1

        hit2 = await sqlite_cache.lookup_similar("read_file", '{"path":"/a"}', 0.85)
        assert hit2 is not None
        assert hit2.hit_count == 2
