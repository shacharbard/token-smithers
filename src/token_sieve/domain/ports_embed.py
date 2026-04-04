"""Embedding port for semantic similarity computations.

Implementations should defer model loading until the first ``embed()`` call
since model initialisation is typically slow (e.g. downloading weights).
"""

from __future__ import annotations

from typing import Protocol


class EmbedderPort(Protocol):
    """Port for text-to-vector embedding adapters.

    Implementations produce fixed-dimension float vectors suitable for
    cosine-similarity comparisons in the semantic cache.

    Model loading should be deferred (lazy init on first ``embed`` call)
    to avoid blocking proxy startup.
    """

    def embed(self, text: str) -> list[float]:
        """Return a fixed-dimension float vector for *text*."""
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts, returning one vector per input."""
        ...

    @property
    def dimension(self) -> int:
        """Dimensionality of the embedding vectors produced."""
        ...
