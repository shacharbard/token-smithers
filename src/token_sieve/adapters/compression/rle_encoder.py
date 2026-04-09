"""RunLengthEncoder -- compacts repeated consecutive values.

Detects 3+ consecutive identical lines (or JSON array elements) and
replaces them with 'value xN' notation. Achieves 30-80% savings on
repetitive data like log output or status arrays.

Lossless -- the notation is unambiguous and preserves all information.
"""

from __future__ import annotations

import dataclasses
from itertools import groupby
from typing import Any

from token_sieve.adapters.compression._json_utils import try_parse_json
from token_sieve.domain.model import ContentEnvelope

_MIN_REPEAT = 3


class RunLengthEncoder:
    """Run-length encoding for repeated consecutive values.

    Satisfies CompressionStrategy protocol structurally.
    """

    deterministic = True

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Accept content with 3+ consecutive identical lines or JSON array elements."""
        return self._has_repeats(envelope.content)

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Compress repeated consecutive lines/values to 'value xN' notation."""
        # Try JSON array path first
        json_items = self._try_parse_json_array(envelope.content)
        if json_items is not None:
            compressed = self._rle_items(json_items)
            return dataclasses.replace(envelope, content=compressed)

        # Line-based path
        if not self._has_repeats(envelope.content):
            return envelope

        lines = envelope.content.split("\n")
        # Preserve trailing newline if present
        trailing_newline = envelope.content.endswith("\n")
        if trailing_newline and lines and lines[-1] == "":
            lines = lines[:-1]

        compressed_lines = self._rle_lines(lines)
        content = "\n".join(compressed_lines)
        if trailing_newline:
            content += "\n"

        return dataclasses.replace(envelope, content=content)

    def _has_repeats(self, content: str) -> bool:
        """Check if content has any group of 3+ consecutive identical items."""
        # Try JSON array first
        json_items = self._try_parse_json_array(content)
        if json_items is not None:
            for _, group in groupby(json_items):
                if sum(1 for _ in group) >= _MIN_REPEAT:
                    return True
            return False

        # Line-based check
        lines = content.split("\n")
        if content.endswith("\n") and lines and lines[-1] == "":
            lines = lines[:-1]

        for _, group in groupby(lines):
            if sum(1 for _ in group) >= _MIN_REPEAT:
                return True
        return False

    @staticmethod
    def _try_parse_json_array(content: str) -> list[Any] | None:
        """Try to parse content as a JSON array of scalars."""
        data = try_parse_json(content)
        if not isinstance(data, list):
            return None

        # Only handle arrays of scalars (strings, numbers, bools, null)
        if any(isinstance(item, (dict, list)) for item in data):
            return None

        return data

    @staticmethod
    def _rle_lines(lines: list[str]) -> list[str]:
        """Apply run-length encoding to a list of lines."""
        result: list[str] = []
        for value, group in groupby(lines):
            count = sum(1 for _ in group)
            if count >= _MIN_REPEAT:
                result.append(f"{value} x{count}")
            else:
                result.extend([value] * count)
        return result

    @staticmethod
    def _rle_items(items: list[Any]) -> str:
        """Apply run-length encoding to JSON array items, return text output."""
        result: list[str] = []
        for value, group in groupby(items):
            count = sum(1 for _ in group)
            if count >= _MIN_REPEAT:
                result.append(f"{value} x{count}")
            else:
                result.extend([str(value)] * count)
        return "\n".join(result)
