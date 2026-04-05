"""Tests for VisibilityController core logic."""

from __future__ import annotations

import mcp.types as types

from token_sieve.adapters.visibility.visibility_controller import VisibilityController
from token_sieve.domain.learning_types import ToolUsageRecord


def _tool(name: str) -> types.Tool:
    """Create a minimal MCP Tool for testing."""
    return types.Tool(name=name, description=f"Tool {name}", inputSchema={"type": "object"})


def _usage(name: str, call_count: int, server_id: str = "default") -> ToolUsageRecord:
    """Create a ToolUsageRecord for testing."""
    return ToolUsageRecord(
        tool_name=name,
        server_id=server_id,
        call_count=call_count,
        last_called_at="2025-01-01T00:00:00Z",
    )


class TestHideZeroCallTools:
    """Tools with zero calls are hidden."""

    def test_hide_zero_call_tools(self) -> None:
        """Tools with call_count==0 are hidden; tools with calls > 0 are visible."""
        tools = [_tool("a"), _tool("b"), _tool("c"), _tool("d"), _tool("e")]
        usage = [
            _usage("a", 5),
            _usage("b", 3),
            _usage("c", 1),
            _usage("d", 0),
            _usage("e", 0),
        ]
        ctrl = VisibilityController(frequency_threshold=3, min_visible_floor=0)
        visible, hidden = ctrl.apply(tools, usage, session_count=10)
        visible_names = {t.name for t in visible}
        hidden_names = {t.name for t in hidden}
        assert visible_names == {"a", "b", "c"}
        assert hidden_names == {"d", "e"}

    def test_hide_tools_not_in_usage_stats(self) -> None:
        """Tools not present in usage_stats at all are treated as never-called."""
        tools = [_tool("a"), _tool("b"), _tool("c")]
        usage = [_usage("a", 5)]  # b, c have no usage records
        ctrl = VisibilityController(frequency_threshold=3, min_visible_floor=0)
        visible, hidden = ctrl.apply(tools, usage, session_count=10)
        assert {t.name for t in visible} == {"a"}
        assert {t.name for t in hidden} == {"b", "c"}


class TestTopKFloor:
    """min_visible_floor guarantees minimum visible tools."""

    def test_top_k_floor_all_called_exceed_floor(self) -> None:
        """When called tools exceed floor, all called tools stay visible."""
        tools = [_tool(f"t{i}") for i in range(20)]
        usage = [_usage(f"t{i}", 12 - i) for i in range(12)]  # 12 called (counts 12..1), 8 not
        ctrl = VisibilityController(frequency_threshold=3, min_visible_floor=10)
        visible, hidden = ctrl.apply(tools, usage, session_count=10)
        assert len(visible) == 12
        assert len(hidden) == 8

    def test_top_k_floor_fills_from_uncalled(self) -> None:
        """When called tools < floor, uncalled tools fill the remaining slots."""
        tools = [_tool(f"t{i}") for i in range(15)]
        usage = [_usage(f"t{i}", 10 - i) for i in range(8)]  # only 8 called
        ctrl = VisibilityController(frequency_threshold=3, min_visible_floor=10)
        visible, hidden = ctrl.apply(tools, usage, session_count=10)
        assert len(visible) == 10  # 8 called + 2 uncalled fill to floor
        assert len(hidden) == 5
        # All 8 called tools must be in visible
        called_names = {f"t{i}" for i in range(8)}
        visible_names = {t.name for t in visible}
        assert called_names.issubset(visible_names)


class TestColdStartBypass:
    """Cold-start bypass returns all tools visible."""

    def test_cold_start_bypass(self) -> None:
        """When session_count < cold_start_sessions, all tools visible."""
        tools = [_tool("a"), _tool("b"), _tool("c")]
        usage = [_usage("a", 5)]  # b, c never called
        ctrl = VisibilityController(
            frequency_threshold=3, min_visible_floor=0, cold_start_sessions=3
        )
        visible, hidden = ctrl.apply(tools, usage, session_count=2)
        assert len(visible) == 3
        assert len(hidden) == 0

    def test_no_bypass_after_cold_start(self) -> None:
        """After cold-start threshold, hiding works normally."""
        tools = [_tool("a"), _tool("b")]
        usage = [_usage("a", 5)]
        ctrl = VisibilityController(
            frequency_threshold=3, min_visible_floor=0, cold_start_sessions=3
        )
        visible, hidden = ctrl.apply(tools, usage, session_count=3)
        assert len(visible) == 1
        assert len(hidden) == 1


class TestUnhideForSession:
    """Session-level unhiding of hidden tools."""

    def test_unhide_for_session(self) -> None:
        """After apply() hides a tool, unhide makes it visible on next apply()."""
        tools = [_tool("a"), _tool("b"), _tool("c")]
        usage = [_usage("a", 5)]
        ctrl = VisibilityController(
            frequency_threshold=3, min_visible_floor=0, cold_start_sessions=0
        )
        # First apply: b, c hidden
        visible, hidden = ctrl.apply(tools, usage, session_count=10)
        assert {t.name for t in hidden} == {"b", "c"}

        # Unhide "b"
        ctrl.unhide_for_session("b")

        # Second apply: b should now be visible
        visible, hidden = ctrl.apply(tools, usage, session_count=10)
        assert "b" in {t.name for t in visible}
        assert "b" not in {t.name for t in hidden}

    def test_unhide_unknown_tool_is_noop(self) -> None:
        """Unhiding a tool not in hidden set does not error."""
        ctrl = VisibilityController(
            frequency_threshold=3, min_visible_floor=0, cold_start_sessions=0
        )
        # No apply() called yet, no hidden tools
        ctrl.unhide_for_session("nonexistent")  # should not raise

    def test_hidden_stats_reflects_unhide(self) -> None:
        """After unhide, hidden_stats() total decreases."""
        tools = [_tool("a"), _tool("b"), _tool("c")]
        usage = [_usage("a", 5)]
        ctrl = VisibilityController(
            frequency_threshold=3, min_visible_floor=0, cold_start_sessions=0
        )
        ctrl.apply(tools, usage, session_count=10)
        assert ctrl.hidden_stats()["total_hidden"] == 2

        ctrl.unhide_for_session("b")
        assert ctrl.hidden_stats()["total_hidden"] == 1
