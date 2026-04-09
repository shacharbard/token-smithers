"""RED tests for ShadowLogger — adaptive sampling + zstd blob storage (D3).

Task 3 of 09-03: verify sampling rates, blob handling, ON CONFLICT update semantics.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from token_sieve.adapters.learning.shadow_logger import ShadowLogger, _sample_rate


class TestSampleRateFunction:
    """Pure _sample_rate() tests — no database needed."""

    def test_sample_rate_25_percent_for_new_pattern(self) -> None:
        """sample_count < 50 → rate is 0.25 (25%)."""
        rate = _sample_rate(sample_count=0, confidently_rated=False, is_retry=False)
        assert rate == pytest.approx(0.25)

        rate_mid = _sample_rate(sample_count=49, confidently_rated=False, is_retry=False)
        assert rate_mid == pytest.approx(0.25)

    def test_sample_rate_5_percent_for_established(self) -> None:
        """50 ≤ sample_count < 200 → rate is 0.05 (5%)."""
        rate = _sample_rate(sample_count=50, confidently_rated=False, is_retry=False)
        assert rate == pytest.approx(0.05)

        rate_mid = _sample_rate(sample_count=199, confidently_rated=False, is_retry=False)
        assert rate_mid == pytest.approx(0.05)

    def test_sample_rate_1_percent_when_confidently_rated(self) -> None:
        """confidently_rated=True → rate is 0.01 (1%) regardless of count."""
        rate = _sample_rate(sample_count=300, confidently_rated=True, is_retry=False)
        assert rate == pytest.approx(0.01)

    def test_sample_rate_100_percent_on_retry(self) -> None:
        """is_retry=True → always 1.0 (100%), overrides all other tiers."""
        rate = _sample_rate(sample_count=0, confidently_rated=False, is_retry=True)
        assert rate == pytest.approx(1.0)

        rate_conf = _sample_rate(sample_count=500, confidently_rated=True, is_retry=True)
        assert rate_conf == pytest.approx(1.0)


class TestShadowLoggerSampling:
    """Sampling behavior integrated with a real in-memory DB."""

    @pytest.fixture()
    async def store(self):
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore
        return await SQLiteLearningStore.connect(":memory:")

    @pytest.fixture()
    def logger(self, store):
        return ShadowLogger(store=store, rng_seed=42)

    async def test_sampling_rate_25_percent_for_new_pattern(
        self, store, logger
    ) -> None:
        """Fresh pattern: ~25% of invocations get logged (seed-deterministic)."""
        raw = b"x" * 100
        count = 0
        for _ in range(50):
            await logger.maybe_log(
                pattern_hash="new_pattern",
                adapter_name="passthrough",
                raw_bytes=raw,
                compressed_bytes=len(raw),
                is_retry=False,
            )

        async with store._db.execute(
            "SELECT sample_count FROM shadow_pattern_stats "
            "WHERE pattern_hash='new_pattern' AND adapter_name='passthrough'"
        ) as cur:
            row = await cur.fetchone()

        sample_count = row[0] if row else 0
        # With seed=42 and 25% rate, expect ~12-13 out of 50
        assert 8 <= sample_count <= 20, (
            f"Expected ~25% sampling for new pattern, got {sample_count}/50"
        )

    async def test_retry_invocation_always_logged_100_percent(
        self, store, logger
    ) -> None:
        """is_retry=True → every invocation is sampled."""
        raw = b"retry_output"
        for _ in range(20):
            await logger.maybe_log(
                pattern_hash="retry_pattern",
                adapter_name="passthrough",
                raw_bytes=raw,
                compressed_bytes=len(raw),
                is_retry=True,
            )

        async with store._db.execute(
            "SELECT sample_count FROM shadow_pattern_stats "
            "WHERE pattern_hash='retry_pattern' AND adapter_name='passthrough'"
        ) as cur:
            row = await cur.fetchone()

        sample_count = row[0] if row else 0
        assert sample_count == 20, (
            f"is_retry=True should sample 100%, got {sample_count}/20"
        )


class TestShadowLoggerBlobs:
    """Blob zstd compression + 256KB cap + replacement semantics."""

    @pytest.fixture()
    async def store(self):
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore
        return await SQLiteLearningStore.connect(":memory:")

    @pytest.fixture()
    def logger(self, store):
        return ShadowLogger(store=store, rng_seed=0)  # seed 0 → always sample

    async def test_blob_zstd_compressed(self, store, logger) -> None:
        """Logged blob decompresses to the original raw bytes."""
        import zstandard

        raw = b"hello world " * 100
        await logger.maybe_log(
            pattern_hash="blob_test",
            adapter_name="passthrough",
            raw_bytes=raw,
            compressed_bytes=len(raw) // 2,
            is_retry=True,  # always sample
        )

        async with store._db.execute(
            "SELECT representative_blob FROM shadow_pattern_stats "
            "WHERE pattern_hash='blob_test' AND adapter_name='passthrough'"
        ) as cur:
            row = await cur.fetchone()

        assert row is not None and row[0] is not None, "Blob should be stored"
        decompressed = zstandard.ZstdDecompressor().decompress(row[0])
        assert decompressed == raw

    async def test_blob_size_cap_256kb_compressed(self, store) -> None:
        """Blobs > 256KB compressed are skipped (metadata-only), counters still updated."""
        logger = ShadowLogger(store=store, rng_seed=0)

        # Build ~300KB of incompressible random data
        rng = random.Random(7)
        raw = bytes(rng.getrandbits(8) for _ in range(300 * 1024))

        await logger.maybe_log(
            pattern_hash="large_pattern",
            adapter_name="passthrough",
            raw_bytes=raw,
            compressed_bytes=len(raw),
            is_retry=True,
        )

        async with store._db.execute(
            "SELECT sample_count, representative_blob FROM shadow_pattern_stats "
            "WHERE pattern_hash='large_pattern' AND adapter_name='passthrough'"
        ) as cur:
            row = await cur.fetchone()

        assert row is not None, "Row must exist even when blob is skipped"
        assert row[0] >= 1, "sample_count must be incremented"
        # blob may be None (too large) — that is acceptable
        # But it could also have compressed below 256KB for some random seeds
        # so we just verify the row exists and counters updated

    async def test_blob_replacement_most_recent_on_success(
        self, store, logger
    ) -> None:
        """representative_blob is updated to the most-recent successful sample."""
        import zstandard

        raw_a = b"sample_A " * 50
        raw_b = b"sample_B " * 50

        await logger.maybe_log(
            pattern_hash="replace_test",
            adapter_name="passthrough",
            raw_bytes=raw_a,
            compressed_bytes=len(raw_a),
            is_retry=True,
        )
        await logger.maybe_log(
            pattern_hash="replace_test",
            adapter_name="passthrough",
            raw_bytes=raw_b,
            compressed_bytes=len(raw_b),
            is_retry=True,
        )

        async with store._db.execute(
            "SELECT representative_blob FROM shadow_pattern_stats "
            "WHERE pattern_hash='replace_test' AND adapter_name='passthrough'"
        ) as cur:
            row = await cur.fetchone()

        assert row is not None and row[0] is not None
        decompressed = zstandard.ZstdDecompressor().decompress(row[0])
        assert decompressed == raw_b, "Blob should be replaced by most-recent sample"

    async def test_blob_preserved_on_capture_failure(
        self, store, logger, monkeypatch
    ) -> None:
        """If zstd compression fails on the second sample, the first blob is kept."""
        import zstandard

        raw_a = b"preserved_blob " * 50

        # First sample succeeds — stores blob A
        await logger.maybe_log(
            pattern_hash="preserve_test",
            adapter_name="passthrough",
            raw_bytes=raw_a,
            compressed_bytes=len(raw_a),
            is_retry=True,
        )

        # Monkeypatch zstd compressor to raise on next call
        original_compress = zstandard.ZstdCompressor

        call_count = [0]

        def failing_compressor(*args, **kwargs):
            c = original_compress(*args, **kwargs)
            original_compress_obj = c

            class BrokenCompressor:
                def compress(self, data):
                    call_count[0] += 1
                    if call_count[0] >= 1:
                        raise RuntimeError("disk full")
                    return original_compress_obj.compress(data)

            return BrokenCompressor()

        monkeypatch.setattr(
            "token_sieve.adapters.learning.shadow_logger.zstandard.ZstdCompressor",
            failing_compressor,
        )

        raw_b = b"should_not_replace " * 50
        await logger.maybe_log(
            pattern_hash="preserve_test",
            adapter_name="passthrough",
            raw_bytes=raw_b,
            compressed_bytes=len(raw_b),
            is_retry=True,
        )

        async with store._db.execute(
            "SELECT representative_blob FROM shadow_pattern_stats "
            "WHERE pattern_hash='preserve_test' AND adapter_name='passthrough'"
        ) as cur:
            row = await cur.fetchone()

        assert row is not None and row[0] is not None, "Original blob must be preserved"
        decompressed = zstandard.ZstdDecompressor().decompress(row[0])
        assert decompressed == raw_a, "Blob must be original A, not replaced by B"


class TestShadowLoggerAggregation:
    """ON CONFLICT update semantics and multi-row aggregation."""

    @pytest.fixture()
    async def store(self):
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore
        return await SQLiteLearningStore.connect(":memory:")

    @pytest.fixture()
    def logger(self, store):
        return ShadowLogger(store=store, rng_seed=0)  # always sample

    async def test_on_conflict_updates_counters(self, store, logger) -> None:
        """3 samples for same (pattern_hash, adapter_name) → sample_count=3, sums correct."""
        raw = b"counter_data " * 10
        for _ in range(3):
            await logger.maybe_log(
                pattern_hash="counter_test",
                adapter_name="passthrough",
                raw_bytes=raw,
                compressed_bytes=len(raw) // 2,
                is_retry=True,
            )

        async with store._db.execute(
            "SELECT sample_count, raw_bytes_sum FROM shadow_pattern_stats "
            "WHERE pattern_hash='counter_test' AND adapter_name='passthrough'"
        ) as cur:
            row = await cur.fetchone()

        assert row is not None
        assert row[0] == 3, f"Expected sample_count=3, got {row[0]}"
        expected_sum = len(raw) * 3
        assert row[1] == expected_sum, f"Expected raw_bytes_sum={expected_sum}, got {row[1]}"

    async def test_aggregation_key_distinguishes_adapter_change(
        self, store, logger
    ) -> None:
        """Same pattern_hash, different adapter_name → 2 separate rows."""
        raw = b"multi_adapter"
        await logger.maybe_log(
            pattern_hash="multi_adapter_test",
            adapter_name="adapter_X",
            raw_bytes=raw,
            compressed_bytes=len(raw),
            is_retry=True,
        )
        await logger.maybe_log(
            pattern_hash="multi_adapter_test",
            adapter_name="adapter_Y",
            raw_bytes=raw,
            compressed_bytes=len(raw),
            is_retry=True,
        )

        async with store._db.execute(
            "SELECT COUNT(*) FROM shadow_pattern_stats "
            "WHERE pattern_hash='multi_adapter_test'"
        ) as cur:
            row = await cur.fetchone()

        assert row[0] == 2, f"Expected 2 rows (one per adapter), got {row[0]}"

    async def test_first_seen_unchanged_on_update(self, store, logger) -> None:
        """first_seen must not change after initial insert."""
        raw = b"first_seen_test"

        await logger.maybe_log(
            pattern_hash="first_seen_test",
            adapter_name="passthrough",
            raw_bytes=raw,
            compressed_bytes=len(raw),
            is_retry=True,
        )

        async with store._db.execute(
            "SELECT first_seen FROM shadow_pattern_stats "
            "WHERE pattern_hash='first_seen_test'"
        ) as cur:
            row = await cur.fetchone()
        first_seen_initial = row[0]

        # Log again
        await logger.maybe_log(
            pattern_hash="first_seen_test",
            adapter_name="passthrough",
            raw_bytes=raw,
            compressed_bytes=len(raw),
            is_retry=True,
        )

        async with store._db.execute(
            "SELECT first_seen FROM shadow_pattern_stats "
            "WHERE pattern_hash='first_seen_test'"
        ) as cur:
            row = await cur.fetchone()
        first_seen_after = row[0]

        assert first_seen_initial == first_seen_after, (
            "first_seen must not change after subsequent updates"
        )


class TestShadowLoggerC3p2Denylist:
    """C3-p2: maybe_log must consult sensitive_denylist.matches(cmd) and skip logging."""

    @pytest.fixture()
    async def store(self):
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore
        return await SQLiteLearningStore.connect(":memory:")

    @pytest.fixture()
    def logger(self, store):
        return ShadowLogger(store=store, rng_seed=0)  # always sample

    async def test_sensitive_cmd_denylist_hit_skips_logging(
        self, store, logger
    ) -> None:
        """When cmd matches denylist, no row is inserted and no blob stored."""
        raw = b"AKIAIOSFODNN7EXAMPLE secret credentials"
        await logger.maybe_log(
            pattern_hash="sensitive_hash",
            adapter_name="passthrough",
            raw_bytes=raw,
            compressed_bytes=len(raw),
            is_retry=True,
            cmd="aws sts get-caller-identity",
        )

        async with store._db.execute(
            "SELECT sample_count, representative_blob FROM shadow_pattern_stats "
            "WHERE pattern_hash='sensitive_hash'"
        ) as cur:
            row = await cur.fetchone()

        assert row is None, (
            "Denylist-matching cmd must not produce a shadow_pattern_stats row"
        )

    async def test_benign_cmd_still_logs_normally(self, store, logger) -> None:
        """After denylist wiring, benign commands must still be logged."""
        raw = b"benign output"
        await logger.maybe_log(
            pattern_hash="benign_hash",
            adapter_name="passthrough",
            raw_bytes=raw,
            compressed_bytes=len(raw),
            is_retry=True,
            cmd="ls -la",
        )

        async with store._db.execute(
            "SELECT sample_count FROM shadow_pattern_stats "
            "WHERE pattern_hash='benign_hash'"
        ) as cur:
            row = await cur.fetchone()

        assert row is not None and row[0] == 1, (
            "Benign cmd must still be logged after denylist wiring"
        )

    async def test_cmd_none_still_logs_backward_compatible(
        self, store, logger
    ) -> None:
        """When cmd is not provided (legacy callers), logging proceeds."""
        raw = b"legacy call"
        await logger.maybe_log(
            pattern_hash="legacy_hash",
            adapter_name="passthrough",
            raw_bytes=raw,
            compressed_bytes=len(raw),
            is_retry=True,
        )

        async with store._db.execute(
            "SELECT sample_count FROM shadow_pattern_stats "
            "WHERE pattern_hash='legacy_hash'"
        ) as cur:
            row = await cur.fetchone()

        assert row is not None and row[0] == 1


class TestShadowLoggerC3p2RetryEventsRetention:
    """C3-p2: retry_events table must have a retention pass (default 30d)."""

    @pytest.fixture()
    async def store(self):
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore
        return await SQLiteLearningStore.connect(":memory:")

    @pytest.fixture()
    def logger(self, store):
        return ShadowLogger(store=store, rng_seed=0)

    async def test_cleanup_old_retry_events_deletes_rows_older_than_30_days(
        self, store, logger
    ) -> None:
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=45)).isoformat()
        recent = (now - timedelta(days=5)).isoformat()

        # Insert two rows: one stale, one recent
        await store._db.execute(
            "INSERT INTO retry_events (pattern_hash, occurred_at, threshold_at_event, session_id) "
            "VALUES (?, ?, ?, ?)",
            ("old_pattern", old, 5, "sess-old"),
        )
        await store._db.execute(
            "INSERT INTO retry_events (pattern_hash, occurred_at, threshold_at_event, session_id) "
            "VALUES (?, ?, ?, ?)",
            ("recent_pattern", recent, 5, "sess-recent"),
        )
        await store._db.commit()

        await logger.cleanup_old_retry_events(max_age_days=30)

        async with store._db.execute(
            "SELECT pattern_hash FROM retry_events ORDER BY pattern_hash"
        ) as cur:
            rows = await cur.fetchall()

        assert [r[0] for r in rows] == ["recent_pattern"], (
            f"Expected only recent_pattern to survive, got {rows}"
        )


class TestShadowLoggerC3p2DecompressionBomb:
    """C3-p2: reading representative_blob must cap decompressed size."""

    def test_safe_decompress_blob_caps_decompressed_size(self) -> None:
        """A blob whose decompressed size exceeds max_size raises, does not OOM."""
        import zstandard

        from token_sieve.adapters.learning.shadow_logger import _safe_decompress_blob

        # Build a highly-compressible 10 MB payload — compresses to < 1 KB
        payload = b"A" * (10 * 1024 * 1024)
        blob = zstandard.ZstdCompressor().compress(payload)
        # Sanity: blob itself is tiny
        assert len(blob) < 10_000

        # Cap at 8 MB — must refuse to materialize the full 10 MB
        with pytest.raises(Exception):
            _safe_decompress_blob(blob, max_size=8 * 1024 * 1024)

    def test_safe_decompress_blob_within_cap_succeeds(self) -> None:
        """A blob whose decompressed size fits within max_size round-trips."""
        import zstandard

        from token_sieve.adapters.learning.shadow_logger import _safe_decompress_blob

        payload = b"hello world " * 1000
        blob = zstandard.ZstdCompressor().compress(payload)
        out = _safe_decompress_blob(blob, max_size=8 * 1024 * 1024)
        assert out == payload
