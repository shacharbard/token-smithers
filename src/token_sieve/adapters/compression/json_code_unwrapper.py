"""Unwrap code embedded in JSON envelopes.

MCP tool responses often wrap source code in a JSON object with fields
like ``source``, ``code``, ``body``, ``content``, or ``text``. This
adapter detects those patterns and extracts the code string, removing
the JSON overhead so downstream AST adapters receive raw source.
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import Any

from token_sieve.domain.model import ContentEnvelope

# Recognised field names that typically hold code, in priority order.
_CODE_FIELDS: tuple[str, ...] = ("source", "code", "body", "content", "text")

# Values shorter than this are considered too small to be meaningful code.
# Per design spec (Decision 7): must be >500 chars.
_MIN_CODE_LENGTH = 500

# Code signal patterns — the value must contain at least one of these
# to be considered plausible source code (not arbitrary prose/HTML).
_CODE_SIGNAL_RE = re.compile(
    r"(?:"
    r"\bdef\s+"
    r"|\bclass\s+"
    r"|\bfunction\s+"
    r"|\bimport\s+"
    r"|\bstruct\s+"
    r"|\bfn\s+"
    r"|\bpub\s+"
    r"|\bpackage\s+"
    r"|\binterface\s+"
    r"|#include\b"
    r"|\bconst\s+"
    r"|\blet\s+"
    r"|\bvar\s+"
    r"|=>"
    r"|->"
    r")"
)


class JsonCodeUnwrapper:
    """Extract code strings from JSON wrapper objects.

    Satisfies CompressionStrategy protocol structurally.
    """

    deterministic = True

    def __init__(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Accept kwargs for AdapterConfig.settings forward-compatibility."""
        self._last_parsed: dict[str, Any] | None = None
        self._last_content_id: str | None = None

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Return True if content is JSON containing a recognised code field."""
        try:
            parsed = json.loads(envelope.content)
        except (json.JSONDecodeError, ValueError, TypeError):
            return False

        if not isinstance(parsed, dict):
            return False

        # Cache parsed result to avoid double-parsing in compress()
        self._last_parsed = parsed
        self._last_content_id = id(envelope.content)

        return self._find_code_field(parsed) is not None

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Extract the code string from a JSON wrapper, if present."""
        # Reuse cached parse from can_handle() if available
        if (
            self._last_parsed is not None
            and self._last_content_id == id(envelope.content)
        ):
            parsed = self._last_parsed
        else:
            try:
                parsed = json.loads(envelope.content)
            except (json.JSONDecodeError, ValueError, TypeError):
                return envelope

            if not isinstance(parsed, dict):
                return envelope

        # Clear cache
        self._last_parsed = None
        self._last_content_id = None

        code = self._find_code_field(parsed)
        if code is None:
            return envelope

        # Preserve original JSON in metadata per design spec
        new_metadata = dict(envelope.metadata) if envelope.metadata else {}
        new_metadata["json_wrapper"] = envelope.content

        return dataclasses.replace(envelope, content=code, metadata=new_metadata)

    @staticmethod
    def _find_code_field(obj: dict[str, Any]) -> str | None:
        """Return the first code field value that meets length and code-signal checks."""
        for field in _CODE_FIELDS:
            value = obj.get(field)
            if isinstance(value, str) and len(value) >= _MIN_CODE_LENGTH:
                if _CODE_SIGNAL_RE.search(value):
                    return value
        return None
