"""WindowDeduplicationStrategy -- rolling-window content deduplication.

Uses SHA-256 content hashing with a bounded deque to detect repeated
tool results within a configurable window. Short content is bypassed
to avoid false positives on brief, common responses.
"""

from __future__ import annotations

import hashlib
from collections import deque
from typing import TYPE_CHECKING

from token_sieve.domain.model import ContentEnvelope

if TYPE_CHECKING:
    from token_sieve.domain.session import SessionContext


class WindowDeduplicationStrategy:
    """Detect duplicate content within a rolling window.

    Satisfies DeduplicationStrategy protocol structurally.
    """

    def __init__(
        self,
        max_window: int = 50,
        min_content_length: int = 100,
    ) -> None:
        self._buffer: deque[tuple[str, str, str]] = deque(maxlen=max_window)
        self._min_content_length = min_content_length

    def is_duplicate(
        self,
        envelope: ContentEnvelope,
        session: SessionContext,
    ) -> bool:
        """Check if envelope content was seen within the rolling window.

        Short content (< min_content_length chars) bypasses dedup.
        """
        if len(envelope.content) < self._min_content_length:
            return False

        content_hash = self._hash(envelope.content)

        # Search buffer for matching hash
        for _tool_name, stored_hash, _summary in self._buffer:
            if stored_hash == content_hash:
                return True

        # Not a duplicate — record in buffer
        tool_name = str(envelope.metadata.get("tool_name", "unknown"))
        summary = envelope.content[:60].replace("\n", " ")
        self._buffer.append((tool_name, content_hash, summary))
        return False

    def get_reference(
        self,
        envelope: ContentEnvelope,
        session: SessionContext,
    ) -> str:
        """Return a backreference string for previously-seen content."""
        content_hash = self._hash(envelope.content)

        for idx, (tool_name, stored_hash, summary) in enumerate(self._buffer, start=1):
            if stored_hash == content_hash:
                return f"[Same as call #{idx} ({tool_name}): {summary}]"

        return f"[Reference not found for content]"

    @staticmethod
    def _hash(content: str) -> str:
        """Compute SHA-256 hex digest of content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
