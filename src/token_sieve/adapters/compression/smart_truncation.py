"""SmartTruncation: head+tail truncation with omission marker.

Preserves the first N and last M lines of content, inserting an
omission marker showing how many lines were removed. Replaces naive
truncation as the universal fallback safety net.

Satisfies CompressionStrategy protocol structurally.
"""

from __future__ import annotations

import dataclasses

from token_sieve.domain.model import ContentEnvelope


class SmartTruncation:
    """Head+tail truncation with omission marker.

    Satisfies CompressionStrategy protocol structurally.

    Args:
        head_lines: Number of lines to preserve from the start (default 50).
        tail_lines: Number of lines to preserve from the end (default 20).
    """

    def __init__(
        self,
        head_lines: int = 50,
        tail_lines: int = 20,
    ) -> None:
        self.head_lines = head_lines
        self.tail_lines = tail_lines

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Accept all content types (universal fallback)."""
        return True

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Truncate to head+tail lines with omission marker if needed."""
        lines = envelope.content.split("\n")
        total = len(lines)

        if total <= self.head_lines + self.tail_lines:
            return envelope

        omitted = total - self.head_lines - self.tail_lines
        head = lines[: self.head_lines]
        tail = lines[-self.tail_lines :]
        marker = f"... [{omitted} lines omitted]"

        truncated = "\n".join(head + [marker] + tail)
        return dataclasses.replace(envelope, content=truncated)
