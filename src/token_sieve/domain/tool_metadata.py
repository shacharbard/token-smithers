"""ToolMetadata frozen value object for MCP tool definitions.

Preserves full inputSchema from tools/list for future reranking.
Follows the frozen dataclass pattern from model.py (ContentEnvelope).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolMetadata:
    """Immutable representation of an MCP tool definition.

    Preserves the full inputSchema from the backend's tools/list response
    for future semantic reranking. The server_id field supports multi-backend
    scenarios in Phase 03+.
    """

    name: str
    title: str | None
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    server_id: str = "default"
