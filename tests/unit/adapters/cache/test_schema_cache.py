"""Tests for SchemaCache adapter.

Verifies TTL-based caching of tools/list responses, concurrent safety,
and invalidation behavior.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from token_sieve.adapters.cache.schema_cache import SchemaCache
from token_sieve.domain.ports_mcp import ToolListProvider
from token_sieve.domain.tool_metadata import ToolMetadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool(name: str) -> ToolMetadata:
    return ToolMetadata(
        name=name,
        title=None,
        description=f"Tool {name}",
        input_schema={"type": "object"},
    )


def _mock_provider(tools: list[ToolMetadata] | None = None) -> AsyncMock:
    """Create an AsyncMock that satisfies ToolListProvider."""
    provider = AsyncMock(spec=ToolListProvider)
    provider.list_tools.return_value = tools or [_tool("default")]
    return provider


# ---------------------------------------------------------------------------
# Basic caching
# ---------------------------------------------------------------------------


class TestBasicCaching:
    """SchemaCache delegates on miss and returns cached on hit."""

    @pytest.mark.asyncio
    async def test_first_call_delegates_to_provider(self) -> None:
        """First call should delegate to the wrapped provider."""
        provider = _mock_provider([_tool("fetch")])
        cache = SchemaCache(provider)

        result = await cache.list_tools()

        provider.list_tools.assert_awaited_once()
        assert len(result) == 1
        assert result[0].name == "fetch"

    @pytest.mark.asyncio
    async def test_second_call_within_ttl_returns_cached(self) -> None:
        """Second call within TTL should return cached result, not call provider again."""
        provider = _mock_provider([_tool("read")])
        cache = SchemaCache(provider, ttl_seconds=3600.0)

        first = await cache.list_tools()
        second = await cache.list_tools()

        provider.list_tools.assert_awaited_once()
        assert first == second

    @pytest.mark.asyncio
    async def test_returns_tool_metadata_objects(self) -> None:
        """Cached result should contain ToolMetadata objects."""
        provider = _mock_provider([_tool("write"), _tool("read")])
        cache = SchemaCache(provider)

        result = await cache.list_tools()
        assert all(isinstance(t, ToolMetadata) for t in result)


# ---------------------------------------------------------------------------
# TTL expiration
# ---------------------------------------------------------------------------


class TestTTLExpiration:
    """Cache expires after TTL and re-fetches from provider."""

    @pytest.mark.asyncio
    async def test_call_after_ttl_delegates_again(self, monkeypatch) -> None:
        """After TTL expires, should call the provider again."""
        import time

        current_time = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: current_time)

        provider = _mock_provider([_tool("a")])
        cache = SchemaCache(provider, ttl_seconds=60.0)

        # First call at t=1000
        await cache.list_tools()
        assert provider.list_tools.await_count == 1

        # Second call at t=1000 (within TTL) -- cached
        await cache.list_tools()
        assert provider.list_tools.await_count == 1

        # Third call at t=1061 (after TTL) -- re-fetches
        current_time = 1061.0
        await cache.list_tools()
        assert provider.list_tools.await_count == 2

    @pytest.mark.asyncio
    async def test_default_ttl_is_3600(self) -> None:
        """Default TTL should be 3600 seconds (1 hour)."""
        provider = _mock_provider()
        cache = SchemaCache(provider)
        assert cache._ttl_seconds == 3600.0  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_custom_ttl(self) -> None:
        """TTL should be configurable."""
        provider = _mock_provider()
        cache = SchemaCache(provider, ttl_seconds=120.0)
        assert cache._ttl_seconds == 120.0  # noqa: SLF001


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


class TestInvalidation:
    """invalidate() forces re-fetch on next call."""

    @pytest.mark.asyncio
    async def test_invalidate_clears_cache(self) -> None:
        """After invalidate(), next call should delegate to provider."""
        provider = _mock_provider([_tool("x")])
        cache = SchemaCache(provider)

        await cache.list_tools()
        assert provider.list_tools.await_count == 1

        cache.invalidate()

        await cache.list_tools()
        assert provider.list_tools.await_count == 2


# ---------------------------------------------------------------------------
# Concurrent safety
# ---------------------------------------------------------------------------


class TestConcurrentSafety:
    """Concurrent calls should not duplicate backend requests."""

    @pytest.mark.asyncio
    async def test_concurrent_calls_single_backend_request(self) -> None:
        """Multiple concurrent list_tools() should only trigger one backend call."""
        call_count = 0

        async def slow_list_tools() -> list[ToolMetadata]:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return [_tool("slow")]

        provider = AsyncMock(spec=ToolListProvider)
        provider.list_tools.side_effect = slow_list_tools

        cache = SchemaCache(provider)

        # Fire 5 concurrent requests
        results = await asyncio.gather(
            cache.list_tools(),
            cache.list_tools(),
            cache.list_tools(),
            cache.list_tools(),
            cache.list_tools(),
        )

        # Only one backend call should have been made
        assert call_count == 1
        # All results should be identical
        for r in results:
            assert len(r) == 1
            assert r[0].name == "slow"


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """SchemaCache itself satisfies ToolListProvider."""

    def test_isinstance_check(self) -> None:
        provider = _mock_provider()
        cache = SchemaCache(provider)
        assert isinstance(cache, ToolListProvider)
