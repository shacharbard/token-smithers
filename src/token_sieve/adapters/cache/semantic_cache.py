"""SQLite-backed semantic result cache.

Satisfies SemanticCachePort Protocol. Uses aiosqlite for async I/O.
Supports exact-match (hash) and fuzzy (edit-distance or cosine) lookup.
"""

from __future__ import annotations

import json
import logging
import math
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
    last_hit_at REAL,
    embedding TEXT
);
"""

_CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_result_cache_tool ON result_cache(tool_name);",
    "CREATE INDEX IF NOT EXISTS idx_result_cache_hash ON result_cache(args_hash);",
    # H3 fix: prevent duplicate (tool_name, args_hash) entries
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_result_cache_dedup ON result_cache(tool_name, args_hash);",
]

# Migration: add embedding column if it doesn't exist
_ADD_EMBEDDING_COL_SQL = (
    "ALTER TABLE result_cache ADD COLUMN embedding TEXT"
)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SQLiteSemanticCache:
    """Semantic result cache backed by SQLite via aiosqlite.

    Satisfies SemanticCachePort Protocol.

    Lookup strategy:
    1. Check exact args_hash match (O(1) via index)
    2. If no exact match, scan most recent entries for the tool (max 100)
       computing similarity via embedder (cosine) or SequenceMatcher (fallback)
    3. Return best match above threshold, or None
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        max_entries: int = 1000,
        ttl_seconds: int = 86400,
        fuzzy_scan_limit: int = 100,
        embedder: Any | None = None,
    ) -> None:
        self._db_path = db_path
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._fuzzy_scan_limit = fuzzy_scan_limit
        self._embedder = embedder
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open DB connection and create schema if needed."""
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute(_CREATE_TABLE_SQL)
        for idx_sql in _CREATE_INDEX_SQL:
            await self._conn.execute(idx_sql)
        # Migration: add embedding column to existing tables
        try:
            await self._conn.execute(_ADD_EMBEDDING_COL_SQL)
        except Exception:
            pass  # Column already exists
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
            embedding_json: str | None = None
            if self._embedder is not None:
                try:
                    vec = self._embedder.embed(args_normalized)
                    embedding_json = json.dumps(vec)
                except Exception:
                    logger.debug("embedder.embed failed, storing without embedding", exc_info=True)

            # H3 fix: use INSERT OR REPLACE to prevent duplicate entries
            await self._conn.execute(
                """INSERT OR REPLACE INTO result_cache
                   (tool_name, args_normalized, args_hash, result_text,
                    hit_count, created_at, embedding)
                   VALUES (?, ?, ?, ?, 0, ?, ?)""",
                (tool_name, args_normalized, args_hash, result, now, embedding_json),
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
        if self._conn is None:
            return None
        # H1 fix: enforce TTL on lookup — expired entries must not be served
        min_created = time.time() - self._ttl_seconds
        cursor = await self._conn.execute(
            """SELECT id, result_text, hit_count
               FROM result_cache
               WHERE tool_name = ? AND args_hash = ?
                 AND created_at >= ?
               LIMIT 1""",
            (tool_name, args_hash, min_created),
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
        """Scan recent entries for the tool, compute similarity.

        When an embedder is available, uses cosine similarity over stored
        embedding vectors. Falls back to SequenceMatcher otherwise.
        """
        if self._conn is None:
            return None

        # If embedder is available, compute query embedding for cosine similarity
        query_embedding: list[float] | None = None
        if self._embedder is not None:
            try:
                query_embedding = self._embedder.embed(args_normalized)
            except Exception:
                logger.debug("embedder.embed failed, falling back to SequenceMatcher", exc_info=True)

        # H1 fix: enforce TTL on fuzzy lookup — expired entries must not be scanned
        min_created = time.time() - self._ttl_seconds
        cursor = await self._conn.execute(
            """SELECT id, args_normalized, result_text, hit_count, embedding
               FROM result_cache
               WHERE tool_name = ? AND created_at >= ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (tool_name, min_created, self._fuzzy_scan_limit),
        )
        rows = await cursor.fetchall()

        best_hit: CacheHit | None = None
        best_score = 0.0
        best_row_id = None

        for row_id, cached_args, result_text, hit_count, embedding_json in rows:
            score: float
            if query_embedding is not None and embedding_json is not None:
                try:
                    cached_embedding = json.loads(embedding_json)
                    score = _cosine_similarity(query_embedding, cached_embedding)
                except (json.JSONDecodeError, TypeError):
                    score = compute_similarity(args_normalized, cached_args)
            else:
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
        if self._conn is None:
            return
        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM result_cache"
        )
        row = await cursor.fetchone()
        if row is None:
            return
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
