"""Tests for MetricsFileWriter — periodic JSON flush to disk."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from token_sieve.domain.model import CompressionEvent, ContentType


class TestMetricsFileWriter:
    """MetricsFileWriter writes collector summary to JSON file."""

    def test_flush_writes_valid_json(self, tmp_path: Path) -> None:
        """flush() writes valid JSON containing session summary + breakdown."""
        from token_sieve.domain.metrics import InMemoryMetricsCollector
        from token_sieve.server.metrics_writer import MetricsFileWriter

        collector = InMemoryMetricsCollector()
        collector.record(
            CompressionEvent(
                original_tokens=200,
                compressed_tokens=80,
                strategy_name="whitespace",
                content_type=ContentType.TEXT,
            )
        )

        metrics_path = tmp_path / "metrics.json"
        writer = MetricsFileWriter(
            collector=collector, metrics_path=str(metrics_path)
        )
        writer.flush()

        data = json.loads(metrics_path.read_text())
        assert "session_summary" in data
        assert "strategy_breakdown" in data
        assert data["session_summary"]["event_count"] == 1

    def test_flush_after_threshold_events(self, tmp_path: Path) -> None:
        """Writer auto-flushes after configured event threshold."""
        from token_sieve.domain.metrics import InMemoryMetricsCollector
        from token_sieve.server.metrics_writer import MetricsFileWriter

        collector = InMemoryMetricsCollector()
        metrics_path = tmp_path / "metrics.json"
        writer = MetricsFileWriter(
            collector=collector,
            metrics_path=str(metrics_path),
            flush_every_n=3,
        )

        for i in range(3):
            event = CompressionEvent(
                original_tokens=100,
                compressed_tokens=50,
                strategy_name="test",
                content_type=ContentType.TEXT,
            )
            writer.record_and_maybe_flush(event)

        assert metrics_path.exists()
        data = json.loads(metrics_path.read_text())
        assert data["session_summary"]["event_count"] == 3

    def test_default_flush_every_n_is_one_so_first_event_writes_file(
        self, tmp_path: Path
    ) -> None:
        """Default flush_every_n must be 1 so the first event flushes to disk.

        Locks in the early-visibility default: a single CompressionEvent
        recorded via record_and_maybe_flush() must produce metrics.json on
        disk without any explicit flush() call.
        """
        from token_sieve.domain.metrics import InMemoryMetricsCollector
        from token_sieve.server.metrics_writer import MetricsFileWriter

        collector = InMemoryMetricsCollector()
        metrics_path = tmp_path / "m.json"
        writer = MetricsFileWriter(
            collector=collector, metrics_path=str(metrics_path)
        )

        # Lock in the default explicitly so future regressions are obvious.
        assert writer._flush_every_n == 1

        writer.record_and_maybe_flush(
            CompressionEvent(
                original_tokens=120,
                compressed_tokens=40,
                strategy_name="whitespace",
                content_type=ContentType.TEXT,
            )
        )

        assert metrics_path.exists()

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        """Writer creates parent directories if they don't exist."""
        from token_sieve.domain.metrics import InMemoryMetricsCollector
        from token_sieve.server.metrics_writer import MetricsFileWriter

        collector = InMemoryMetricsCollector()
        collector.record(
            CompressionEvent(
                original_tokens=100,
                compressed_tokens=50,
                strategy_name="test",
                content_type=ContentType.TEXT,
            )
        )

        metrics_path = tmp_path / "subdir" / "metrics.json"
        writer = MetricsFileWriter(
            collector=collector, metrics_path=str(metrics_path)
        )
        writer.flush()
        assert metrics_path.exists()


class TestMetricsFileWriterAtomicity:
    """H3: flush() must write atomically so concurrent readers never see torn JSON."""

    def test_concurrent_reader_never_sees_torn_json(self, tmp_path: Path) -> None:
        """A reader reading metrics.json while the writer is flushing must
        always observe valid JSON (never a zero-byte or partial file)."""
        from token_sieve.domain.metrics import InMemoryMetricsCollector
        from token_sieve.server.metrics_writer import MetricsFileWriter

        collector = InMemoryMetricsCollector()
        for _ in range(50):
            collector.record(
                CompressionEvent(
                    original_tokens=200,
                    compressed_tokens=80,
                    strategy_name="whitespace",
                    content_type=ContentType.TEXT,
                )
            )

        metrics_path = tmp_path / "metrics.json"
        writer = MetricsFileWriter(
            collector=collector, metrics_path=str(metrics_path)
        )
        # Seed the file so the reader has something to find.
        writer.flush()

        stop = threading.Event()
        errors: list[str] = []

        def writer_loop() -> None:
            while not stop.is_set():
                writer.flush()

        def reader_loop() -> None:
            while not stop.is_set():
                try:
                    text = metrics_path.read_text()
                except FileNotFoundError:
                    errors.append("file disappeared mid-write")
                    return
                if not text:
                    errors.append("read zero-byte file")
                    return
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as exc:
                    errors.append(f"torn JSON: {exc}")
                    return
                assert "session_summary" in data

        t_w = threading.Thread(target=writer_loop)
        t_r = threading.Thread(target=reader_loop)
        t_w.start()
        t_r.start()
        time.sleep(0.3)
        stop.set()
        t_w.join(timeout=2)
        t_r.join(timeout=2)

        assert not errors, f"reader saw torn reads: {errors[:3]}"

    def test_flush_uses_tmp_then_rename(self, tmp_path: Path, monkeypatch) -> None:
        """flush() must write to a .tmp sibling and os.replace() it into place.

        Assert by spying on os.replace and verifying the source path ends with .tmp
        and the destination is the target metrics path.
        """
        import os

        from token_sieve.domain.metrics import InMemoryMetricsCollector
        from token_sieve.server import metrics_writer as mw_module
        from token_sieve.server.metrics_writer import MetricsFileWriter

        collector = InMemoryMetricsCollector()
        collector.record(
            CompressionEvent(
                original_tokens=100,
                compressed_tokens=50,
                strategy_name="test",
                content_type=ContentType.TEXT,
            )
        )

        metrics_path = tmp_path / "metrics.json"
        writer = MetricsFileWriter(
            collector=collector, metrics_path=str(metrics_path)
        )

        calls: list[tuple[str, str]] = []
        real_replace = os.replace

        def spy_replace(src, dst):  # type: ignore[no-untyped-def]
            calls.append((str(src), str(dst)))
            return real_replace(src, dst)

        monkeypatch.setattr(mw_module.os, "replace", spy_replace)
        writer.flush()

        assert len(calls) == 1, "flush() must call os.replace exactly once"
        src, dst = calls[0]
        assert src.endswith(".tmp"), f"source must be tmp file, got {src}"
        assert dst == str(metrics_path)


