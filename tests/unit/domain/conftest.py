"""Domain test fixtures: factory functions for value objects."""

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
    ):
        from token_sieve.domain.model import CompressionEvent, ContentType

        if content_type is None:
            content_type = ContentType.TEXT
        return CompressionEvent(
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            strategy_name=strategy_name,
            content_type=content_type,
        )

    return _factory
