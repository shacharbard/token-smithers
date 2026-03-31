"""Contract test base classes and shared fixtures for adapter tests.

CompressionStrategyContract and DeduplicationStrategyContract define
the minimum behavioral guarantees every adapter must satisfy.
Concrete test modules inherit from these and provide a fixture.
"""

from __future__ import annotations

import pytest

from token_sieve.domain.model import ContentEnvelope, ContentType
from token_sieve.domain.session import SessionContext


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def make_envelope():
    """Factory fixture for ContentEnvelope instances."""

    def _factory(
        content: str = "test content for adapter",
        content_type: ContentType = ContentType.TEXT,
        metadata: dict | None = None,
    ) -> ContentEnvelope:
        return ContentEnvelope(
            content=content,
            content_type=content_type,
            metadata=metadata or {},
        )

    return _factory


@pytest.fixture()
def make_session():
    """Factory fixture for SessionContext instances."""

    def _factory(session_id: str = "test-session-001") -> SessionContext:
        return SessionContext(session_id=session_id)

    return _factory


# ---------------------------------------------------------------------------
# Contract: CompressionStrategy
# ---------------------------------------------------------------------------


class CompressionStrategyContract:
    """Contract tests every CompressionStrategy adapter must pass.

    Subclass this AND provide a ``strategy`` fixture that returns
    the adapter under test.
    """

    def test_compress_returns_envelope(self, strategy, make_envelope):
        """compress() must return a ContentEnvelope."""
        envelope = make_envelope()
        result = strategy.compress(envelope)
        assert isinstance(result, ContentEnvelope)

    def test_can_handle_returns_bool(self, strategy, make_envelope):
        """can_handle() must return a bool."""
        envelope = make_envelope()
        result = strategy.can_handle(envelope)
        assert isinstance(result, bool)

    def test_compress_preserves_content_type(self, strategy, make_envelope):
        """compress() must not change the content_type."""
        for ct in ContentType:
            envelope = make_envelope(content_type=ct)
            if strategy.can_handle(envelope):
                result = strategy.compress(envelope)
                assert result.content_type == ct

    def test_compress_nonempty_content(self, strategy, make_envelope):
        """compress() must produce non-empty content."""
        envelope = make_envelope(content="some meaningful text to compress")
        if strategy.can_handle(envelope):
            result = strategy.compress(envelope)
            assert result.content  # non-empty string


# ---------------------------------------------------------------------------
# Contract: DeduplicationStrategy
# ---------------------------------------------------------------------------


class DeduplicationStrategyContract:
    """Contract tests every DeduplicationStrategy adapter must pass.

    Subclass this AND provide a ``dedup_strategy`` fixture that returns
    the adapter under test.
    """

    def test_is_duplicate_returns_bool(self, dedup_strategy, make_envelope, make_session):
        """is_duplicate() must return a bool."""
        envelope = make_envelope()
        session = make_session()
        result = dedup_strategy.is_duplicate(envelope, session)
        assert isinstance(result, bool)

    def test_get_reference_returns_str(self, dedup_strategy, make_envelope, make_session):
        """get_reference() must return a str."""
        envelope = make_envelope()
        session = make_session()
        result = dedup_strategy.get_reference(envelope, session)
        assert isinstance(result, str)

    def test_first_call_not_duplicate(self, dedup_strategy, make_envelope, make_session):
        """The very first call for any content must not be a duplicate."""
        envelope = make_envelope(content="unique content never seen before")
        session = make_session()
        assert dedup_strategy.is_duplicate(envelope, session) is False
