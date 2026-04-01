"""AttentionScore value object -- tracks how often a tool result is referenced.

Zero external dependencies. Stdlib-only imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AttentionScore:
    """Immutable record of a tool's attention metrics.

    Attributes:
        tool_name: The MCP tool whose results are being tracked.
        reference_count: How many times the result was referenced.
        last_referenced: Monotonic timestamp of last reference.
        decay_score: Time-decayed importance score (0.0 = cold, 1.0 = hot).
    """

    tool_name: str
    reference_count: int
    last_referenced: float
    decay_score: float = 0.0
