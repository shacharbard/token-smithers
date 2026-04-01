"""SQLite-backed LearningStore implementation using aiosqlite.

WAL mode for concurrent read/write. Schema migration on connect().
Bounded result_cache with oldest-first eviction.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import aiosqlite

from token_sieve.domain.learning_types import CooccurrenceRecord, ToolUsageRecord
from token_sieve.domain.model import CompressionEvent

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS tool_usage (
    tool_name TEXT NOT NULL,
    server_id TEXT NOT NULL DEFAULT 'default',
    call_count INTEGER NOT NULL DEFAULT 0,
    last_called_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tool_name, server_id)
);

CREATE TABLE IF NOT EXISTS result_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    args_hash TEXT NOT NULL,
    args_normalized TEXT NOT NULL,
    result_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    hit_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_result_cache_tool ON result_cache(tool_name, args_hash);

CREATE TABLE IF NOT EXISTS compression_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    original_tokens INTEGER NOT NULL,
    compressed_tokens INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_compression_events_strategy
    ON compression_events(strategy_name, created_at);

CREATE TABLE IF NOT EXISTS tool_cooccurrence (
    tool_a TEXT NOT NULL,
    tool_b TEXT NOT NULL,
    co_count INTEGER NOT NULL DEFAULT 1,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (tool_a, tool_b)
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""


class SQLiteLearningStore:
    """Cross-session learning persistence backed by SQLite.

    Use the async class method ``connect()`` to create an instance.
    WAL mode is enabled for file-based databases. In-memory databases
    (:memory:) skip WAL since it has no effect.
    """

    def __init__(self, db: aiosqlite.Connection, max_cache_entries: int = 1000) -> None:
        self._db = db
        self._max_cache_entries = max_cache_entries

    @classmethod
    async def connect(
        cls, db_path: str = ":memory:", max_cache_entries: int = 1000
    ) -> SQLiteLearningStore:
        """Create and initialize a SQLiteLearningStore.

        Creates the database, enables WAL mode (for file-based DBs),
        and runs schema migrations.
        """
        db = await aiosqlite.connect(db_path, timeout=30.0)
        db.row_factory = aiosqlite.Row

        # Enable WAL and performance pragmas (no-op for :memory:)
        if db_path != ":memory:":
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA cache_size=64000")
        await db.execute("PRAGMA foreign_keys=ON")

        # Run schema migration
        await db.executescript(_SCHEMA_SQL)

        # Record schema version if not already present
        async with db.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                now = datetime.now(timezone.utc).isoformat()
                await db.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (1, now),
                )
                await db.commit()

        return cls(db, max_cache_entries)

    async def close(self) -> None:
        """Close the database connection."""
        await self._db.close()

    async def record_call(self, tool_name: str, server_id: str) -> None:
        """Record a tool call, incrementing usage count."""
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """\
            INSERT INTO tool_usage (tool_name, server_id, call_count, last_called_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(tool_name, server_id) DO UPDATE SET
                call_count = call_count + 1,
                last_called_at = excluded.last_called_at,
                updated_at = excluded.updated_at
            """,
            (tool_name, server_id, now, now),
        )
        await self._db.commit()

    async def get_usage_stats(self, server_id: str) -> list[ToolUsageRecord]:
        """Get usage statistics for all tools on a server."""
        async with self._db.execute(
            "SELECT tool_name, server_id, call_count, last_called_at "
            "FROM tool_usage WHERE server_id = ? ORDER BY call_count DESC",
            (server_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                ToolUsageRecord(
                    tool_name=row[0],
                    server_id=row[1],
                    call_count=row[2],
                    last_called_at=row[3],
                )
                for row in rows
            ]

    async def cache_result(
        self, tool_name: str, args_normalized: str, result: str
    ) -> None:
        """Cache a tool result. Evicts oldest entries when over capacity."""
        args_hash = hashlib.sha256(
            (tool_name + args_normalized).encode()
        ).hexdigest()
        now = datetime.now(timezone.utc).isoformat()

        # Upsert: if same tool+hash exists, update; otherwise insert
        await self._db.execute(
            """\
            INSERT INTO result_cache (tool_name, args_hash, args_normalized, result_text, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (tool_name, args_hash, args_normalized, result, now),
        )
        await self._db.commit()

        # Enforce bounded cache size
        await self._prune_cache()

    async def _prune_cache(self) -> None:
        """Remove oldest entries if cache exceeds max size."""
        async with self._db.execute("SELECT COUNT(*) FROM result_cache") as cursor:
            row = await cursor.fetchone()
            count = row[0] if row else 0

        if count > self._max_cache_entries:
            excess = count - self._max_cache_entries
            await self._db.execute(
                "DELETE FROM result_cache WHERE id IN "
                "(SELECT id FROM result_cache ORDER BY created_at ASC LIMIT ?)",
                (excess,),
            )
            await self._db.commit()

    async def lookup_similar(
        self, tool_name: str, args_normalized: str, threshold: float
    ) -> str | None:
        """Look up cached result by exact args hash match.

        For Phase 04-01, uses exact hash matching. Semantic similarity
        (edit distance, embeddings) will be added in later plans.
        The threshold parameter is accepted for Protocol conformance
        but not yet used in matching logic.
        """
        args_hash = hashlib.sha256(
            (tool_name + args_normalized).encode()
        ).hexdigest()

        async with self._db.execute(
            "SELECT result_text FROM result_cache "
            "WHERE tool_name = ? AND args_hash = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (tool_name, args_hash),
        ) as cursor:
            row = await cursor.fetchone()
            if row is not None:
                # Increment hit count
                await self._db.execute(
                    "UPDATE result_cache SET hit_count = hit_count + 1 "
                    "WHERE tool_name = ? AND args_hash = ?",
                    (tool_name, args_hash),
                )
                await self._db.commit()
                return row[0]
        return None

    async def record_compression_event(
        self, session_id: str, event: CompressionEvent, tool_name: str
    ) -> None:
        """Record a compression event for analytics."""
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """\
            INSERT INTO compression_events
                (session_id, tool_name, strategy_name, original_tokens, compressed_tokens, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                tool_name,
                event.strategy_name,
                event.original_tokens,
                event.compressed_tokens,
                now,
            ),
        )
        await self._db.commit()

    async def record_cooccurrence(self, tool_a: str, tool_b: str) -> None:
        """Record that two tools were called together."""
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """\
            INSERT INTO tool_cooccurrence (tool_a, tool_b, co_count, last_seen)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(tool_a, tool_b) DO UPDATE SET
                co_count = co_count + 1,
                last_seen = excluded.last_seen
            """,
            (tool_a, tool_b, now),
        )
        await self._db.commit()

    async def get_cooccurrence(self, tool_name: str) -> list[CooccurrenceRecord]:
        """Get co-occurrence records where tool_name is tool_a."""
        async with self._db.execute(
            "SELECT tool_a, tool_b, co_count, last_seen "
            "FROM tool_cooccurrence WHERE tool_a = ? ORDER BY co_count DESC",
            (tool_name,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                CooccurrenceRecord(
                    tool_a=row[0],
                    tool_b=row[1],
                    co_count=row[2],
                    last_seen=row[3],
                )
                for row in rows
            ]
