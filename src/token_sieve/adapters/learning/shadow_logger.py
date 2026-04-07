"""Shadow logging for CLI compress subcommand — Decision D3.

Adaptive sampling rates:
- 25% for new patterns (sample_count < 50)
- 5% for established patterns (50 ≤ sample_count < 200)
- 1% for confidently-rated patterns
- 100% for retries (always sample)

Stores zstd-compressed representative blobs up to 256KB compressed.
Uses ON CONFLICT(pattern_hash, adapter_name) DO UPDATE to accumulate counters.
Preserves existing blob if new compression fails (fail-safe).
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import zstandard

if TYPE_CHECKING:
    from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

logger = logging.getLogger(__name__)

# Maximum compressed blob size in bytes (256KB)
_BLOB_CAP_BYTES = 256 * 1024


def _sample_rate(
    sample_count: int, confidently_rated: bool, is_retry: bool
) -> float:
    """Return the sampling probability for a given pattern state (D3a).

    Args:
        sample_count: Number of times this pattern has been sampled.
        confidently_rated: True when the pattern has been flagged as
            well-understood (≥ 200 samples).
        is_retry: True when the invocation was detected as a retry.

    Returns:
        A float in [0.0, 1.0] representing the sampling probability.
    """
    if is_retry:
        return 1.0
    if confidently_rated or sample_count >= 200:
        return 0.01
    if sample_count >= 50:
        return 0.05
    return 0.25


class ShadowLogger:
    """Fire-and-forget shadow sampler for compression pipeline telemetry.

    Writes to the shadow_pattern_stats table in the learning store.
    Sampling decisions use a seeded RNG for determinism in tests.
    All writes are fire-and-forget: any exception is logged and swallowed
    so that shadow logging NEVER affects Claude's observed bytes (D4c).
    """

    def __init__(
        self,
        store: "SQLiteLearningStore",
        rng_seed: int | None = None,
    ) -> None:
        self._store = store
        self._rng = random.Random(rng_seed)

    async def maybe_log(
        self,
        pattern_hash: str,
        adapter_name: str,
        raw_bytes: bytes,
        compressed_bytes: int,
        is_retry: bool,
    ) -> None:
        """Conditionally sample and persist a pattern observation.

        Coin-flips against the computed sampling rate.  On a hit:
        1. Attempts to zstd-compress raw_bytes.
        2. If compressed size > 256KB cap, stores no blob (metadata only).
        3. Upserts shadow_pattern_stats with ON CONFLICT counter accumulation.
        4. On compression failure, preserves the existing representative_blob.

        All exceptions are caught and logged at DEBUG level (D4c — fire-and-forget).

        Args:
            pattern_hash: Canonical hash for the command pattern.
            adapter_name: Name of the active compression adapter.
            raw_bytes: Uncompressed stdout bytes.
            compressed_bytes: Length of compressed output (for counter).
            is_retry: Whether this invocation was classified as a retry.
        """
        try:
            await self._do_log(
                pattern_hash=pattern_hash,
                adapter_name=adapter_name,
                raw_bytes=raw_bytes,
                compressed_bytes=compressed_bytes,
                is_retry=is_retry,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("ShadowLogger.maybe_log failed (fire-and-forget): %s", exc)

    async def _do_log(
        self,
        pattern_hash: str,
        adapter_name: str,
        raw_bytes: bytes,
        compressed_bytes: int,
        is_retry: bool,
    ) -> None:
        """Internal implementation of maybe_log — exceptions propagate to caller."""
        # Fetch current sample_count and confidence flag to decide sampling rate
        sample_count = 0
        confidently_rated = False
        async with self._store._db.execute(
            "SELECT sample_count FROM shadow_pattern_stats "
            "WHERE pattern_hash=? AND adapter_name=?",
            (pattern_hash, adapter_name),
        ) as cur:
            row = await cur.fetchone()
            if row:
                sample_count = row[0]
                confidently_rated = sample_count >= 200

        rate = _sample_rate(
            sample_count=sample_count,
            confidently_rated=confidently_rated,
            is_retry=is_retry,
        )

        if self._rng.random() > rate:
            return  # not sampled this time

        # Try to compress the blob
        new_blob: bytes | None = None
        try:
            compressed_blob = zstandard.ZstdCompressor().compress(raw_bytes)
            if len(compressed_blob) <= _BLOB_CAP_BYTES:
                new_blob = compressed_blob
            # else: too large — blob will be None (metadata-only)
        except Exception as exc:  # noqa: BLE001
            logger.debug("ShadowLogger: zstd compression failed, preserving old blob: %s", exc)
            # new_blob stays None; the UPDATE below will preserve existing blob

        now = datetime.now(timezone.utc).isoformat()
        raw_len = len(raw_bytes)

        if new_blob is not None:
            # Upsert with blob replacement
            await self._store._db.execute(
                """\
                INSERT INTO shadow_pattern_stats
                    (pattern_hash, adapter_name, sample_count, raw_bytes_sum,
                     raw_bytes_max, compressed_bytes_sum, compressed_bytes_max,
                     retry_count, first_seen, last_seen, representative_blob)
                VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pattern_hash, adapter_name) DO UPDATE SET
                    sample_count = sample_count + 1,
                    raw_bytes_sum = raw_bytes_sum + excluded.raw_bytes_sum,
                    raw_bytes_max = MAX(raw_bytes_max, excluded.raw_bytes_max),
                    compressed_bytes_sum = compressed_bytes_sum + excluded.compressed_bytes_sum,
                    compressed_bytes_max = MAX(compressed_bytes_max, excluded.compressed_bytes_max),
                    retry_count = retry_count + excluded.retry_count,
                    last_seen = excluded.last_seen,
                    representative_blob = excluded.representative_blob
                """,
                (
                    pattern_hash,
                    adapter_name,
                    raw_len,
                    raw_len,
                    compressed_bytes,
                    compressed_bytes,
                    1 if is_retry else 0,
                    now,
                    now,
                    new_blob,
                ),
            )
        else:
            # Upsert without touching the blob (preserve existing)
            await self._store._db.execute(
                """\
                INSERT INTO shadow_pattern_stats
                    (pattern_hash, adapter_name, sample_count, raw_bytes_sum,
                     raw_bytes_max, compressed_bytes_sum, compressed_bytes_max,
                     retry_count, first_seen, last_seen)
                VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pattern_hash, adapter_name) DO UPDATE SET
                    sample_count = sample_count + 1,
                    raw_bytes_sum = raw_bytes_sum + excluded.raw_bytes_sum,
                    raw_bytes_max = MAX(raw_bytes_max, excluded.raw_bytes_max),
                    compressed_bytes_sum = compressed_bytes_sum + excluded.compressed_bytes_sum,
                    compressed_bytes_max = MAX(compressed_bytes_max, excluded.compressed_bytes_max),
                    retry_count = retry_count + excluded.retry_count,
                    last_seen = excluded.last_seen
                """,
                (
                    pattern_hash,
                    adapter_name,
                    raw_len,
                    raw_len,
                    compressed_bytes,
                    compressed_bytes,
                    1 if is_retry else 0,
                    now,
                    now,
                ),
            )

        await self._store._db.commit()
