"""Tests for domain model value objects."""

from __future__ import annotations


def test_can_import_content_envelope():
    """Smoke test: ContentEnvelope is importable from domain.model."""
    from token_sieve.domain.model import ContentEnvelope

    assert ContentEnvelope is not None
