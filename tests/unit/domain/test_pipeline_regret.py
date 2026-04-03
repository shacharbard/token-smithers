"""Tests for negative compression detection and regret tracking."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from token_sieve.domain.model import ContentEnvelope, ContentType
from token_sieve.domain.pipeline import CompressionPipeline


def _make_counter() -> MagicMock:
    counter = MagicMock()
    counter.count = MagicMock(side_effect=lambda text: max(1, len(text) // 4))
    return counter


def _make_expanding_strategy(name: str) -> MagicMock:
    """Strategy that makes content LARGER (negative compression)."""
    strategy = MagicMock()
    strategy.__class__ = type(name, (), {})
    type(strategy).__name__ = name
    strategy.can_handle = MagicMock(return_value=True)

    def compress_side_effect(envelope: ContentEnvelope) -> ContentEnvelope:
        # Double the content = negative compression
        return ContentEnvelope(
            content=envelope.content * 2,
            content_type=envelope.content_type,
            metadata=envelope.metadata,
        )

    strategy.compress = MagicMock(side_effect=compress_side_effect)
    return strategy


def _make_shrinking_strategy(name: str) -> MagicMock:
    """Strategy that makes content smaller (positive compression)."""
    strategy = MagicMock()
    strategy.__class__ = type(name, (), {})
    type(strategy).__name__ = name
    strategy.can_handle = MagicMock(return_value=True)

    def compress_side_effect(envelope: ContentEnvelope) -> ContentEnvelope:
        return ContentEnvelope(
            content=envelope.content[:len(envelope.content) // 2] or "x",
            content_type=envelope.content_type,
            metadata=envelope.metadata,
        )

    strategy.compress = MagicMock(side_effect=compress_side_effect)
    return strategy


class TestNegativeCompressionDetection:
    """Pipeline detects and handles strategies that increase token count."""

    def test_expanding_strategy_marked_as_regret(self) -> None:
        """CompressionEvent has is_regret=True when compressed > original."""
        counter = _make_counter()
        pipeline = CompressionPipeline(counter=counter)

        expander = _make_expanding_strategy("BadAdapter")
        pipeline.register(ContentType.TEXT, expander)

        envelope = ContentEnvelope(
            content="x" * 200,
            content_type=ContentType.TEXT,
        )
        _, events = pipeline.process(envelope)

        assert len(events) == 1
        assert events[0].is_regret is True
        assert events[0].compressed_tokens > events[0].original_tokens

    def test_shrinking_strategy_not_regret(self) -> None:
        """Positive compression has is_regret=False."""
        counter = _make_counter()
        pipeline = CompressionPipeline(counter=counter)

        shrinker = _make_shrinking_strategy("GoodAdapter")
        pipeline.register(ContentType.TEXT, shrinker)

        envelope = ContentEnvelope(
            content="x" * 200,
            content_type=ContentType.TEXT,
        )
        _, events = pipeline.process(envelope)

        assert len(events) == 1
        assert events[0].is_regret is False

    def test_regret_reverts_envelope(self) -> None:
        """Expanding strategy's output is reverted — envelope unchanged."""
        counter = _make_counter()
        pipeline = CompressionPipeline(counter=counter)

        expander = _make_expanding_strategy("BadAdapter")
        shrinker = _make_shrinking_strategy("GoodAdapter")
        pipeline.register(ContentType.TEXT, expander)
        pipeline.register(ContentType.TEXT, shrinker)

        original_content = "y" * 200
        envelope = ContentEnvelope(
            content=original_content,
            content_type=ContentType.TEXT,
        )
        result, events = pipeline.process(envelope)

        # BadAdapter was reverted, GoodAdapter compressed the original
        assert len(events) == 2
        assert events[0].is_regret is True
        assert events[1].is_regret is False
        # Result should be smaller than original (GoodAdapter worked on original, not expanded)
        assert len(result.content) < len(original_content)

    def test_multiple_regrets_all_reverted(self) -> None:
        """Multiple expanding strategies are all reverted."""
        counter = _make_counter()
        pipeline = CompressionPipeline(counter=counter)

        e1 = _make_expanding_strategy("Expander1")
        e2 = _make_expanding_strategy("Expander2")
        pipeline.register(ContentType.TEXT, e1)
        pipeline.register(ContentType.TEXT, e2)

        envelope = ContentEnvelope(
            content="z" * 200,
            content_type=ContentType.TEXT,
        )
        result, events = pipeline.process(envelope)

        assert len(events) == 2
        assert all(e.is_regret for e in events)
        # Content unchanged — both reverted
        assert result.content == envelope.content
