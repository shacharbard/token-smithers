"""Domain test fixtures: factory functions for value objects."""

from __future__ import annotations

import dataclasses

import pytest


@pytest.fixture
def make_envelope():
    """Factory fixture for ContentEnvelope instances."""

    def _factory(content="test content", content_type=None, metadata=None):
        from token_sieve.domain.model import ContentEnvelope, ContentType

        if content_type is None:
            content_type = ContentType.TEXT
        return ContentEnvelope(
            content=content,
            content_type=content_type,
            metadata=metadata or {},
        )

    return _factory


@pytest.fixture
def make_event():
    """Factory fixture for CompressionEvent instances."""

    def _factory(
        original_tokens=100,
        compressed_tokens=50,
        strategy_name="test_strategy",
        content_type=None,
        is_regret=False,
    ):
        from token_sieve.domain.model import CompressionEvent, ContentType

        if content_type is None:
            content_type = ContentType.TEXT
        return CompressionEvent(
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            strategy_name=strategy_name,
            content_type=content_type,
            is_regret=is_regret,
        )

    return _factory


@pytest.fixture
def make_budget():
    """Factory fixture for TokenBudget instances."""

    def _factory(total=1000, used=0):
        from token_sieve.domain.model import TokenBudget

        return TokenBudget(total=total, used=used)

    return _factory


@pytest.fixture
def mock_strategy():
    """A MockStrategy that satisfies CompressionStrategy Protocol.

    Always handles any envelope, returns it with '[compressed] ' prefix.
    """
    from token_sieve.domain.model import ContentEnvelope

    class MockStrategy:
        def can_handle(self, envelope: ContentEnvelope) -> bool:
            return True

        def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
            return dataclasses.replace(
                envelope, content=f"[compressed] {envelope.content}"
            )

    return MockStrategy()
