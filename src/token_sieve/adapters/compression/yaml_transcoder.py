"""YamlTranscoder -- JSON-to-YAML format transcoding.

Converts non-tabular JSON to YAML representation for 15-25% token savings.
YAML eliminates braces, brackets, and most quotes, using indentation instead.

Defers to ToonCompressor for uniform JSON arrays (TOON gets better savings
on tabular data). Sets transformed_by metadata guard to prevent
double-transformation.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import yaml

from token_sieve.domain.model import ContentEnvelope


class YamlTranscoder:
    """JSON-to-YAML format transcoding for token savings.

    Satisfies CompressionStrategy protocol structurally.
    """

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Accept valid JSON that is not already transformed and not TOON-eligible."""
        if envelope.metadata.get("transformed_by"):
            return False

        parsed = self._try_parse_json(envelope.content)
        if parsed is None:
            return False

        # Defer uniform arrays to ToonCompressor (better savings)
        if self._is_toon_eligible(parsed):
            return False

        return True

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Convert JSON content to YAML format."""
        parsed = self._try_parse_json(envelope.content)
        if parsed is None:
            return envelope

        yaml_content = yaml.dump(
            parsed,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        new_metadata = dict(envelope.metadata)
        new_metadata["transformed_by"] = "yaml_transcoder"

        return dataclasses.replace(
            envelope,
            content=yaml_content,
            metadata=new_metadata,
        )

    @staticmethod
    def _try_parse_json(content: str) -> Any | None:
        """Try to parse content as JSON. Returns parsed data or None."""
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _is_toon_eligible(data: Any) -> bool:
        """Check if data is a uniform array eligible for ToonCompressor.

        Uniform = list of 2+ dicts with identical key sets.
        """
        if not isinstance(data, list) or len(data) < 2:
            return False

        if not all(isinstance(item, dict) for item in data):
            return False

        first_keys = set(data[0].keys())
        if not first_keys:
            return False

        return all(set(item.keys()) == first_keys for item in data[1:])
