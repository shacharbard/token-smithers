"""WhitespaceNormalizer -- strips pretty-print indentation and excess whitespace.

Lossless cleanup adapter: compacts JSON to minimal separators, collapses
multiple blank lines, strips trailing whitespace. Typically saves 10-30%.
"""

from __future__ import annotations

import dataclasses
import json
import re

from token_sieve.domain.model import ContentEnvelope, ContentType


class WhitespaceNormalizer:
    """Normalize whitespace in text, JSON, and code content.

    Satisfies CompressionStrategy protocol structurally.
    """

    deterministic = True

    _HANDLED_TYPES = frozenset({ContentType.TEXT, ContentType.JSON, ContentType.CODE})

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Accept TEXT, JSON, and CODE content types."""
        return envelope.content_type in self._HANDLED_TYPES

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Strip excess whitespace, compact JSON, collapse blank lines."""
        content = envelope.content

        if envelope.content_type == ContentType.JSON:
            content = self._compact_json(content)
        else:
            content = self._normalize_text(content)

        if content == envelope.content:
            return envelope

        return dataclasses.replace(envelope, content=content)

    def _compact_json(self, text: str) -> str:
        """Parse and re-serialize JSON with minimal separators."""
        try:
            parsed = json.loads(text)
            return json.dumps(
                parsed, separators=(",", ":"), ensure_ascii=False, sort_keys=True
            )
        except (json.JSONDecodeError, ValueError):
            return self._normalize_text(text)

    def _normalize_text(self, text: str) -> str:
        """Collapse blank lines and strip trailing whitespace per line."""
        # Strip trailing whitespace from each line
        lines = [line.rstrip() for line in text.split("\n")]
        # Collapse 3+ consecutive blank lines into one blank line
        result: list[str] = []
        blank_count = 0
        for line in lines:
            if not line:
                blank_count += 1
                if blank_count <= 1:
                    result.append(line)
            else:
                blank_count = 0
                result.append(line)
        return "\n".join(result)
