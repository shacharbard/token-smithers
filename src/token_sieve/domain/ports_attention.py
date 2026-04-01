"""AttentionTracker port interface (Protocol class).

Defines the contract for tracking which tool results get referenced
by the LLM. Zero external dependencies -- stdlib-only imports.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from token_sieve.domain.attention_score import AttentionScore


@runtime_checkable
class AttentionTracker(Protocol):
    """Interface for tracking tool result attention.

    Implementations record when a tool result is referenced and
    provide scored access to determine which tools are most valuable.
    """

    def record_reference(self, tool_name: str, session_id: str) -> None:
        """Record that a tool result was referenced by the LLM."""
        ...

    def get_score(self, tool_name: str) -> AttentionScore | None:
        """Get the attention score for a tool, or None if untracked."""
        ...

    def get_all_scores(self) -> list[AttentionScore]:
        """Get all tracked attention scores."""
        ...
