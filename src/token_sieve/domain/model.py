"""Domain model value objects for token-sieve.

All types are frozen dataclasses (immutable value objects).
Zero external dependencies -- stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum, auto
from types import MappingProxyType
from typing import Any


class ContentType(Enum):
    """Classification of content for routing through compression strategies."""

    TEXT = auto()
    JSON = auto()
    CODE = auto()
    CLI_OUTPUT = auto()
    UNKNOWN = auto()


@dataclass(frozen=True)
class ContentEnvelope:
    """Immutable wrapper for content entering the compression pipeline.

    The anti-corruption layer between tool/MCP domain and compression domain.
    Strategies operate on envelopes, never on raw tool results.
    """

    content: str
    content_type: ContentType
    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not self.content:
            raise ValueError("content must not be empty")
        # Convert dict metadata to MappingProxyType for true immutability
        if isinstance(self.metadata, dict):
            object.__setattr__(
                self, "metadata", MappingProxyType(self.metadata)
            )

    def __hash__(self) -> int:
        return hash((self.content, self.content_type, tuple(sorted(self.metadata.items()))))


@dataclass(frozen=True)
class CompressionEvent:
    """Records a single compression step for observability.

    Every pipeline step emits one event with before/after token counts.
    """

    original_tokens: int
    compressed_tokens: int
    strategy_name: str
    content_type: ContentType

    @property
    def savings_ratio(self) -> float:
        """Fraction of tokens saved (0.0 = no savings, 1.0 = total elimination)."""
        if self.original_tokens == 0:
            return 0.0
        return 1.0 - (self.compressed_tokens / self.original_tokens)


@dataclass(frozen=True)
class TokenBudget:
    """Tracks token budget consumption. Immutable -- consume() returns new instance."""

    total: int
    used: int

    @property
    def remaining(self) -> int:
        """Tokens still available."""
        return self.total - self.used

    @property
    def is_exceeded(self) -> bool:
        """Whether usage has exceeded the total budget."""
        return self.used > self.total

    def consume(self, tokens: int) -> TokenBudget:
        """Return a new TokenBudget with additional tokens consumed."""
        return replace(self, used=self.used + tokens)


@dataclass(frozen=True)
class CompressedResult:
    """Output of a compression pipeline run: the compressed envelope plus events."""

    envelope: ContentEnvelope
    events: tuple[CompressionEvent, ...] = ()

    def __post_init__(self) -> None:
        # Convert list to tuple for immutability
        if isinstance(self.events, list):
            object.__setattr__(self, "events", tuple(self.events))
