"""Tests for CompressionPipeline -- content-routed strategy chain.

TDD RED phase: these tests define the pipeline contract before implementation.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from token_sieve.domain.model import (
    CompressionEvent,
    ContentEnvelope,
    ContentType,
)


# ---------------------------------------------------------------------------
# Mock strategies for testing
# ---------------------------------------------------------------------------

class AlwaysCompressStrategy:
    """Mock strategy that always handles and prefixes content."""

    def __init__(self, prefix: str = "[compressed]") -> None:
        self._prefix = prefix

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        return True

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        return dataclasses.replace(
            envelope, content=f"{self._prefix} {envelope.content}"
        )


class NeverHandleStrategy:
    """Mock strategy that never handles any envelope."""

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        return False

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        raise AssertionError("compress should never be called")


class UpperCaseStrategy:
    """Mock strategy that uppercases content."""

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        return True

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        return dataclasses.replace(
            envelope, content=envelope.content.upper()
        )


# ---------------------------------------------------------------------------
# Mock token counter
# ---------------------------------------------------------------------------

class FakeTokenCounter:
    """Token counter that returns len(text) for predictable assertions."""

    def count(self, text: str) -> int:
        return len(text)


# ---------------------------------------------------------------------------
# Pipeline tests
# ---------------------------------------------------------------------------

class TestCompressionPipeline:
    """CompressionPipeline routes envelopes by ContentType through strategy chains."""

    def test_process_empty_pipeline_returns_input_unchanged(self):
        from token_sieve.domain.pipeline import CompressionPipeline

        counter = FakeTokenCounter()
        pipeline = CompressionPipeline(counter=counter)
        envelope = ContentEnvelope(content="hello", content_type=ContentType.TEXT)

        result_envelope, events = pipeline.process(envelope)

        assert result_envelope == envelope
        assert events == []

    def test_process_routes_by_content_type(self):
        from token_sieve.domain.pipeline import CompressionPipeline

        counter = FakeTokenCounter()
        pipeline = CompressionPipeline(counter=counter)
        text_strategy = AlwaysCompressStrategy(prefix="[text]")
        pipeline.register(ContentType.TEXT, text_strategy)

        # TEXT envelope should be processed
        text_env = ContentEnvelope(content="hello", content_type=ContentType.TEXT)
        result, events = pipeline.process(text_env)
        assert result.content == "[text] hello"
        assert len(events) == 1

        # JSON envelope should NOT be processed (no JSON route)
        json_env = ContentEnvelope(content='{"key": "val"}', content_type=ContentType.JSON)
        result, events = pipeline.process(json_env)
        assert result.content == '{"key": "val"}'
        assert events == []

    def test_process_chains_strategies_in_order(self):
        from token_sieve.domain.pipeline import CompressionPipeline

        counter = FakeTokenCounter()
        pipeline = CompressionPipeline(counter=counter)
        pipeline.register(ContentType.TEXT, AlwaysCompressStrategy(prefix="[first]"))
        pipeline.register(ContentType.TEXT, UpperCaseStrategy())

        envelope = ContentEnvelope(content="hello", content_type=ContentType.TEXT)
        result, events = pipeline.process(envelope)

        # First strategy prefixes, second uppercases the result
        assert result.content == "[FIRST] HELLO"
        assert len(events) == 2

    def test_process_returns_events(self):
        from token_sieve.domain.pipeline import CompressionPipeline

        counter = FakeTokenCounter()
        pipeline = CompressionPipeline(counter=counter)
        pipeline.register(ContentType.TEXT, AlwaysCompressStrategy(prefix="[c]"))

        envelope = ContentEnvelope(content="hello", content_type=ContentType.TEXT)
        result, events = pipeline.process(envelope)

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, CompressionEvent)
        assert event.strategy_name == "AlwaysCompressStrategy"
        assert event.content_type == ContentType.TEXT
        assert event.original_tokens == len("hello")  # FakeTokenCounter
        assert event.compressed_tokens == len("[c] hello")

    def test_process_skips_strategy_when_can_handle_false(self):
        from token_sieve.domain.pipeline import CompressionPipeline

        counter = FakeTokenCounter()
        pipeline = CompressionPipeline(counter=counter)
        pipeline.register(ContentType.TEXT, NeverHandleStrategy())
        pipeline.register(ContentType.TEXT, AlwaysCompressStrategy(prefix="[ok]"))

        envelope = ContentEnvelope(content="hello", content_type=ContentType.TEXT)
        result, events = pipeline.process(envelope)

        # NeverHandleStrategy skipped, only AlwaysCompressStrategy ran
        assert result.content == "[ok] hello"
        assert len(events) == 1
        assert events[0].strategy_name == "AlwaysCompressStrategy"

    def test_register_adds_strategy_to_route(self):
        from token_sieve.domain.pipeline import CompressionPipeline

        counter = FakeTokenCounter()
        pipeline = CompressionPipeline(counter=counter)

        s1 = AlwaysCompressStrategy()
        s2 = UpperCaseStrategy()
        pipeline.register(ContentType.TEXT, s1)
        pipeline.register(ContentType.TEXT, s2)
        pipeline.register(ContentType.JSON, s1)

        assert len(pipeline._routes[ContentType.TEXT]) == 2
        assert len(pipeline._routes[ContentType.JSON]) == 1

    def test_process_with_token_counter(self):
        """Pipeline uses injected TokenCounter for event token counts."""
        from token_sieve.domain.pipeline import CompressionPipeline

        counter = FakeTokenCounter()
        pipeline = CompressionPipeline(counter=counter)
        pipeline.register(ContentType.TEXT, AlwaysCompressStrategy(prefix="[c]"))

        envelope = ContentEnvelope(content="hi", content_type=ContentType.TEXT)
        _, events = pipeline.process(envelope)

        assert events[0].original_tokens == 2  # len("hi")
        assert events[0].compressed_tokens == 6  # len("[c] hi")


class TestPipelineIntegration:
    """Integration test: pipeline with real CharEstimateCounter."""

    def test_pipeline_with_char_estimate_counter(self):
        from token_sieve.domain.counters import CharEstimateCounter
        from token_sieve.domain.pipeline import CompressionPipeline

        counter = CharEstimateCounter()
        pipeline = CompressionPipeline(counter=counter)
        pipeline.register(ContentType.TEXT, AlwaysCompressStrategy(prefix="[compressed]"))

        # "hello world" = 11 chars -> CharEstimateCounter: max(1, 11//4) = 2
        envelope = ContentEnvelope(content="hello world", content_type=ContentType.TEXT)
        result, events = pipeline.process(envelope)

        assert result.content == "[compressed] hello world"
        assert len(events) == 1

        event = events[0]
        assert event.original_tokens == 2  # 11 chars -> 11//4 = 2
        # "[compressed] hello world" = 24 chars -> 24//4 = 6
        assert event.compressed_tokens == 6
        assert event.strategy_name == "AlwaysCompressStrategy"
        assert event.content_type == ContentType.TEXT
