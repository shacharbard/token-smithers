"""TruncationCompressor -- truncates content to a configurable token budget.

Uses a TokenCounter (default: CharEstimateCounter) to estimate token counts.
Content exceeding max_tokens is truncated with a marker showing savings.
"""

from __future__ import annotations

import dataclasses

from token_sieve.domain.counters import CharEstimateCounter
from token_sieve.domain.model import ContentEnvelope


class TruncationCompressor:
    """Truncate content to approximately *max_tokens* tokens.

    Satisfies CompressionStrategy protocol structurally.
    """

    def __init__(
        self,
        max_tokens: int = 4096,
        counter: object | None = None,
    ) -> None:
        self.max_tokens = max_tokens
        self._counter = counter or CharEstimateCounter()

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Accept all content types."""
        return True

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Truncate content if it exceeds the token budget."""
        original_tokens = self._counter.count(envelope.content)
        if original_tokens <= self.max_tokens:
            return envelope

        # Estimate character budget from token budget
        # For CharEstimateCounter: 1 token ~ 4 chars
        char_budget = self.max_tokens * 4
        truncated_content = envelope.content[:char_budget]

        # Keep at least the first line to avoid empty or mid-line truncation
        first_newline = envelope.content.find("\n")
        if first_newline > 0 and first_newline > char_budget:
            # Budget cuts into the first line — preserve the full first line
            truncated_content = envelope.content[:first_newline]
        elif not truncated_content:
            truncated_content = envelope.content[:1]

        truncated_tokens = self._counter.count(truncated_content)
        marker = f"\n[truncated: {original_tokens} -> {truncated_tokens} tokens]"

        return dataclasses.replace(
            envelope,
            content=truncated_content + marker,
        )
