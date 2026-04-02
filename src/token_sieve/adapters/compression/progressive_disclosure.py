"""ProgressiveDisclosureStrategy: summary + file pointer for large results.

Returns a compressed summary of oversized content plus a temp file pointer
to the full result. Uses SentenceScorer for extractive summaries when
available, falls back to head truncation.

Satisfies CompressionStrategy protocol structurally.
"""

from __future__ import annotations

import dataclasses
import os
import stat
import tempfile

from token_sieve.domain.counters import CharEstimateCounter
from token_sieve.domain.model import ContentEnvelope


class ProgressiveDisclosureStrategy:
    """Return compressed summary + file pointer for oversized results.

    Satisfies CompressionStrategy protocol structurally.

    Args:
        threshold_tokens: Token count above which content is disclosed
            progressively (default 10000).
        summary_tokens: Approximate token count for the summary (default 200).
        output_dir: Directory for temp files (default: system temp dir).
    """

    def __init__(
        self,
        threshold_tokens: int = 10000,
        summary_tokens: int = 200,
        output_dir: str | None = None,
    ) -> None:
        self.threshold_tokens = threshold_tokens
        self.summary_tokens = summary_tokens
        self._output_dir = output_dir
        self._counter = CharEstimateCounter()
        self._created_files: list[str] = []

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Return True when content exceeds the token threshold."""
        token_count = self._counter.count(envelope.content)
        return token_count > self.threshold_tokens

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Extract summary, write full content to file, return envelope."""
        content = envelope.content
        content_bytes = content.encode("utf-8")
        byte_count = len(content_bytes)

        # Generate summary
        summary = self._generate_summary(content)

        # Write full content to temp file
        f = tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".txt",
            prefix="token-sieve-prog-",
            dir=self._output_dir,
            delete=False,
        )
        try:
            f.write(content_bytes)
        finally:
            f.close()

        # Restrict to owner-only access (0o600) — defense-in-depth
        # against permissive umask on some Linux configurations.
        os.chmod(f.name, stat.S_IRUSR | stat.S_IWUSR)

        self._created_files.append(f.name)

        # Build structured envelope
        result = (
            f"[token-sieve/progressive]\n"
            f"Summary: {summary}\n"
            f"Full result: {f.name} ({byte_count} bytes)\n"
            f'To read: call read_file("{f.name}")'
        )

        return dataclasses.replace(envelope, content=result)

    def cleanup(self) -> None:
        """Remove all temp files created by this strategy instance."""
        for path in self._created_files:
            try:
                os.unlink(path)
            except OSError:
                pass
        self._created_files.clear()

    def _generate_summary(self, content: str) -> str:
        """Generate extractive summary or head-truncation fallback."""
        # Try SentenceScorer if available
        try:
            from token_sieve.adapters.compression.sentence_scorer import (
                SentenceScorer,
                _SUMY_AVAILABLE,
            )

            if _SUMY_AVAILABLE:
                from token_sieve.domain.model import ContentEnvelope, ContentType

                temp_envelope = ContentEnvelope(
                    content=content, content_type=ContentType.TEXT
                )
                scorer = SentenceScorer(sentence_count=3)
                if scorer.can_handle(temp_envelope):
                    result = scorer.compress(temp_envelope)
                    if result.content != content:
                        return result.content
        except Exception:
            pass

        # Fallback: head truncation to summary_tokens
        char_limit = self.summary_tokens * 4  # ~4 chars per token
        if len(content) <= char_limit:
            return content
        return content[:char_limit].rstrip() + "..."
