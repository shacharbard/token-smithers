"""Domain port interfaces (Protocol classes) for token-sieve.

All ports are defined as typing.Protocol classes -- no ABC, no inheritance required.
Adapters satisfy these structurally (duck typing). Zero external dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from token_sieve.domain.model import CompressionEvent, ContentEnvelope

if TYPE_CHECKING:
    from token_sieve.domain.session import SessionContext


class CompressionStrategy(Protocol):
    """Interface for content compression adapters.

    Each strategy handles specific content types and returns a compressed envelope.

    The ``deterministic`` flag (D4b) signals whether two calls to ``compress``
    on byte-identical input must produce byte-identical output. This attribute
    is REQUIRED: every adapter MUST declare ``deterministic = True`` or
    ``deterministic = False`` at class level. There is intentionally no default
    — a forgetful adapter should fail the audit, not silently be treated as
    deterministic. Phase 10 will fork code paths on this flag (e.g., bypass
    caching for non-deterministic adapters).
    """

    deterministic: bool

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Whether this strategy can compress the given envelope."""
        ...

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Compress the envelope content, returning a new envelope."""
        ...


class DeduplicationStrategy(Protocol):
    """Interface for detecting and handling duplicate content."""

    def is_duplicate(self, envelope: ContentEnvelope, session: SessionContext) -> bool:
        """Whether this envelope's content has been seen before in the session."""
        ...

    def get_reference(self, envelope: ContentEnvelope, session: SessionContext) -> str:
        """Return a backreference string for previously-seen content."""
        ...


class BackendToolAdapter(Protocol):
    """Interface for calling backend MCP tool servers."""

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute a tool call on a backend server and return the result."""
        ...


class SessionRepository(Protocol):
    """Interface for session state persistence."""

    def get(self, session_id: str) -> SessionContext | None:
        """Retrieve a session by ID, or None if not found."""
        ...

    def save(self, session: SessionContext) -> None:
        """Persist a session."""
        ...


class MetricsCollector(Protocol):
    """Interface for recording and querying compression metrics."""

    def record(self, event: CompressionEvent) -> None:
        """Record a compression event."""
        ...

    def session_summary(self) -> dict:
        """Return a summary of metrics for the current session."""
        ...

    def strategy_breakdown(self) -> dict:
        """Return per-strategy metrics breakdown."""
        ...


@runtime_checkable
class TokenCounter(Protocol):
    """Interface for counting tokens in text.

    Marked @runtime_checkable for dynamic dispatch between
    CharEstimateCounter and real tokenizer implementations.
    """

    def count(self, text: str) -> int:
        """Count the number of tokens in the given text."""
        ...
