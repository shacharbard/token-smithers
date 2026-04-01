"""SchemaCache -- TTL-based caching for tools/list responses.

Wraps a ToolListProvider with a time-based cache to avoid repeated
backend calls for the tool schema list. Uses asyncio.Lock to prevent
concurrent calls from duplicating backend requests (follows the same
pattern as BackendConnector).

Default TTL is 1 hour (3600s), matching the DietMCP caching pattern.
"""

from __future__ import annotations

import asyncio
import time

from token_sieve.domain.tool_metadata import ToolMetadata


class SchemaCache:
    """TTL-based cache wrapper for ToolListProvider.

    Satisfies the ToolListProvider Protocol itself, so it can be used
    as a drop-in replacement wherever ToolListProvider is expected.
    """

    def __init__(
        self,
        provider: object,
        ttl_seconds: float = 3600.0,
    ) -> None:
        self._provider = provider
        self._ttl_seconds = ttl_seconds
        self._cached: list[ToolMetadata] | None = None
        self._last_fetched: float = 0.0
        self._lock = asyncio.Lock()

    async def list_tools(self) -> list[ToolMetadata]:
        """Return cached tool list, or fetch from provider if stale.

        Uses an asyncio.Lock so concurrent callers wait for a single
        backend fetch rather than each triggering their own.
        """
        async with self._lock:
            now = time.monotonic()
            if self._cached is not None and (now - self._last_fetched) < self._ttl_seconds:
                return self._cached

            result = await self._provider.list_tools()  # type: ignore[union-attr]
            self._cached = result
            self._last_fetched = time.monotonic()
            return result

    def invalidate(self) -> None:
        """Force the next list_tools() call to re-fetch from the provider."""
        self._last_fetched = 0.0
        self._cached = None
