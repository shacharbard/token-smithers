"""Port for semantic result caching.

Defines the SemanticCachePort Protocol and CacheHit value object.
Domain layer -- ZERO external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CacheHit:
    """Result of a successful semantic cache lookup.

    All fields are hashable scalars per domain conventions.
    """

    result_text: str
    similarity_score: float
    hit_count: int


@runtime_checkable
class SemanticCachePort(Protocol):
    """Interface for semantic (fuzzy) result caching.

    Implementations store tool call results keyed by normalized arguments
    and support both exact-match and similarity-based lookup.
    """

    async def lookup_similar(
        self,
        tool_name: str,
        args_normalized: str,
        threshold: float,
    ) -> CacheHit | None:
        """Find a cached result similar to the given args.

        Returns CacheHit if similarity >= threshold, else None.
        Exact hash match is preferred over fuzzy scan.
        """
        ...

    async def cache_result(
        self,
        tool_name: str,
        args_normalized: str,
        args_hash: str,
        result: str,
    ) -> None:
        """Store a tool call result in the cache."""
        ...

    async def evict_expired(self) -> int:
        """Remove expired entries. Returns count of evicted entries."""
        ...
