"""NullFieldElider -- removes null, empty string, empty list, empty dict fields.

Lossless cleanup adapter: absent = default convention. Recursively removes
empty fields from JSON structures. Typically saves 20-60%.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from token_sieve.adapters.compression._json_utils import try_parse_json
from token_sieve.domain.model import ContentEnvelope, ContentType


# Sentinel values considered "empty" for elision
_EMPTY_VALUES: tuple[Any, ...] = (None, "", [], {})


class NullFieldElider:
    """Remove null and empty fields from JSON content.

    Satisfies CompressionStrategy protocol structurally.
    """

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Accept all content types -- attempts JSON parse, passes through on failure."""
        return True

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Remove null/empty fields from JSON content."""
        parsed = try_parse_json(envelope.content)
        if parsed is None:
            return envelope

        cleaned = self._elide(parsed)
        result = json.dumps(
            cleaned, separators=(",", ":"), ensure_ascii=False, sort_keys=True
        )

        if result == envelope.content:
            return envelope

        return dataclasses.replace(envelope, content=result)

    def _elide(self, obj: Any) -> Any:
        """Recursively remove empty values from dicts and process lists."""
        if isinstance(obj, dict):
            cleaned = {}
            for key, value in obj.items():
                processed = self._elide(value)
                if processed not in _EMPTY_VALUES:
                    cleaned[key] = processed
            return cleaned
        if isinstance(obj, list):
            return [self._elide(item) for item in obj]
        return obj
