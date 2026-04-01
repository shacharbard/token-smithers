"""Semantic diff compression strategy.

Returns only the changes when a tool result is re-read with the same
arguments. Uses DiffStateStore for LRU-bounded previous result storage.
Produces human-readable diff format with Added/Removed/Changed sections.
"""

from __future__ import annotations

import difflib
import json
from typing import Any

from token_sieve.adapters.cache.diff_state_store import DiffStateStore
from token_sieve.domain.model import ContentEnvelope, ContentType


class SemanticDiffStrategy:
    """Compression strategy that returns diffs on re-reads.

    First call for a tool+args pair stores the result and returns it unchanged.
    Subsequent calls with the same tool+args compare against the stored result
    and return a human-readable diff.

    Implements the CompressionStrategy Protocol.
    """

    def __init__(self, store: DiffStateStore) -> None:
        self._store = store

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Handle text envelopes that have source_tool metadata."""
        if envelope.content_type not in (
            ContentType.TEXT, ContentType.JSON, ContentType.CODE, ContentType.CLI_OUTPUT,
        ):
            return False
        return "source_tool" in envelope.metadata

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Return diff if previous result exists, else store and return as-is."""
        tool_name = envelope.metadata.get("source_tool", "")
        args_str = envelope.metadata.get("source_args", "")
        args: dict[str, Any] | None = None
        if args_str:
            try:
                args = json.loads(args_str)
            except (json.JSONDecodeError, TypeError):
                args = None

        previous = self._store.get_previous(tool_name, args)
        self._store.store_result(tool_name, args, envelope.content)

        if previous is None:
            # First call — return full content
            return envelope

        if previous == envelope.content:
            # No changes
            return ContentEnvelope(
                content="[No changes since last read]",
                content_type=envelope.content_type,
                metadata=envelope.metadata,
            )

        # Compute human-readable diff
        diff_text = self._compute_diff(previous, envelope.content)
        return ContentEnvelope(
            content=diff_text,
            content_type=envelope.content_type,
            metadata=envelope.metadata,
        )

    @staticmethod
    def _compute_diff(old: str, new: str) -> str:
        """Produce a human-readable diff with Added/Removed/Changed sections."""
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)

        added: list[str] = []
        removed: list[str] = []

        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "insert":
                for line in new_lines[j1:j2]:
                    added.append(line.rstrip("\n"))
            elif tag == "delete":
                for line in old_lines[i1:i2]:
                    removed.append(line.rstrip("\n"))
            elif tag == "replace":
                for line in old_lines[i1:i2]:
                    removed.append(line.rstrip("\n"))
                for line in new_lines[j1:j2]:
                    added.append(line.rstrip("\n"))

        parts: list[str] = ["[Changes detected]"]
        if removed:
            parts.append("Removed:")
            for line in removed:
                parts.append(f"  - {line}")
        if added:
            parts.append("Added:")
            for line in added:
                parts.append(f"  + {line}")
        if not removed and not added:
            # Edge case: whitespace-only changes
            parts.append("Changed: whitespace-only differences")

        return "\n".join(parts)
