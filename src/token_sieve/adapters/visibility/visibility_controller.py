"""VisibilityController -- frequency-based tool visibility partitioning.

Hides unused MCP tools based on call frequency from the learning store.
Receives a tool list and usage stats, returns visible and hidden partitions.
"""

from __future__ import annotations

from typing import Any


class VisibilityController:
    """Partitions MCP tools into visible and hidden sets based on usage.

    Tools with zero calls (or absent from usage_stats) are hidden.
    A top-K floor guarantees a minimum number of visible tools.
    Cold-start bypass shows all tools until enough sessions exist.
    """

    def __init__(
        self,
        frequency_threshold: int = 3,
        min_visible_floor: int = 10,
        cold_start_sessions: int = 3,
    ) -> None:
        self._frequency_threshold = frequency_threshold
        self._min_visible_floor = min_visible_floor
        self._cold_start_sessions = cold_start_sessions
        self._hidden_tools: dict[str, Any] = {}
        self._session_unhidden: set[str] = set()

    def apply(
        self,
        tools: list,
        usage_stats: list,
        *,
        session_count: int,
    ) -> tuple[list, list]:
        """Partition tools into (visible, hidden) based on usage frequency.

        Args:
            tools: Full list of MCP Tool objects.
            usage_stats: List of ToolUsageRecord from the learning store.
            session_count: Number of sessions observed so far.

        Returns:
            Tuple of (visible_tools, hidden_tools).
        """
        # Cold-start bypass: show all tools until enough data exists
        if session_count < self._cold_start_sessions:
            self._hidden_tools = {}
            return list(tools), []

        # Build usage lookup: tool_name -> call_count
        usage_by_name: dict[str, int] = {}
        for stat in usage_stats:
            usage_by_name[stat.tool_name] = stat.call_count

        # Score and partition tools
        called, uncalled = self._score_tools(tools, usage_by_name)

        # Apply top-K floor: ensure at least min_visible_floor tools are visible
        visible = list(called)
        hidden = list(uncalled)

        if len(visible) < self._min_visible_floor and hidden:
            deficit = self._min_visible_floor - len(visible)
            promote = hidden[:deficit]
            visible.extend(promote)
            hidden = hidden[deficit:]

        # Store hidden tools for later queries
        self._hidden_tools = {t.name: t for t in hidden}

        return visible, hidden

    def _score_tools(
        self,
        tools: list,
        usage_by_name: dict[str, int],
    ) -> tuple[list, list]:
        """Separate tools into called and uncalled based on usage data.

        Args:
            tools: Full list of MCP Tool objects.
            usage_by_name: Map of tool_name -> call_count.

        Returns:
            Tuple of (called_tools, uncalled_tools).
        """
        called = []
        uncalled = []
        for tool in tools:
            name = tool.name
            # Session-unhidden tools always go to called
            if name in self._session_unhidden:
                called.append(tool)
            elif usage_by_name.get(name, 0) > 0:
                called.append(tool)
            else:
                uncalled.append(tool)
        return called, uncalled

    def hidden_stats(self) -> dict:
        """Return summary statistics about hidden tools."""
        total_hidden = len(self._hidden_tools)
        return {"total_hidden": total_hidden, "visible": 0}

    def get_hidden_tools(self) -> list:
        """Return the list of currently hidden tool objects."""
        return list(self._hidden_tools.values())

    def get_hidden_tool_names(self) -> frozenset[str]:
        """Return the set of currently hidden tool names."""
        return frozenset(self._hidden_tools.keys())

    def unhide_for_session(self, tool_name: str) -> None:
        """Make a hidden tool visible for the remainder of this session.

        If the tool is not currently hidden, this is a no-op.
        """
        if tool_name in self._hidden_tools:
            del self._hidden_tools[tool_name]
            self._session_unhidden.add(tool_name)
