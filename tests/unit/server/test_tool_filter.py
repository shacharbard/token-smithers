"""Tests for ToolFilter pure domain object.

ToolFilter supports passthrough/allowlist/blocklist with exact names and regex.
Uses plain objects with .name attribute -- no MCP SDK dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pytest

from token_sieve.config.schema import FilterConfig
from token_sieve.server.tool_filter import ToolFilter


@dataclass
class FakeTool:
    """Minimal tool object with .name attribute for testing."""

    name: str


def _make_tools(*names: str) -> list[FakeTool]:
    return [FakeTool(name=n) for n in names]


class TestToolFilterPassthrough:
    """Passthrough mode allows all tools."""

    def test_all_tools_allowed(self) -> None:
        f = ToolFilter(mode="passthrough", names=frozenset(), patterns=[])
        assert f.is_allowed("anything") is True
        assert f.is_allowed("read_file") is True

    def test_filter_tools_returns_all(self) -> None:
        f = ToolFilter(mode="passthrough", names=frozenset(), patterns=[])
        tools = _make_tools("a", "b", "c")
        result = f.filter_tools(tools)
        assert len(result) == 3


class TestToolFilterAllowlist:
    """Allowlist mode: only matching tools are allowed."""

    def test_exact_name_allowed(self) -> None:
        f = ToolFilter(
            mode="allowlist",
            names=frozenset(["read_file", "write_file"]),
            patterns=[],
        )
        assert f.is_allowed("read_file") is True
        assert f.is_allowed("delete_file") is False

    def test_regex_pattern_allowed(self) -> None:
        f = ToolFilter(
            mode="allowlist",
            names=frozenset(),
            patterns=[re.compile(r"search_.*")],
        )
        assert f.is_allowed("search_files") is True
        assert f.is_allowed("search_code") is True
        assert f.is_allowed("read_file") is False

    def test_exact_name_or_regex(self) -> None:
        f = ToolFilter(
            mode="allowlist",
            names=frozenset(["read_file"]),
            patterns=[re.compile(r"search_.*")],
        )
        assert f.is_allowed("read_file") is True
        assert f.is_allowed("search_code") is True
        assert f.is_allowed("delete_file") is False

    def test_filter_tools_keeps_allowed_only(self) -> None:
        f = ToolFilter(
            mode="allowlist",
            names=frozenset(["a", "c"]),
            patterns=[],
        )
        tools = _make_tools("a", "b", "c", "d")
        result = f.filter_tools(tools)
        assert [t.name for t in result] == ["a", "c"]

    def test_empty_allowlist_blocks_all(self) -> None:
        f = ToolFilter(mode="allowlist", names=frozenset(), patterns=[])
        assert f.is_allowed("anything") is False
        assert f.filter_tools(_make_tools("a", "b")) == []


class TestToolFilterBlocklist:
    """Blocklist mode: matching tools are rejected."""

    def test_exact_name_blocked(self) -> None:
        f = ToolFilter(
            mode="blocklist",
            names=frozenset(["dangerous_tool"]),
            patterns=[],
        )
        assert f.is_allowed("dangerous_tool") is False
        assert f.is_allowed("safe_tool") is True

    def test_regex_pattern_blocked(self) -> None:
        f = ToolFilter(
            mode="blocklist",
            names=frozenset(),
            patterns=[re.compile(r"internal_.*")],
        )
        assert f.is_allowed("internal_debug") is False
        assert f.is_allowed("public_api") is True

    def test_filter_tools_removes_blocked(self) -> None:
        f = ToolFilter(
            mode="blocklist",
            names=frozenset(["b"]),
            patterns=[re.compile(r"d.*")],
        )
        tools = _make_tools("a", "b", "c", "dangerous")
        result = f.filter_tools(tools)
        assert [t.name for t in result] == ["a", "c"]

    def test_empty_blocklist_allows_all(self) -> None:
        f = ToolFilter(mode="blocklist", names=frozenset(), patterns=[])
        assert f.is_allowed("anything") is True


class TestToolFilterEdgeCases:
    """Edge cases and special behaviors."""

    def test_case_sensitive_matching(self) -> None:
        f = ToolFilter(
            mode="allowlist",
            names=frozenset(["Read_File"]),
            patterns=[],
        )
        assert f.is_allowed("Read_File") is True
        assert f.is_allowed("read_file") is False

    def test_empty_tool_list(self) -> None:
        f = ToolFilter(mode="passthrough", names=frozenset(), patterns=[])
        assert f.filter_tools([]) == []

    def test_regex_partial_match(self) -> None:
        """Regex uses search, not fullmatch -- partial matches work."""
        f = ToolFilter(
            mode="allowlist",
            names=frozenset(),
            patterns=[re.compile(r"file")],
        )
        assert f.is_allowed("read_file_content") is True
        assert f.is_allowed("no_match") is False


class TestToolFilterFromConfig:
    """Factory method from FilterConfig."""

    def test_passthrough_from_config(self) -> None:
        cfg = FilterConfig(mode="passthrough")
        f = ToolFilter.from_config(cfg)
        assert f.mode == "passthrough"
        assert f.names == frozenset()
        assert f.patterns == []

    def test_allowlist_from_config(self) -> None:
        cfg = FilterConfig(
            mode="allowlist",
            tools=["read_file", "write_file"],
            patterns=[r"search_.*"],
        )
        f = ToolFilter.from_config(cfg)
        assert f.mode == "allowlist"
        assert f.names == frozenset(["read_file", "write_file"])
        assert len(f.patterns) == 1
        assert f.is_allowed("search_code") is True

    def test_blocklist_from_config(self) -> None:
        cfg = FilterConfig(
            mode="blocklist",
            tools=["dangerous"],
            patterns=[r"internal_.*"],
        )
        f = ToolFilter.from_config(cfg)
        assert f.mode == "blocklist"
        assert f.is_allowed("dangerous") is False
        assert f.is_allowed("internal_debug") is False
        assert f.is_allowed("safe") is True

    def test_invalid_regex_raises(self) -> None:
        cfg = FilterConfig(
            mode="allowlist",
            tools=[],
            patterns=["[invalid"],  # bad regex
        )
        with pytest.raises(re.error):
            ToolFilter.from_config(cfg)

    def test_from_config_compiles_patterns(self) -> None:
        cfg = FilterConfig(
            mode="allowlist",
            tools=[],
            patterns=[r"^fetch$", r"read_\w+"],
        )
        f = ToolFilter.from_config(cfg)
        assert len(f.patterns) == 2
        assert all(isinstance(p, re.Pattern) for p in f.patterns)


class TestToolFilterDefenseInDepth:
    """Defense-in-depth: invalid mode raises ValueError even at runtime."""

    def test_invalid_mode_raises_value_error(self) -> None:
        """If someone bypasses Pydantic and passes invalid mode, is_allowed raises."""
        # Force an invalid mode via object.__setattr__ to bypass frozen/Literal
        f = ToolFilter(mode="passthrough")  # type: ignore[arg-type]
        object.__setattr__(f, "mode", "bogus")
        with pytest.raises(ValueError, match="Unknown filter mode"):
            f.is_allowed("any_tool")
