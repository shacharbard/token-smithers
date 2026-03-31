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
        # Buffer entries: (tool_name, content_hash, summary, call_number)
        self._buffer: deque[tuple[str, str, str, int]] = deque(maxlen=max_window)
        self._min_content_length = min_content_length
        self._call_counter: int = 0

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
        for i, (tool_name, stored_hash, summary, call_num) in enumerate(
            self._buffer
        ):
            if stored_hash == content_hash:
                # Refresh: remove old entry, re-append at end to prevent eviction
                del self._buffer[i]
                self._buffer.append((tool_name, stored_hash, summary, call_num))
                return True

        # Not a duplicate — record in buffer with monotonic call number
        self._call_counter += 1
        tool_name = str(envelope.metadata.get("tool_name", "unknown"))
        summary = envelope.content[:60].replace("\n", " ")
        self._buffer.append((tool_name, content_hash, summary, self._call_counter))
        return False

    def get_reference(
        self,
        envelope: ContentEnvelope,
        session: SessionContext,
    ) -> str:
        """Return a backreference string for previously-seen content."""
        content_hash = self._hash(envelope.content)

        for tool_name, stored_hash, summary, call_num in self._buffer:
            if stored_hash == content_hash:
                return f"[Same as call #{call_num} ({tool_name}): {summary}]"

        return "[Reference not found for content]"

    @staticmethod
    def _hash(content: str) -> str:
        """Compute SHA-256 hex digest of content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
