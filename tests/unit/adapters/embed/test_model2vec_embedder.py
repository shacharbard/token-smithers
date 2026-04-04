"""Tests for Model2VecEmbedder adapter."""

from __future__ import annotations

import importlib.util
import math
import sys

import pytest

from tests.unit.domain.test_ports_embed import EmbedderPortContract
from token_sieve.adapters.embed.model2vec_embedder import Model2VecEmbedder

_MODEL2VEC_AVAILABLE = importlib.util.find_spec("model2vec") is not None


class TestModel2VecEmbedderImportGuard:
    """Test graceful handling when model2vec is not installed."""

    @pytest.mark.skipif(_MODEL2VEC_AVAILABLE, reason="model2vec is installed")
    def test_raises_import_error_without_model2vec(self) -> None:
        with pytest.raises(ImportError, match="model2vec"):
            Model2VecEmbedder()


@pytest.mark.skipif(not _MODEL2VEC_AVAILABLE, reason="model2vec not installed")
class TestModel2VecEmbedderContract(EmbedderPortContract):
    """Run contract tests against real Model2VecEmbedder."""

    @pytest.fixture
    def embedder(self) -> Model2VecEmbedder:
        return Model2VecEmbedder()


@pytest.mark.skipif(not _MODEL2VEC_AVAILABLE, reason="model2vec not installed")
class TestModel2VecEmbedder:
    """Functional tests for Model2VecEmbedder."""

    def test_embed_returns_vector(self) -> None:
        embedder = Model2VecEmbedder()
        result = embedder.embed("hello world")
        assert isinstance(result, list)
        assert len(result) == embedder.dimension
        assert all(isinstance(v, float) for v in result)

    def test_embed_batch_consistent(self) -> None:
        embedder = Model2VecEmbedder()
        texts = ["hello world", "goodbye moon"]
        batch_results = embedder.embed_batch(texts)
        individual_results = [embedder.embed(t) for t in texts]
        for batch_vec, ind_vec in zip(batch_results, individual_results):
            assert batch_vec == ind_vec

    def test_cosine_similarity_sensible(self) -> None:
        embedder = Model2VecEmbedder()
        v_python = embedder.embed("Python programming language")
        v_coding = embedder.embed("coding in Python with pytest")
        v_food = embedder.embed("delicious Italian pizza recipe")

        def cosine_sim(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot / (norm_a * norm_b)

        sim_related = cosine_sim(v_python, v_coding)
        sim_unrelated = cosine_sim(v_python, v_food)
        assert sim_related > sim_unrelated, (
            f"Similar texts ({sim_related:.3f}) should score higher "
            f"than dissimilar ({sim_unrelated:.3f})"
        )

    def test_repr(self) -> None:
        embedder = Model2VecEmbedder()
        r = repr(embedder)
        assert "Model2VecEmbedder" in r
        assert str(embedder.dimension) in r
