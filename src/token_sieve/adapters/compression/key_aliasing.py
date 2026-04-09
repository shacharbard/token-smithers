"""KeyAliasingStrategy: session-scoped symbol table for repeated long keys.

For JSON content with frequently repeated long keys, builds a short alias
table (k0, k1, ...) and substitutes throughout. Prepends a parseable
alias header so the LLM can dereference.

Satisfies CompressionStrategy protocol structurally.
"""

from __future__ import annotations

import dataclasses
import json
from collections import Counter

from token_sieve.adapters.compression._json_utils import (
    JSON_START_RE as _JSON_START_RE,
    try_parse_json,
)
from token_sieve.domain.model import ContentEnvelope


class KeyAliasingStrategy:
    """Replace repeated long JSON keys with short aliases.

    Satisfies CompressionStrategy protocol structurally.

    Args:
        min_occurrences: Minimum times a key must appear to qualify (default 5).
        min_key_length: Minimum character length of key to qualify (default 10).
    """

    deterministic = True

    def __init__(
        self,
        min_occurrences: int = 5,
        min_key_length: int = 10,
    ) -> None:
        self.min_occurrences = min_occurrences
        self.min_key_length = min_key_length

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Return True if content is JSON with qualifying repeated long keys."""
        content = envelope.content.strip()
        if not _JSON_START_RE.match(content):
            return False

        parsed = try_parse_json(content)
        if parsed is None:
            return False

        key_counts = Counter()
        _collect_keys(parsed, key_counts)

        return any(
            count >= self.min_occurrences and len(key) >= self.min_key_length
            for key, count in key_counts.items()
        )

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Alias qualifying keys and prepend alias header."""
        content = envelope.content.strip()
        parsed = try_parse_json(content)
        if parsed is None:
            return envelope

        # Collect key frequencies
        key_counts: Counter[str] = Counter()
        _collect_keys(parsed, key_counts)

        # Build alias table for qualifying keys (sorted for determinism)
        qualifying = sorted(
            key
            for key, count in key_counts.items()
            if count >= self.min_occurrences and len(key) >= self.min_key_length
        )

        if not qualifying:
            return envelope

        alias_map: dict[str, str] = {}
        for i, key in enumerate(qualifying):
            alias_map[key] = f"k{i}"

        # Apply aliases to the parsed structure
        aliased = _apply_aliases(parsed, alias_map)

        # Serialize back to compact JSON
        body = json.dumps(aliased, separators=(",", ":"))

        # Build header: # aliases: k0=originalKey, k1=otherKey
        alias_decls = ", ".join(
            f"{alias}={original}"
            for original, alias in sorted(alias_map.items(), key=lambda x: x[1])
        )
        header = f"# aliases: {alias_decls}"

        compressed = f"{header}\n{body}"
        return dataclasses.replace(envelope, content=compressed)


def _collect_keys(obj: object, counter: Counter[str]) -> None:
    """Recursively collect all keys from a JSON-like structure."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            counter[key] += 1
            _collect_keys(value, counter)
    elif isinstance(obj, list):
        for item in obj:
            _collect_keys(item, counter)


def _apply_aliases(obj: object, alias_map: dict[str, str]) -> object:
    """Recursively replace keys in a JSON-like structure using alias_map."""
    if isinstance(obj, dict):
        return {
            alias_map.get(key, key): _apply_aliases(value, alias_map)
            for key, value in obj.items()
        }
    elif isinstance(obj, list):
        return [_apply_aliases(item, alias_map) for item in obj]
    return obj
