"""Schema virtualization domain port interface (Protocol class).

Protocol for schema compression -- virtualizing tool schemas across
multiple tiers of compression. Zero external dependencies -- only stdlib.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SchemaVirtualizerPort(Protocol):
    """Interface for schema virtualization engines.

    Implementations compress tool schemas across configurable tiers
    (lossless cleanup, description compression, DietMCP notation)
    while preserving original schemas for on-demand retrieval.
    """

    def virtualize(
        self,
        tools: list[dict],
        *,
        tier: int = 3,
        usage_stats: dict[str, int] | None = None,
    ) -> list[dict]:
        """Compress tool schemas at the specified tier level.

        Args:
            tools: List of MCP tool dicts with 'name', 'description', 'inputSchema'.
            tier: Maximum compression tier to apply (1=lossless, 2=descriptions, 3=DietMCP).
            usage_stats: Optional dict of tool_name -> call_count for frequency-aware selection.

        Returns:
            List of tools with compressed schemas.
        """
        ...

    def get_full_schema(self, tool_name: str) -> dict | None:
        """Retrieve the original uncompressed schema for a tool.

        Returns None if the tool is not known.
        """
        ...
