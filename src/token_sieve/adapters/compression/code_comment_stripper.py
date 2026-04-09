"""CodeCommentStripper -- lossy compression adapter for source code.

Removes full-line comments (# for Python, // for JS/TS), docstrings
(triple-quote blocks), and multi-line block comments (/* */ for JS/TS).
Inline comments on code lines are preserved (safer default).

Off by default (lossy). Requires explicit ``enabled=True`` opt-in.
"""

from __future__ import annotations

import dataclasses
import re

from token_sieve.adapters.compression.summary_marker import format_summary_marker
from token_sieve.domain.model import ContentEnvelope, ContentType

# Code-like patterns that signal the content is source code
_CODE_KEYWORDS = re.compile(
    r"^\s*(def |class |function |import |from |const |let |var |export )",
    re.MULTILINE,
)

_MIN_CODE_SIGNALS = 2  # Require at least 2 code keywords for TEXT content


class CodeCommentStripper:
    """Remove comments and docstrings from source code.

    Satisfies CompressionStrategy protocol structurally.
    Lossy adapter: off by default, opt-in via ``enabled=True``.
    """

    deterministic = True

    def __init__(self, *, enabled: bool = False) -> None:
        self._enabled = enabled

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Return True only if enabled AND content is code.

        Detection: ContentType.CODE always qualifies. For TEXT,
        requires 2+ code-keyword lines (Decision 11: multi-signal).
        """
        if not self._enabled:
            return False
        if envelope.content_type == ContentType.CODE:
            return True
        # For non-CODE types, check for code-like patterns
        matches = _CODE_KEYWORDS.findall(envelope.content)
        return len(matches) >= _MIN_CODE_SIGNALS

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Remove comments and docstrings, append summary marker."""
        content = envelope.content
        original_lines = content.split("\n")
        original_count = len(original_lines)

        # Step 1: Remove multi-line constructs (docstrings, /* */ blocks)
        content = self._strip_docstrings(content)
        content = self._strip_block_comments(content)

        # Step 2: Remove full-line comments (# and //)
        lines = content.split("\n")
        kept_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            # Full-line Python comment
            if stripped.startswith("#"):
                continue
            # Full-line JS/TS comment
            if stripped.startswith("//"):
                continue
            kept_lines.append(line)

        # Remove excessive blank lines (more than 2 consecutive)
        final_lines: list[str] = []
        blank_count = 0
        for line in kept_lines:
            if not line.strip():
                blank_count += 1
                if blank_count <= 2:
                    final_lines.append(line)
            else:
                blank_count = 0
                final_lines.append(line)

        kept_count = len(final_lines)
        marker = format_summary_marker(
            adapter_name="CodeCommentStripper",
            original_count=original_count,
            kept_count=kept_count,
        )
        compressed_content = "\n".join(final_lines).rstrip() + "\n" + marker

        return dataclasses.replace(envelope, content=compressed_content)

    @staticmethod
    def _strip_docstrings(content: str) -> str:
        """Remove Python triple-quote docstrings."""
        # Match triple-quoted strings (both ''' and \"\"\")
        # Non-greedy match across newlines
        content = re.sub(
            r'"""[\s\S]*?"""',
            "",
            content,
        )
        content = re.sub(
            r"'''[\s\S]*?'''",
            "",
            content,
        )
        return content

    @staticmethod
    def _strip_block_comments(content: str) -> str:
        """Remove JS/TS /* */ and /** */ block comments."""
        content = re.sub(
            r"/\*[\s\S]*?\*/",
            "",
            content,
        )
        return content
