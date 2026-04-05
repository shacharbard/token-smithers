"""Model2Vec embedder adapter — fast CPU-friendly static embeddings.

Uses ``model2vec`` distilled static embeddings (8MB model) which are
~500x faster on CPU than sentence-transformers. The model is loaded
lazily on the first ``embed()`` call to avoid blocking proxy startup.
"""

from __future__ import annotations

import threading

_DEFAULT_MODEL = "minishlab/potion-base-8M"


class Model2VecEmbedder:
    """EmbedderPort implementation backed by model2vec static embeddings.

    Raises ``ImportError`` at construction time if ``model2vec`` is not
    installed, with a helpful message pointing to the optional extra.

    The model is loaded on the first ``embed()`` call (deferred pattern).
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        try:
            import model2vec  # noqa: F401
        except ImportError:
            raise ImportError(
                "model2vec is required for Model2VecEmbedder. "
                "Install with: pip install 'token-smithers[embeddings]'"
            ) from None
        self._model_name = model_name
        self._model: object | None = None
        self._dimension: int | None = None
        # H10 fix: guard against double loading from concurrent async tasks
        self._load_lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        """Load the model on first use (deferred init)."""
        if self._model is not None:
            return
        with self._load_lock:
            # Double-check after acquiring lock
            if self._model is not None:
                return
            from model2vec import StaticModel

            self._model = StaticModel.from_pretrained(self._model_name)
            # Probe dimension from a test embedding
            probe = self._model.encode("")
            self._dimension = len(probe)

    def embed(self, text: str) -> list[float]:
        """Return a fixed-dimension float vector for *text*."""
        self._ensure_loaded()
        vec = self._model.encode(text)
        return [float(v) for v in vec]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts, returning one vector per input."""
        self._ensure_loaded()
        matrix = self._model.encode(texts)
        return [[float(v) for v in row] for row in matrix]

    @property
    def dimension(self) -> int:
        """Dimensionality of the embedding vectors produced."""
        self._ensure_loaded()
        assert self._dimension is not None
        return self._dimension

    def __repr__(self) -> str:
        dim = self._dimension if self._dimension is not None else "?"
        return f"Model2VecEmbedder(model={self._model_name!r}, dim={dim})"
