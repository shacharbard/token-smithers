"""Phase 07 integration tests.

Validates end-to-end behavior across Plans 01-05:
deterministic pipeline output, reranker stability,
session report generation, and suggestion candidates.
"""

from __future__ import annotations

import pytest

from token_sieve.domain.counters import CharEstimateCounter
from token_sieve.domain.model import ContentEnvelope, ContentType, CompressionEvent
from token_sieve.domain.pipeline import CompressionPipeline


@pytest.mark.integration
class TestDeterministicPipelineOutput:
    """Pipeline produces byte-identical output for same input."""

    def test_deterministic_pipeline_output(self) -> None:
        """Run same input through full pipeline twice, assert identical output."""
        from token_sieve.adapters.compression.whitespace_normalizer import (
            WhitespaceNormalizer,
        )

        counter = CharEstimateCounter()
        pipeline = CompressionPipeline(counter=counter)
        pipeline.register(ContentType.TEXT, WhitespaceNormalizer())

        input_text = "hello   world\n\n\nfoo   bar   baz\n\n"
        envelope = ContentEnvelope(content=input_text, content_type=ContentType.TEXT)

        result1, events1 = pipeline.process(envelope)
        result2, events2 = pipeline.process(envelope)

        assert result1.content == result2.content
        assert len(events1) == len(events2)
        for e1, e2 in zip(events1, events2):
            assert e1.original_tokens == e2.original_tokens
            assert e1.compressed_tokens == e2.compressed_tokens


@pytest.mark.integration
class TestRerankerFrozenStability:
    """Reranker frozen order is stable across multiple calls."""

    def test_frozen_order_stable(self) -> None:
        """Create reranker, freeze, call transform() multiple times."""
        from token_sieve.adapters.rerank.statistical_reranker import StatisticalReranker
        from token_sieve.domain.tool_metadata import ToolMetadata

        reranker = StatisticalReranker()

        # Record varied usage
        for _ in range(10):
            reranker.record_call("tool_a")
        for _ in range(5):
            reranker.record_call("tool_b")
        for _ in range(3):
            reranker.record_call("tool_c")

        reranker.freeze()

        tools = [
            ToolMetadata(name="tool_c", title=None, description="c"),
            ToolMetadata(name="tool_a", title=None, description="a"),
            ToolMetadata(name="tool_b", title=None, description="b"),
        ]

        results = []
        for _ in range(5):
            result = reranker.transform(tools)
            results.append([t.name for t in result])

        # All 5 calls should produce identical ordering
        for r in results[1:]:
            assert r == results[0]

        # Most-used (tool_a) should be first
        assert results[0][0] == "tool_a"


@pytest.mark.integration
class TestSessionReportEndToEnd:
    """Full session report generation from learning store data."""

    @pytest.mark.asyncio
    async def test_session_report_end_to_end(self) -> None:
        """Run a mini session, generate report, verify sections."""
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        store = await SQLiteLearningStore.connect(":memory:")

        try:
            session_id = "test-integration-session"

            # Simulate tool calls with compression events
            for i in range(3):
                event = CompressionEvent(
                    original_tokens=1000,
                    compressed_tokens=600,
                    strategy_name="whitespace",
                    content_type=ContentType.TEXT,
                )
                await store.record_compression_event(session_id, event, "read_file")

            for i in range(2):
                event = CompressionEvent(
                    original_tokens=500,
                    compressed_tokens=200,
                    strategy_name="null_elider",
                    content_type=ContentType.JSON,
                )
                await store.record_compression_event(session_id, event, "grep")

            # Generate report
            report = await store.get_session_report(session_id)

            assert report["totals"]["event_count"] == 5
            assert report["totals"]["total_original"] == 3 * 1000 + 2 * 500
            assert report["totals"]["total_compressed"] == 3 * 600 + 2 * 200

            # Verify tool breakdown
            tools = {t["tool_name"]: t for t in report["tool_breakdown"]}
            assert "read_file" in tools
            assert "grep" in tools

            # Verify strategy breakdown
            strategies = {s["strategy_name"]: s for s in report["strategy_breakdown"]}
            assert "whitespace" in strategies
            assert "null_elider" in strategies

            # Adapter effectiveness
            adapters = await store.get_adapter_effectiveness(limit=5)
            assert len(adapters) == 2

            # Savings trend
            trend = await store.get_savings_trend(sessions=5)
            assert len(trend) == 1
            assert trend[0]["session_id"] == session_id
        finally:
            await store.close()


@pytest.mark.integration
class TestSuggestionCandidates:
    """Suggestion generation integration test."""

    @pytest.mark.asyncio
    async def test_suggestions_from_repeated_patterns(self) -> None:
        """Repeated tool calls generate CLAUDE.md suggestions."""
        from token_sieve.adapters.learning.sqlite_store import SQLiteLearningStore

        store = await SQLiteLearningStore.connect(":memory:")

        try:
            session_id = "suggestion-test"

            # 6 calls to same tool = should trigger repeated_tool
            for _ in range(6):
                event = CompressionEvent(
                    original_tokens=500,
                    compressed_tokens=300,
                    strategy_name="whitespace",
                    content_type=ContentType.TEXT,
                )
                await store.record_compression_event(session_id, event, "read_file")

            suggestions = await store.get_suggestion_candidates(session_id)

            # Should have both repeated_tool and repeated_content
            types = {s["type"] for s in suggestions}
            assert "repeated_tool" in types
            assert "repeated_content" in types

            for s in suggestions:
                assert "CLAUDE.md" in s["suggestion"]
        finally:
            await store.close()
