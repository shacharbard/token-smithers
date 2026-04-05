"""Port protocol for tool visibility control.

Defines the interface for components that partition MCP tools into
visible and hidden sets based on usage frequency.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class VisibilityControllerPort(Protocol):
    """Interface for tool visibility controllers.

    Implementations partition a tool list into visible and hidden sets
    based on usage statistics and session context.
    """

    def apply(
        self,
        tools: list,
        usage_stats: list,
        *,
        session_count: int,
    ) -> tuple[list, list]:
        """Partition tools into (visible, hidden) based on usage frequency."""
        ...

    def hidden_stats(self) -> dict:
        """Return summary statistics about hidden tools."""
        ...

    def get_hidden_tools(self) -> list:
        """Return the list of currently hidden tool objects."""
        ...

    def get_hidden_tool_names(self) -> frozenset[str]:
        """Return the set of currently hidden tool names."""
        ...

    def unhide_for_session(self, tool_name: str) -> None:
        """Make a hidden tool visible for the remainder of this session."""
        ...
