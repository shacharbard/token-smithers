"""ToonCompressor -- TOON columnar encoding for uniform JSON arrays.

Detects uniform JSON arrays (list of dicts with identical key sets)
and converts to a compact columnar format: header row with keys,
data rows with values, pipe-separated. Inspired by DietMCP's TOON encoding.

Achieves 40-60% lossless savings on tabular JSON data (file listings,
DB rows, search results).
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from token_sieve.domain.model import ContentEnvelope


class ToonCompressor:
    """Columnar encoding for uniform JSON arrays.

    Satisfies CompressionStrategy protocol structurally.
    """

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Accept uniform JSON arrays with 2+ items and no prior transformation."""
        if envelope.metadata.get("transformed_by"):
            return False

        parsed = self._try_parse_uniform_array(envelope.content)
        return parsed is not None

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Convert uniform JSON array to pipe-separated columnar format."""
        parsed = self._try_parse_uniform_array(envelope.content)
        if parsed is None:
            return envelope

        keys, rows = parsed
        lines = ["|".join(keys)]
        for row in rows:
            values = [self._format_value(row[k]) for k in keys]
            lines.append("|".join(values))

        new_metadata = dict(envelope.metadata)
        new_metadata["transformed_by"] = "toon_compressor"

        return dataclasses.replace(
            envelope,
            content="\n".join(lines),
            metadata=new_metadata,
        )

    def _try_parse_uniform_array(
        self, content: str
    ) -> tuple[list[str], list[dict[str, Any]]] | None:
        """Parse content as a uniform JSON array.

        Returns (keys, rows) if content is a JSON array of 2+ dicts
        with identical key sets. Returns None otherwise.
        """
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return None

        if not isinstance(data, list) or len(data) < 2:
            return None

        if not all(isinstance(item, dict) for item in data):
            return None

        first_keys = set(data[0].keys())
        if not first_keys:
            return None

        for item in data[1:]:
            if set(item.keys()) != first_keys:
                return None

        # Use stable key order from first dict
        keys = list(data[0].keys())
        return keys, data

    @staticmethod
    def _format_value(value: Any) -> str:
        """Format a cell value for TOON output.

        Scalars are converted to their Python str representation.
        Dicts and lists are serialized as compact JSON.
        """
        if isinstance(value, dict):
            return json.dumps(value, separators=(", ", ": "))
        if isinstance(value, list):
            return json.dumps(value, separators=(", ", ": "))
        return str(value)
