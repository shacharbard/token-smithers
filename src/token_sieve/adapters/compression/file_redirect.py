"""FileRedirectStrategy: write oversized results to temp files.

When content exceeds a configurable token threshold, writes the full
content to a temporary file and returns a pointer envelope with the
file path and byte count. This prevents massive results from consuming
the context window.

Satisfies CompressionStrategy protocol structurally.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import tempfile

from token_sieve.domain.counters import CharEstimateCounter
from token_sieve.domain.model import ContentEnvelope


class FileRedirectStrategy:
    """Write oversized results to temp files, return pointer envelope.

    Satisfies CompressionStrategy protocol structurally.
    Tracks created files and provides cleanup() for removal.

    Args:
        threshold_tokens: Token count above which content is redirected (default 10000).
        output_dir: Directory for temp files (default: system temp dir).
    """

    def __init__(
        self,
        threshold_tokens: int = 10000,
        output_dir: str | None = None,
    ) -> None:
        self.threshold_tokens = threshold_tokens
        self._output_dir = output_dir
        self._counter = CharEstimateCounter()
        self._created_files: list[str] = []

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Return True when content exceeds the token threshold."""
        token_count = self._counter.count(envelope.content)
        return token_count > self.threshold_tokens

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Write content to temp file and return pointer envelope."""
        content_bytes = envelope.content.encode("utf-8")
        byte_count = len(content_bytes)

        # Deterministic filename based on content hash for cache alignment:
        # identical content always produces the same file path.
        content_hash = hashlib.sha256(content_bytes).hexdigest()[:12]
        out_dir = self._output_dir or tempfile.gettempdir()
        file_path = os.path.join(out_dir, f"token-sieve-{content_hash}.txt")

        with open(file_path, "wb") as f:
            f.write(content_bytes)

        self._created_files.append(file_path)
        pointer = f"Result written to {file_path}, {byte_count} bytes"
        return dataclasses.replace(envelope, content=pointer)

    def cleanup(self) -> None:
        """Remove all temp files created by this strategy instance."""
        for path in self._created_files:
            try:
                os.unlink(path)
            except OSError:
                pass
        self._created_files.clear()
