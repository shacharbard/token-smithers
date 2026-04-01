"""Contract tests for SemanticCachePort Protocol."""

from __future__ import annotations

import pytest

from token_sieve.domain.ports_cache import CacheHit, SemanticCachePort


class SemanticCacheContract:
    """Contract test base for SemanticCachePort implementations.

    Subclass and provide a ``strategy`` fixture returning a concrete
    SemanticCachePort implementation.
    """

    @pytest.fixture
    def strategy(self) -> SemanticCachePort:
        raise NotImplementedError

    @pytest.mark.asyncio
    async def test_lookup_on_empty_returns_none(
        self, strategy: SemanticCachePort
    ) -> None:
        result = await strategy.lookup_similar("read_file", '{"path":"/a"}', 0.85)
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_then_exact_lookup(
        self, strategy: SemanticCachePort
    ) -> None:
        await strategy.cache_result(
            "read_file", '{"path":"/a"}', "hash_a", "file content"
        )
        hit = await strategy.lookup_similar("read_file", '{"path":"/a"}', 0.85)
        assert hit is not None
        assert isinstance(hit, CacheHit)
        assert hit.result_text == "file content"
        assert hit.similarity_score >= 0.85

    @pytest.mark.asyncio
    async def test_cache_then_similar_lookup_above_threshold(
        self, strategy: SemanticCachePort
    ) -> None:
        # Near-identical args (minor whitespace diff) should match
        await strategy.cache_result(
            "read_file", '{"path": "/src/main.py"}', "hash_b", "main content"
        )
        # Slightly different normalized form (no space after colon)
        hit = await strategy.lookup_similar(
            "read_file", '{"path":"/src/main.py"}', 0.85
        )
        assert hit is not None
        assert hit.result_text == "main content"
        assert hit.similarity_score >= 0.85

    @pytest.mark.asyncio
    async def test_below_threshold_returns_none(
        self, strategy: SemanticCachePort
    ) -> None:
        await strategy.cache_result(
            "read_file", '{"path":"/completely/different"}', "hash_c", "other"
        )
        hit = await strategy.lookup_similar(
            "read_file", '{"path":"/totally/unrelated/file.txt"}', 0.95
        )
        assert hit is None

    @pytest.mark.asyncio
    async def test_evict_expired_on_empty(
        self, strategy: SemanticCachePort
    ) -> None:
        count = await strategy.evict_expired()
        assert count == 0

    @pytest.mark.asyncio
    async def test_different_tool_no_cross_match(
        self, strategy: SemanticCachePort
    ) -> None:
        await strategy.cache_result(
            "read_file", '{"path":"/a"}', "hash_d", "content"
        )
        hit = await strategy.lookup_similar("write_file", '{"path":"/a"}', 0.85)
        assert hit is None


class TestCacheHitFrozen:
    """CacheHit is a frozen dataclass with hashable fields."""

    def test_frozen(self) -> None:
        hit = CacheHit(result_text="data", similarity_score=0.95, hit_count=1)
        with pytest.raises(AttributeError):
            hit.result_text = "changed"  # type: ignore[misc]

    def test_hashable_fields(self) -> None:
        hit = CacheHit(result_text="data", similarity_score=0.95, hit_count=1)
        # All fields are hashable scalars
        assert isinstance(hit.result_text, str)
        assert isinstance(hit.similarity_score, float)
        assert isinstance(hit.hit_count, int)


class TestSemanticCachePortIsProtocol:
    """SemanticCachePort is a runtime-checkable Protocol."""

    def test_protocol_is_runtime_checkable(self) -> None:
        assert hasattr(SemanticCachePort, "__protocol_attrs__") or hasattr(
            SemanticCachePort, "_is_protocol"
        )
