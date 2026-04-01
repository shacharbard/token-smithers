"""LRU-bounded result store for semantic diff.

Stores previous tool call results so SemanticDiffStrategy can compute
diffs on re-reads. Implements InvalidationObserver for write-through
invalidation of mutating calls.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import Any


class DiffStateStore:
    """LRU-bounded store for previous tool call results.

    Implements invalidation observer interface for WriteThruInvalidator.
    """

    def __init__(self, max_entries: int = 100) -> None:
        self._max_entries = max_entries
        self._store: OrderedDict[str, tuple[str, str]] = OrderedDict()
        # Map tool_name -> set of store keys for fast invalidation
        self._tool_keys: dict[str, set[str]] = {}

    def store_result(
        self, tool_name: str, args: dict[str, Any] | None, content: str
    ) -> None:
        """Store a tool call result for future diff comparison."""
        key = self._make_key(tool_name, args)
        if key in self._store:
            self._store.move_to_end(key)
            self._store[key] = (tool_name, content)
        else:
            self._store[key] = (tool_name, content)
            self._tool_keys.setdefault(tool_name, set()).add(key)
            self._evict_if_needed()

    def get_previous(
        self, tool_name: str, args: dict[str, Any] | None
    ) -> str | None:
        """Retrieve previous result for a tool+args key. None on miss."""
        key = self._make_key(tool_name, args)
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        return self._store[key][1]

    def invalidate(self, tool_name: str) -> None:
        """Remove all stored entries for a specific tool name.

        Satisfies the InvalidationObserver protocol.
        """
        keys = self._tool_keys.pop(tool_name, set())
        for key in keys:
            self._store.pop(key, None)

    def invalidate_all(self) -> None:
        """Remove ALL stored entries regardless of tool name.

        Used for global invalidation on mutating calls.
        """
        self._store.clear()
        self._tool_keys.clear()

    @staticmethod
    def _make_key(tool_name: str, args: dict[str, Any] | None) -> str:
        """Compute deterministic store key from tool name + args."""
        args_str = json.dumps(args, sort_keys=True) if args else ""
        raw = f"{tool_name}:{args_str}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _evict_if_needed(self) -> None:
        """Evict oldest entries when exceeding max_entries."""
        while len(self._store) > self._max_entries:
            evicted_key, (evicted_tool, _) = self._store.popitem(last=False)
            tool_keys = self._tool_keys.get(evicted_tool)
            if tool_keys:
                tool_keys.discard(evicted_key)
                if not tool_keys:
                    del self._tool_keys[evicted_tool]
