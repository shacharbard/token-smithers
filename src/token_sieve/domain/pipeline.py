"""CompressionPipeline -- content-routed strategy chain.

Routes envelopes by ContentType through registered strategy chains.
Each strategy in a chain receives the output of the previous one.
Zero external dependencies -- stdlib only.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

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
        self.pipeline_config_store: Any | None = None

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
        current_tokens: int | None = None
        if self._size_gate_threshold is not None:
            current_tokens = self._counter.count(envelope.content)
            if current_tokens <= self._size_gate_threshold:
                return envelope, events

        chain = self._routes.get(envelope.content_type, [])

        # Per-tool filtering: skip disabled adapters.
        # C2 fix: disabled_adapters are passed via envelope metadata as a
        # comma-separated string by the async caller (proxy.py handle_call_tool)
        # to avoid sync→async mismatch. The pipeline_config_store attribute is
        # retained for backward compat but no longer called from this sync method.
        disabled: set[str] = set()
        da_raw = envelope.metadata.get("disabled_adapters") if envelope.metadata else None
        if da_raw:
            disabled = set(da_raw.split(","))

        for strategy in chain:
            strategy_name = type(strategy).__name__

            # Skip disabled adapters for this tool
            if strategy_name in disabled:
                continue

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
                # Carry forward token count from size gate or previous strategy
                original_tokens = (
                    current_tokens
                    if current_tokens is not None
                    else self._counter.count(envelope.content)
                )
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

            is_regret = compressed_tokens > original_tokens
            events.append(
                CompressionEvent(
                    original_tokens=original_tokens,
                    compressed_tokens=compressed_tokens,
                    strategy_name=strategy_name,
                    content_type=envelope.content_type,
                    is_regret=is_regret,
                )
            )
            if is_regret and self.pipeline_config_store is not None:
                # Revert: don't apply this strategy's output when tracking is active
                continue
            envelope = compressed_envelope
            current_tokens = compressed_tokens

        return envelope, events

    def cleanup(self) -> None:
        """Clean up resources held by registered strategies."""
        for chain in self._routes.values():
            for strategy in chain:
                if hasattr(strategy, "cleanup"):
                    strategy.cleanup()
