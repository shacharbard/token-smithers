"""CompressionPipeline -- content-routed strategy chain.

Routes envelopes by ContentType through registered strategy chains.
Each strategy in a chain receives the output of the previous one.
Zero external dependencies -- stdlib only.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from token_sieve.domain.model import CompressionEvent, ContentEnvelope, ContentType

if TYPE_CHECKING:
    from token_sieve.domain.ports import CompressionStrategy, TokenCounter


@dataclass
class CompressionPipeline:
    """Content-routed compression pipeline.

    Strategies are registered per ContentType. When an envelope is processed,
    only the chain for its content_type is executed. Strategies that decline
    via can_handle() are skipped.
    """

    _counter: TokenCounter
    _routes: dict[ContentType, list[CompressionStrategy]] = field(
        default_factory=dict, init=False
    )

    def __init__(
        self,
        counter: TokenCounter,
        size_gate_threshold: int | None = None,
    ) -> None:
        self._counter = counter
        self._size_gate_threshold = size_gate_threshold
        self._routes: dict[ContentType, list[CompressionStrategy]] = {}

    def register(
        self, content_type: ContentType, strategy: CompressionStrategy
    ) -> None:
        """Add a strategy to the chain for the given content type."""
        self._routes.setdefault(content_type, []).append(strategy)

    def process(
        self, envelope: ContentEnvelope
    ) -> tuple[ContentEnvelope, list[CompressionEvent]]:
        """Run the envelope through the registered strategy chain.

        Returns the (possibly transformed) envelope and a list of
        CompressionEvent records -- one per strategy that actually fired.
        """
        events: list[CompressionEvent] = []

        # Size gate: skip all compression for small content
        if self._size_gate_threshold is not None:
            token_count = self._counter.count(envelope.content)
            if token_count <= self._size_gate_threshold:
                return envelope, events

        chain = self._routes.get(envelope.content_type, [])

        for strategy in chain:
            strategy_name = type(strategy).__name__
            try:
                if not strategy.can_handle(envelope):
                    continue
            except Exception as exc:
                print(
                    f"Warning: {strategy_name}.can_handle() raised "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                continue

            try:
                original_tokens = self._counter.count(envelope.content)
                compressed_envelope = strategy.compress(envelope)
                compressed_tokens = self._counter.count(
                    compressed_envelope.content
                )
            except Exception as exc:
                print(
                    f"Warning: {strategy_name}.compress() raised "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                continue

            events.append(
                CompressionEvent(
                    original_tokens=original_tokens,
                    compressed_tokens=compressed_tokens,
                    strategy_name=strategy_name,
                    content_type=envelope.content_type,
                )
            )
            envelope = compressed_envelope

        return envelope, events

    def cleanup(self) -> None:
        """Clean up resources held by registered strategies."""
        for chain in self._routes.values():
            for strategy in chain:
                if hasattr(strategy, "cleanup"):
                    strategy.cleanup()
