"""YamlTranscoder -- JSON-to-YAML format transcoding.

Converts non-tabular JSON to YAML representation for 15-25% token savings.
YAML eliminates braces, brackets, and most quotes, using indentation instead.

Defers to ToonCompressor for uniform JSON arrays (TOON gets better savings
on tabular data). Sets transformed_by metadata guard to prevent
double-transformation.
"""

from __future__ import annotations

import dataclasses

import yaml

from token_sieve.adapters.compression._json_utils import try_parse_json
from token_sieve.adapters.compression.toon_compressor import ToonCompressor
from token_sieve.domain.model import ContentEnvelope


class YamlTranscoder:
    """JSON-to-YAML format transcoding for token savings.

    Satisfies CompressionStrategy protocol structurally.
    """

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Accept valid JSON that is not already transformed and not TOON-eligible."""
        if envelope.metadata.get("transformed_by"):
            return False

        parsed = try_parse_json(envelope.content)
        if parsed is None:
            return False

        # Defer uniform arrays to ToonCompressor (better savings)
        if ToonCompressor.is_uniform_array(parsed):
            return False

        return True

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Convert JSON content to YAML format."""
        parsed = try_parse_json(envelope.content)
        if parsed is None:
            return envelope

        yaml_content = yaml.dump(
            parsed,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=True,
        )

        # Pre-regret size guard: skip if YAML is not smaller than original JSON
        if len(yaml_content) >= len(envelope.content):
            return envelope

        new_metadata = dict(envelope.metadata)
        new_metadata["transformed_by"] = "yaml_transcoder"

        return dataclasses.replace(
            envelope,
            content=yaml_content,
            metadata=new_metadata,
        )
