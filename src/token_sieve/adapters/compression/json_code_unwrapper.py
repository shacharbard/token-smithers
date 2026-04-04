"""Unwrap code embedded in JSON envelopes.

MCP tool responses often wrap source code in a JSON object with fields
like ``source``, ``code``, ``body``, ``content``, or ``text``. This
adapter detects those patterns and extracts the code string, removing
the JSON overhead so downstream AST adapters receive raw source.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from token_sieve.domain.model import ContentEnvelope

# Recognised field names that typically hold code, in priority order.
_CODE_FIELDS: tuple[str, ...] = ("source", "code", "body", "content", "text")

# Values shorter than this are considered too small to be meaningful code.
_MIN_CODE_LENGTH = 10


class JsonCodeUnwrapper:
    """Extract code strings from JSON wrapper objects.

    Satisfies CompressionStrategy protocol structurally.
    """

    def __init__(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Accept kwargs for AdapterConfig.settings forward-compatibility."""

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Return True if content is JSON containing a recognised code field."""
        try:
            parsed = json.loads(envelope.content)
        except (json.JSONDecodeError, ValueError, TypeError):
            return False

        if not isinstance(parsed, dict):
            return False

        return self._find_code_field(parsed) is not None

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Extract the code string from a JSON wrapper, if present."""
        try:
            parsed = json.loads(envelope.content)
        except (json.JSONDecodeError, ValueError, TypeError):
            return envelope

        if not isinstance(parsed, dict):
            return envelope

        code = self._find_code_field(parsed)
        if code is None:
            return envelope

        return dataclasses.replace(envelope, content=code)

    @staticmethod
    def _find_code_field(obj: dict[str, Any]) -> str | None:
        """Return the first code field value that meets the minimum length."""
        for field in _CODE_FIELDS:
            value = obj.get(field)
            if isinstance(value, str) and len(value) >= _MIN_CODE_LENGTH:
                return value
        return None
