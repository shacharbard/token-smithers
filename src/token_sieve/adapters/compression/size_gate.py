"""SizeGate -- skip compression for small results.

Tier 0 gate: results under a configurable token threshold pass through
unchanged. Prevents unnecessary processing of already-small content
(e.g., pre-compressed results from jCodeMunch/context-mode backends).
"""

from __future__ import annotations

from token_sieve.domain.counters import CharEstimateCounter
from token_sieve.domain.model import ContentEnvelope

# Default threshold in estimated tokens — synced with schema.py CompressionConfig
_DEFAULT_THRESHOLD = 500


class SizeGate:
    """CompressionStrategy that gates on content size.

    can_handle() returns False for content below the token threshold,
    causing the pipeline to skip this strategy. compress() returns
    content unchanged (it's a gate, not a transform).

    Satisfies CompressionStrategy protocol structurally.
    """

    deterministic = True

    def __init__(
        self,
        threshold: int = _DEFAULT_THRESHOLD,
        counter: object | None = None,
    ) -> None:
        self.threshold = threshold
        self._counter = counter or CharEstimateCounter()

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Return True only when content exceeds the token threshold."""
        token_count = self._counter.count(envelope.content)
        return token_count > self.threshold

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Return content unchanged -- SizeGate is a gate, not a transform."""
        return envelope


def should_compress(
    envelope: ContentEnvelope,
    counter: object,
    threshold: int = _DEFAULT_THRESHOLD,
) -> bool:
    """Utility function: check if content is large enough to warrant compression.

    Returns True if estimated token count exceeds threshold.
    Can be called before running the pipeline to skip it entirely.
    """
    token_count = counter.count(envelope.content)
    return token_count > threshold
