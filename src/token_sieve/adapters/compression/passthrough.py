"""PassthroughStrategy -- no-op compression adapter.

Returns the envelope unchanged. Useful as a default strategy when
no compression is desired, or as a baseline for benchmarking.
"""

from __future__ import annotations

from token_sieve.domain.model import ContentEnvelope


class PassthroughStrategy:
    """No-op compression: returns the envelope unchanged.

    Satisfies CompressionStrategy protocol structurally.
    """

    deterministic: bool = True  # D4b: passthrough trivially preserves bytes

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Accept all content types."""
        return True

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Return the envelope unchanged."""
        return envelope