class TestMetricsFileWriterConcurrentProcesses:
    """M4: concurrent proxies sharing a metrics.json must not corrupt it.

    On POSIX, ``flush()`` takes an ``fcntl.flock(LOCK_EX)`` on the tmp
    sibling before writing + ``os.replace()``. This serializes the
    atomic-write window across processes so last-writer-wins is
    acceptable but file corruption is not.

    Note: M4 was folded into the H3 commit earlier in this batch —
    the atomic-write path is the same code path that takes the lock.
    These tests are here to lock the concurrent-safety invariant in
    place so a future change can't regress it without noticing.
    """

    def test_two_writers_same_path_no_corruption(self, tmp_path: Path) -> None:
        """Two MetricsFileWriter instances writing the same path concurrently
        from threads must never leave a torn or zero-byte file on disk.

        Threads are a conservative proxy for processes here: the flock on
        POSIX is per-fd, and both threads open their own fd via os.open,
        so they race just like two processes would on the tmp sibling."""
        from token_sieve.domain.metrics import InMemoryMetricsCollector
        from token_sieve.server.metrics_writer import MetricsFileWriter

        metrics_path = tmp_path / "metrics.json"

        collector_a = InMemoryMetricsCollector()
        collector_b = InMemoryMetricsCollector()
        for _ in range(20):
            collector_a.record(
                CompressionEvent(
                    original_tokens=100,
                    compressed_tokens=40,
                    strategy_name="a",
                    content_type=ContentType.TEXT,
                )
            )
            collector_b.record(
                CompressionEvent(
                    original_tokens=200,
                    compressed_tokens=60,
                    strategy_name="b",
                    content_type=ContentType.TEXT,
                )
            )

        writer_a = MetricsFileWriter(collector_a, str(metrics_path))
        writer_b = MetricsFileWriter(collector_b, str(metrics_path))

        stop = threading.Event()
        errors: list[str] = []

        def loop(w: MetricsFileWriter) -> None:
            try:
                while not stop.is_set():
                    w.flush()
            except Exception as exc:  # pragma: no cover
                errors.append(repr(exc))

        t_a = threading.Thread(target=loop, args=(writer_a,))
        t_b = threading.Thread(target=loop, args=(writer_b,))
        t_a.start()
        t_b.start()
        time.sleep(0.3)
        stop.set()
        t_a.join(timeout=2)
        t_b.join(timeout=2)

        assert not errors, f"writers raised: {errors[:3]}"

        # Final state must be fully valid JSON from exactly one of the
        # writers (last-writer-wins). Either "a" or "b" should be the
        # winning strategy; no mixed/torn content.
        text = metrics_path.read_text()
        assert text, "final file is empty"
        data = json.loads(text)
        strategies = set(data["strategy_breakdown"].keys())
        assert strategies in ({"a"}, {"b"}), (
            f"expected exactly one writer's state, got {strategies}"
        )


class TestStatsReaderRetry:
    """H3: `ts stats` reader must retry on transient JSONDecodeError."""

    def test_stats_reader_retries_on_transient_json_error(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """If the first read returns a torn JSON, _run_stats retries and succeeds
        on a subsequent attempt (simulating a race with the writer)."""
        from token_sieve.cli import main as cli_main

        metrics_path = tmp_path / "metrics.json"
        # Write valid JSON to the file.
        metrics_path.write_text(
            json.dumps(
                {
                    "session_summary": {
                        "total_original_tokens": 100,
                        "total_compressed_tokens": 40,
                        "total_savings_ratio": 0.6,
                        "event_count": 1,
                    },
                    "strategy_breakdown": {},
                }
            )
        )
        monkeypatch.setenv("TOKEN_SIEVE_METRICS_PATH", str(metrics_path))

        # Patch Path.read_text on _this_ file: first 2 calls raise-equivalent
        # by returning a truncated string, 3rd returns real content.
        real_read_text = Path.read_text
        call_count = {"n": 0}

        def flaky_read_text(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            if str(self) == str(metrics_path):
                call_count["n"] += 1
                if call_count["n"] <= 2:
                    return "{partial"
            return real_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", flaky_read_text)

        rc = cli_main._run_stats(full=False)
        assert rc == 0
        assert call_count["n"] >= 3, (
            f"expected at least 3 reads (2 failures + 1 success), got {call_count['n']}"
        )
        captured = capsys.readouterr()
        assert "Token Smithers" in captured.out
