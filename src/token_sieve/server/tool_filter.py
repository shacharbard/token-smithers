"""ToolFilter -- pure domain object for tool allowlist/blocklist filtering.

Supports passthrough, allowlist, and blocklist modes with exact name matching
and compiled regex patterns. Zero I/O, no MCP SDK dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from token_sieve.config.schema import FilterConfig


@dataclass
class ToolFilter:
    """Filters MCP tools by name using allowlist/blocklist/passthrough modes.

    Constructed directly or via the from_config() factory method.
    Operates on any object with a .name attribute (MCP-SDK-agnostic).
    """

    mode: Literal["passthrough", "allowlist", "blocklist"]
    names: frozenset[str] = field(default_factory=frozenset)
    patterns: list[re.Pattern[str]] = field(default_factory=list)

    def is_allowed(self, tool_name: str) -> bool:
        """Check whether a tool name passes the filter."""
        if self.mode == "passthrough":
            return True

        match = tool_name in self.names or any(
            p.search(tool_name) for p in self.patterns
        )

        if self.mode == "allowlist":
            return match
        # blocklist
        return not match

    def filter_tools(self, tools: list[Any]) -> list[Any]:
        """Filter a list of tool objects, keeping only allowed ones.

        Each tool object must have a .name attribute.
        """
        return [t for t in tools if self.is_allowed(t.name)]

    @classmethod
    def from_config(cls, config: FilterConfig) -> ToolFilter:
        """Create a ToolFilter from a FilterConfig instance.

        Compiles regex patterns at construction time.
        Raises re.error if any pattern is invalid.
        """
        compiled = [re.compile(p) for p in config.patterns]
        return cls(
            mode=config.mode,  # type: ignore[arg-type]
            names=frozenset(config.tools),
            patterns=compiled,
        )
