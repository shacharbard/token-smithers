"""Write-through invalidation for mutating tool calls.

Shared invalidation logic used by IdempotentCallCache and DiffStateStore.
Mutating tool calls (write/create/delete/update/set/remove/add) trigger
invalidation of all registered observers.
"""

from __future__ import annotations

from typing import Protocol


class InvalidationObserver(Protocol):
    """Interface for caches that respond to invalidation signals."""

    def invalidate(self, tool_name: str) -> None:
        """Clear entries related to the given tool name."""
        ...


_DEFAULT_MUTATING_PATTERNS: frozenset[str] = frozenset(
    {"write", "create", "delete", "update", "set", "remove", "add"}
)


class WriteThruInvalidator:
    """Detects mutating tool calls and notifies registered cache observers.

    Pattern matching: a tool name is considered mutating if any of the
    configured patterns appears as a substring (case-insensitive).
    """

    def __init__(
        self,
        mutating_patterns: set[str] | frozenset[str] | None = None,
    ) -> None:
        self._patterns: frozenset[str] = (
            frozenset(mutating_patterns)
            if mutating_patterns is not None
            else _DEFAULT_MUTATING_PATTERNS
        )
        self._observers: list[InvalidationObserver] = []

    def is_mutating(self, tool_name: str) -> bool:
        """Check if a tool name matches any mutating pattern."""
        lower = tool_name.lower()
        return any(p in lower for p in self._patterns)

    def register_observer(self, observer: InvalidationObserver) -> None:
        """Register a cache/store to receive invalidation signals."""
        self._observers.append(observer)

    def invalidate_for(self, tool_name: str) -> None:
        """Notify all registered observers about a mutating tool call.

        Uses global invalidation (invalidate_all) when available, since a
        mutation to any resource may affect cached reads from other tools.
        Falls back to per-tool invalidation for observers without invalidate_all.
        """
        for observer in self._observers:
            if hasattr(observer, "invalidate_all"):
                observer.invalidate_all()
            else:
                observer.invalidate(tool_name)
