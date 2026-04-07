"""Tests for the `deterministic` flag on the CompressionStrategy Protocol (D4b).

The flag is a class-level boolean attribute that defaults to True. Adapters
known to be non-deterministic can set ``deterministic = False`` and be
exempted by audit-style tests.

This wave only adds the *contract*; Phase 10 will fork code paths on it.
"""

from __future__ import annotations

from token_sieve.adapters.compression.passthrough import PassthroughStrategy
from token_sieve.domain.model import ContentEnvelope
from token_sieve.domain.ports import CompressionStrategy


def test_default_adapter_is_deterministic_true() -> None:
    """A vanilla adapter inherits ``deterministic = True``."""
    instance = PassthroughStrategy()
    assert hasattr(instance, "deterministic"), (
        "PassthroughStrategy must expose a `deterministic` attribute"
    )
    assert instance.deterministic is True


def test_protocol_declares_deterministic_attribute() -> None:
    """The Protocol must declare `deterministic` so static checkers see it."""
    assert "deterministic" in CompressionStrategy.__annotations__, (
        "CompressionStrategy Protocol must declare `deterministic` annotation"
    )


def test_adapter_can_override_deterministic_to_false() -> None:
    """Subclasses/duck-typed implementations can opt out by setting False."""

    class FakeNonDeterministicAdapter:
        deterministic = False

        def can_handle(self, envelope: ContentEnvelope) -> bool:
            return True

        def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
            return envelope

    adapter = FakeNonDeterministicAdapter()
    assert adapter.deterministic is False
    # Structural protocol satisfaction (duck-typed)
    assert hasattr(adapter, "can_handle")
    assert hasattr(adapter, "compress")
