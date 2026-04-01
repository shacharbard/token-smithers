"""Reranking domain port interfaces (Protocol classes).

Protocol for tool list transformation -- reordering and filtering tools/list
responses based on usage patterns. Zero external dependencies -- only stdlib
+ domain model types.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from token_sieve.domain.tool_metadata import ToolMetadata


@runtime_checkable
class ToolListTransformer(Protocol):
    """Interface for reordering/filtering tool lists.

    Implementations may track usage stats (via record_call) and use them
    to reorder the tools/list response (via transform).  transform() must
    never *remove* tools -- only reorder or deprioritize.
    """

    def transform(self, tools: list[ToolMetadata]) -> list[ToolMetadata]:
        """Reorder or filter the tool list based on implementation strategy.

        Must return all input tools (reorder only, no removal).
        """
        ...

    def record_call(self, tool_name: str) -> None:
        """Record that a tool was called, for future ranking decisions."""
        ...
