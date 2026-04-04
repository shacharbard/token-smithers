"""Contract tests for EmbedderPort Protocol."""

from __future__ import annotations

import pytest

from token_sieve.domain.ports_embed import EmbedderPort


class FakeEmbedder:
    """Stub embedder for contract verification."""

    def __init__(self, dim: int = 8) -> None:
        self._dim = dim

    def embed(self, text: str) -> list[float]:
        """Hash-based deterministic embedding."""
        h = hash(text) & 0xFFFFFFFF
        return [float((h >> (i * 4)) & 0xF) / 15.0 for i in range(self._dim)]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    @property
    def dimension(self) -> int:
        return self._dim


class EmbedderPortContract:
    """Contract test base for EmbedderPort implementations.

    Subclass and provide an ``embedder`` fixture returning a concrete
    EmbedderPort implementation.
    """

    @pytest.fixture
    def embedder(self) -> EmbedderPort:
        raise NotImplementedError

    def test_embed_returns_list_of_float(self, embedder: EmbedderPort) -> None:
        result = embedder.embed("hello world")
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(v, float) for v in result)

    def test_embed_dimension_matches(self, embedder: EmbedderPort) -> None:
        result = embedder.embed("test text")
        assert len(result) == embedder.dimension

    def test_embed_batch_returns_correct_shape(
        self, embedder: EmbedderPort
    ) -> None:
        texts = ["first", "second", "third"]
        results = embedder.embed_batch(texts)
        assert len(results) == 3
        for vec in results:
            assert len(vec) == embedder.dimension
            assert all(isinstance(v, float) for v in vec)

    def test_embed_empty_string_no_crash(self, embedder: EmbedderPort) -> None:
        result = embedder.embed("")
        assert isinstance(result, list)
        assert len(result) == embedder.dimension

    def test_identical_texts_produce_identical_embeddings(
        self, embedder: EmbedderPort
    ) -> None:
        v1 = embedder.embed("determinism check")
        v2 = embedder.embed("determinism check")
        assert v1 == v2


class TestFakeEmbedderContract(EmbedderPortContract):
    """Run contract tests against FakeEmbedder stub."""

    @pytest.fixture
    def embedder(self) -> EmbedderPort:
        return FakeEmbedder(dim=8)
