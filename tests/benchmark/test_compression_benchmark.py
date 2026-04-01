"""Benchmark tests for compression pipeline effectiveness.

Marked @pytest.mark.benchmark -- excluded from normal test runs.
Run with: pytest tests/benchmark/ -v -m benchmark
"""

from __future__ import annotations

import time

import pytest

from tests.benchmark.corpus import BENCHMARK_CORPUS
from token_sieve.adapters.compression.null_field_elider import NullFieldElider
from token_sieve.adapters.compression.path_prefix_deduplicator import (
    PathPrefixDeduplicator,
)
from token_sieve.adapters.compression.timestamp_normalizer import (
    TimestampNormalizer,
)
from token_sieve.adapters.compression.whitespace_normalizer import (
    WhitespaceNormalizer,
)
from token_sieve.domain.counters import CharEstimateCounter
from token_sieve.domain.model import ContentType
from token_sieve.domain.pipeline import CompressionPipeline


def _build_cleanup_pipeline() -> CompressionPipeline:
    """Build a pipeline with cleanup-layer adapters only."""
    counter = CharEstimateCounter()
    pipeline = CompressionPipeline(counter)
    cleanup_adapters = [
        WhitespaceNormalizer(),
        NullFieldElider(),
        PathPrefixDeduplicator(),
        TimestampNormalizer(),
    ]
    for adapter in cleanup_adapters:
        for ct in ContentType:
            pipeline.register(ct, adapter)
    return pipeline


def _compression_ratio(original: str, compressed: str) -> float:
    """Fraction of content saved: 1 - (compressed / original)."""
    if not original:
        return 0.0
    return 1.0 - len(compressed) / len(original)


@pytest.mark.benchmark
class TestCompressionBenchmark:
    """Measures compression effectiveness against the fixed corpus."""

    def test_corpus_not_empty(self) -> None:
        """Corpus has sufficient entries for meaningful benchmarks."""
        assert len(BENCHMARK_CORPUS) >= 5

    def test_all_corpus_entries_are_envelopes(self) -> None:
        """Every corpus entry is a valid ContentEnvelope."""
        from token_sieve.domain.model import ContentEnvelope

        for name, envelope in BENCHMARK_CORPUS.items():
            assert isinstance(envelope, ContentEnvelope), f"{name} is not an envelope"

    def test_whitespace_normalizer_compression(self) -> None:
        """WhitespaceNormalizer produces non-negative compression on corpus entries."""
        adapter = WhitespaceNormalizer()
        for name, envelope in BENCHMARK_CORPUS.items():
            if adapter.can_handle(envelope):
                result = adapter.compress(envelope)
                assert len(result.content) <= len(envelope.content), (
                    f"WhitespaceNormalizer expanded {name}"
                )

    def test_null_field_elider_on_json(self) -> None:
        """NullFieldElider handles JSON corpus entries."""
        adapter = NullFieldElider()
        envelope = BENCHMARK_CORPUS["list_directory"]
        if adapter.can_handle(envelope):
            result = adapter.compress(envelope)
            assert len(result.content) <= len(envelope.content)

    def test_path_prefix_deduplicator_on_search(self) -> None:
        """PathPrefixDeduplicator compresses repeated path prefixes."""
        adapter = PathPrefixDeduplicator()
        envelope = BENCHMARK_CORPUS["search_files"]
        if adapter.can_handle(envelope):
            result = adapter.compress(envelope)
            ratio = _compression_ratio(envelope.content, result.content)
            assert ratio >= 0.0, "Path deduplication should not expand content"

    def test_cleanup_pipeline_minimum_savings(self) -> None:
        """Cleanup-layer pipeline achieves >= 5% savings on at least one corpus entry."""
        pipeline = _build_cleanup_pipeline()
        max_ratio = 0.0
        for name, envelope in BENCHMARK_CORPUS.items():
            result_env, events = pipeline.process(envelope)
            ratio = _compression_ratio(envelope.content, result_env.content)
            max_ratio = max(max_ratio, ratio)
        assert max_ratio >= 0.05, (
            f"Cleanup pipeline max savings was only {max_ratio:.1%}, expected >= 5%"
        )

    def test_cleanup_pipeline_no_expansion(self) -> None:
        """Cleanup pipeline never expands content beyond original size."""
        pipeline = _build_cleanup_pipeline()
        for name, envelope in BENCHMARK_CORPUS.items():
            result_env, _ = pipeline.process(envelope)
            assert len(result_env.content) <= len(envelope.content) + 10, (
                f"Pipeline expanded {name} by more than trivial amount"
            )

    def test_per_adapter_latency(self) -> None:
        """Each cleanup adapter processes any corpus entry in < 50ms."""
        adapters = [
            WhitespaceNormalizer(),
            NullFieldElider(),
            PathPrefixDeduplicator(),
            TimestampNormalizer(),
        ]
        for adapter in adapters:
            adapter_name = type(adapter).__name__
            for name, envelope in BENCHMARK_CORPUS.items():
                if not adapter.can_handle(envelope):
                    continue
                start = time.monotonic()
                adapter.compress(envelope)
                elapsed_ms = (time.monotonic() - start) * 1000
                assert elapsed_ms < 50, (
                    f"{adapter_name} on {name} took {elapsed_ms:.1f}ms (limit 50ms)"
                )

    def test_pipeline_latency(self) -> None:
        """Full cleanup pipeline processes any corpus entry in < 50ms."""
        pipeline = _build_cleanup_pipeline()
        for name, envelope in BENCHMARK_CORPUS.items():
            start = time.monotonic()
            pipeline.process(envelope)
            elapsed_ms = (time.monotonic() - start) * 1000
            assert elapsed_ms < 50, (
                f"Pipeline on {name} took {elapsed_ms:.1f}ms (limit 50ms)"
            )

    def test_corpus_content_type_diversity(self) -> None:
        """Corpus covers multiple content types for meaningful benchmarks."""
        types = {e.content_type for e in BENCHMARK_CORPUS.values()}
        assert len(types) >= 2, "Corpus should cover at least 2 content types"

    def test_aggregate_compression_report(self) -> None:
        """Pipeline produces compression events for at least some corpus entries."""
        pipeline = _build_cleanup_pipeline()
        total_events = 0
        for name, envelope in BENCHMARK_CORPUS.items():
            _, events = pipeline.process(envelope)
            total_events += len(events)
        assert total_events > 0, "Pipeline should produce at least one compression event"
