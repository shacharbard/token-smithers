"""Idempotent call short-circuit cache.

Exact-match cache at the proxy layer. Key = hash(tool_name + sorted(args)).
Session-scoped with no TTL — session end is natural invalidation.
Implements InvalidationObserver for write-through invalidation.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import Any


class IdempotentCallCache:
    """Session-scoped exact-match cache for tool call results.

    Uses OrderedDict for LRU behavior. Bounded by max_entries.
    Implements invalidation observer interface for WriteThruInvalidator.
    """

    def __init__(self, max_entries: int = 200) -> None:
        self._max_entries = max_entries
        self._cache: OrderedDict[str, tuple[str, Any]] = OrderedDict()
        # Map tool_name -> set of cache keys for fast invalidation
        self._tool_keys: dict[str, set[str]] = {}

    def get(self, tool_name: str, args: dict[str, Any] | None) -> Any | None:
        """Look up a cached result. Returns None on miss."""
        key = self._make_key(tool_name, args)
        if key not in self._cache:
            return None
        # Move to end for LRU freshness
        self._cache.move_to_end(key)
        return self._cache[key][1]

    def put(
        self, tool_name: str, args: dict[str, Any] | None, result: Any
    ) -> None:
        """Store a tool call result."""
        key = self._make_key(tool_name, args)
        if key in self._cache:
            self._cache.move_to_end(key)
            self._cache[key] = (tool_name, result)
        else:
            self._cache[key] = (tool_name, result)
            self._tool_keys.setdefault(tool_name, set()).add(key)
            self._evict_if_needed()

    def clear_all(self) -> None:
        """Reset the entire cache (session end)."""
        self._cache.clear()
        self._tool_keys.clear()

    def invalidate(self, tool_name: str) -> None:
        """Remove all cached entries for a specific tool name.

        Satisfies the InvalidationObserver protocol.
        """
        keys = self._tool_keys.pop(tool_name, set())
        for key in keys:
            self._cache.pop(key, None)

    def invalidate_all(self) -> None:
        """Remove ALL cached entries regardless of tool name.

        Used for global invalidation on mutating calls -- a write to
        any resource may affect cached reads from other tools.
        """
        self._cache.clear()
        self._tool_keys.clear()

    @staticmethod
    def _make_key(tool_name: str, args: dict[str, Any] | None) -> str:
        """Compute deterministic cache key from tool name + args."""
        args_str = json.dumps(args, sort_keys=True) if args else ""
        raw = f"{tool_name}:{args_str}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _evict_if_needed(self) -> None:
        """Evict oldest entries when exceeding max_entries."""
        while len(self._cache) > self._max_entries:
            evicted_key, (evicted_tool, _) = self._cache.popitem(last=False)
            tool_keys = self._tool_keys.get(evicted_tool)
            if tool_keys:
                tool_keys.discard(evicted_key)
                if not tool_keys:
                    del self._tool_keys[evicted_tool]
