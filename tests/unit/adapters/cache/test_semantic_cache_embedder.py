"""Tests for Model2Vec embedder wiring into SQLiteSemanticCache.

Verifies:
- SQLiteSemanticCache accepts optional embedder param
- When embedder is provided, lookup_similar uses cosine similarity
- SemanticCacheConfig.embedder field validates correctly
- _DeferredSemanticCache creates embedder when config specifies it
"""
from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest


class TestSemanticCacheWithEmbedder:
    """SQLiteSemanticCache uses embedder for similarity when provided."""

    @pytest.mark.asyncio
    async def test_accepts_embedder_param(self) -> None:
        """SQLiteSemanticCache.__init__ accepts optional embedder."""
        from token_sieve.adapters.cache.semantic_cache import SQLiteSemanticCache

        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [1.0, 0.0, 0.0]
        mock_embedder.dimension = 3

        cache = SQLiteSemanticCache(
            db_path=":memory:",
            embedder=mock_embedder,
        )
        await cache.initialize()
        assert cache._embedder is mock_embedder
        await cache.close()

    @pytest.mark.asyncio
    async def test_lookup_uses_cosine_similarity_with_embedder(self) -> None:
        """When embedder is set, fuzzy lookup uses cosine similarity."""
        from token_sieve.adapters.cache.semantic_cache import SQLiteSemanticCache

        # Create mock embedder that returns known vectors
        mock_embedder = MagicMock()
        mock_embedder.dimension = 3
        # Embed for cache_result: query=[1,0,0]
        # Embed for lookup:       query=[0.9,0.1,0]  (high similarity)
        mock_embedder.embed.side_effect = [
            [1.0, 0.0, 0.0],  # cache_result call
            [0.9, 0.1, 0.0],  # lookup call
        ]

        cache = SQLiteSemanticCache(
            db_path=":memory:",
            embedder=mock_embedder,
        )
        await cache.initialize()

        # Store a result
        await cache.cache_result(
            tool_name="test_tool",
            args_normalized='{"key": "value"}',
            args_hash="abc123",
            result="cached result text",
        )

        # Lookup with similar args (should use cosine similarity)
        hit = await cache.lookup_similar(
            tool_name="test_tool",
            args_normalized='{"key": "similar_value"}',
            threshold=0.8,
        )

        assert hit is not None
        assert hit.result_text == "cached result text"
        # Cosine similarity of [1,0,0] and [0.9,0.1,0] ≈ 0.994
        assert hit.similarity_score > 0.9

        await cache.close()

    @pytest.mark.asyncio
    async def test_fallback_to_sequence_matcher_without_embedder(self) -> None:
        """Without embedder, fuzzy lookup uses SequenceMatcher (existing behavior)."""
        from token_sieve.adapters.cache.semantic_cache import SQLiteSemanticCache

        cache = SQLiteSemanticCache(db_path=":memory:")
        await cache.initialize()

        # Store a result
        await cache.cache_result(
            tool_name="test_tool",
            args_normalized='{"key": "value"}',
            args_hash="abc123",
            result="cached result text",
        )

        # Lookup with identical args (should still work via SequenceMatcher)
        hit = await cache.lookup_similar(
            tool_name="test_tool",
            args_normalized='{"key": "value"}',
            threshold=0.99,
        )

        assert hit is not None
        assert hit.result_text == "cached result text"

        await cache.close()


class TestSemanticCacheConfigEmbedder:
    """SemanticCacheConfig.embedder field validates correctly."""

    def test_embedder_field_default_none(self) -> None:
        from token_sieve.config.schema import SemanticCacheConfig

        config = SemanticCacheConfig()
        assert config.embedder is None

    def test_embedder_field_accepts_model2vec(self) -> None:
        from token_sieve.config.schema import SemanticCacheConfig

        config = SemanticCacheConfig(embedder="model2vec")
        assert config.embedder == "model2vec"


class TestDeferredSemanticCacheEmbedder:
    """_DeferredSemanticCache creates embedder when config specifies it."""

    @pytest.mark.asyncio
    async def test_deferred_cache_with_embedder_config(self) -> None:
        """When embedder='model2vec' in config, deferred cache passes embedder."""
        from token_sieve.server.proxy import _DeferredSemanticCache

        deferred = _DeferredSemanticCache(
            max_entries=100,
            ttl_seconds=3600,
            similarity_threshold=0.85,
            embedder_name="model2vec",
        )
        assert deferred._embedder_name == "model2vec"

    def test_deferred_cache_without_embedder(self) -> None:
        """Default deferred cache has no embedder."""
        from token_sieve.server.proxy import _DeferredSemanticCache

        deferred = _DeferredSemanticCache()
        assert deferred._embedder_name is None
