"""SQLite-backed semantic result cache.

Satisfies SemanticCachePort Protocol. Uses aiosqlite for async I/O.
Supports exact-match (hash) and fuzzy (edit-distance) lookup.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import aiosqlite

from token_sieve.adapters.cache.param_normalizer import compute_args_hash, compute_similarity
from token_sieve.domain.ports_cache import CacheHit

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS result_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    args_normalized TEXT NOT NULL,
    args_hash TEXT NOT NULL,
    result_text TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    last_hit_at REAL
);
"""

_CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_result_cache_tool ON result_cache(tool_name);",
    "CREATE INDEX IF NOT EXISTS idx_result_cache_hash ON result_cache(args_hash);",
]


class SQLiteSemanticCache:
    """Semantic result cache backed by SQLite via aiosqlite.

    Satisfies SemanticCachePort Protocol.

    Lookup strategy:
    1. Check exact args_hash match (O(1) via index)
    2. If no exact match, scan most recent entries for the tool (max 100)
       computing edit-distance similarity via SequenceMatcher
    3. Return best match above threshold, or None
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        max_entries: int = 1000,
        ttl_seconds: int = 86400,
        fuzzy_scan_limit: int = 100,
    ) -> None:
        self._db_path = db_path
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._fuzzy_scan_limit = fuzzy_scan_limit
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open DB connection and create schema if needed."""
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute(_CREATE_TABLE_SQL)
        for idx_sql in _CREATE_INDEX_SQL:
            await self._conn.execute(idx_sql)
        await self._conn.commit()

    async def close(self) -> None:
        """Close the DB connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def lookup_similar(
        self,
        tool_name: str,
        args_normalized: str,
        threshold: float,
    ) -> CacheHit | None:
        """Find a cached result by exact hash or fuzzy match."""
        try:
            if self._conn is None:
                return None

            # Step 1: exact hash match
            args_hash = compute_args_hash_from_normalized(args_normalized)
            hit = await self._exact_lookup(tool_name, args_hash)
            if hit is not None:
                return hit

            # Step 2: fuzzy scan within tool bucket
            return await self._fuzzy_lookup(tool_name, args_normalized, threshold)
        except Exception:
            logger.debug("lookup_similar failed gracefully", exc_info=True)
            return None

    async def cache_result(
        self,
        tool_name: str,
        args_normalized: str,
        args_hash: str,
        result: str,
    ) -> None:
        """Store a tool call result, evicting if over max_entries."""
        try:
            if self._conn is None:
                return

            now = time.time()
            await self._conn.execute(
                """INSERT INTO result_cache
                   (tool_name, args_normalized, args_hash, result_text, hit_count, created_at)
                   VALUES (?, ?, ?, ?, 0, ?)""",
                (tool_name, args_normalized, args_hash, result, now),
            )
            await self._conn.commit()
            await self._evict_overflow()
        except Exception:
            logger.debug("cache_result failed gracefully", exc_info=True)

    async def evict_expired(self) -> int:
        """Remove entries older than TTL. Returns count evicted."""
        try:
            if self._conn is None:
                return 0

            cutoff = time.time() - self._ttl_seconds
            cursor = await self._conn.execute(
                "DELETE FROM result_cache WHERE created_at < ?", (cutoff,)
            )
            await self._conn.commit()
            return cursor.rowcount
        except Exception:
            logger.debug("evict_expired failed gracefully", exc_info=True)
            return 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _exact_lookup(
        self, tool_name: str, args_hash: str
    ) -> CacheHit | None:
        """O(1) lookup by args_hash index."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            """SELECT id, result_text, hit_count
               FROM result_cache
               WHERE tool_name = ? AND args_hash = ?
               LIMIT 1""",
            (tool_name, args_hash),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        row_id, result_text, hit_count = row
        new_count = hit_count + 1
        now = time.time()
        await self._conn.execute(
            "UPDATE result_cache SET hit_count = ?, last_hit_at = ? WHERE id = ?",
            (new_count, now, row_id),
        )
        await self._conn.commit()
        return CacheHit(
            result_text=result_text,
            similarity_score=1.0,
            hit_count=new_count,
        )

    async def _fuzzy_lookup(
        self, tool_name: str, args_normalized: str, threshold: float
    ) -> CacheHit | None:
        """Scan recent entries for the tool, compute similarity."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            """SELECT id, args_normalized, result_text, hit_count
               FROM result_cache
               WHERE tool_name = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (tool_name, self._fuzzy_scan_limit),
        )
        rows = await cursor.fetchall()

        best_hit: CacheHit | None = None
        best_score = 0.0
        best_row_id = None

        for row_id, cached_args, result_text, hit_count in rows:
            score = compute_similarity(args_normalized, cached_args)
            if score >= threshold and score > best_score:
                best_score = score
                best_hit = CacheHit(
                    result_text=result_text,
                    similarity_score=score,
                    hit_count=hit_count + 1,
                )
                best_row_id = row_id

        if best_hit is not None and best_row_id is not None:
            now = time.time()
            await self._conn.execute(
                "UPDATE result_cache SET hit_count = ?, last_hit_at = ? WHERE id = ?",
                (best_hit.hit_count, now, best_row_id),
            )
            await self._conn.commit()

        return best_hit

    async def _evict_overflow(self) -> None:
        """Remove oldest entries if total count exceeds max_entries."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM result_cache"
        )
        row = await cursor.fetchone()
        assert row is not None
        total = row[0]

        if total > self._max_entries:
            excess = total - self._max_entries
            await self._conn.execute(
                """DELETE FROM result_cache
                   WHERE id IN (
                       SELECT id FROM result_cache
                       ORDER BY created_at ASC
                       LIMIT ?
                   )""",
                (excess,),
            )
            await self._conn.commit()


def compute_args_hash_from_normalized(args_normalized: str) -> str:
    """Compute SHA-256 hash from an already-normalized args string."""
    import hashlib
    return hashlib.sha256(args_normalized.encode("utf-8")).hexdigest()
