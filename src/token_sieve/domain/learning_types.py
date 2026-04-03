"""Domain types for cross-session learning persistence.

Frozen dataclasses with hashable-scalar fields only (str, int, float, bool, None).
Zero external dependencies -- stdlib-only imports.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolUsageRecord:
    """A tool's usage statistics from the learning store."""

    tool_name: str
    server_id: str
    call_count: int
    last_called_at: str  # ISO 8601


@dataclass(frozen=True)
class CooccurrenceRecord:
    """Records how often two tools are called together in a session."""

    tool_a: str
    tool_b: str
    co_count: int
    last_seen: str  # ISO 8601


@dataclass(frozen=True)
class PipelineConfig:
    """Per-tool compression pipeline configuration.

    Stores the learned optimal adapter ordering and disabled adapters
    for a specific tool on a specific server.  Tuples ensure immutability
    and hashability.
    """

    tool_name: str
    server_id: str
    adapter_order: tuple[str, ...] = ()
    disabled_adapters: tuple[str, ...] = ()
    eval_count: int = 0
    regret_streak: int = 0
    last_eval_at: str = ""  # ISO 8601
    created_at: str = ""  # ISO 8601
