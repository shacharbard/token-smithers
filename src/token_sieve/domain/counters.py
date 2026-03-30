"""Token counting implementations.

CharEstimateCounter provides a zero-dependency chars/4 approximation.
Zero external dependencies -- stdlib only.
"""

from __future__ import annotations


class CharEstimateCounter:
    """Estimate token count as chars // 4.

    Returns 0 for empty strings, minimum 1 for any non-empty text.
    Approximately 75% accurate compared to real tokenizers.
    """

    def count(self, text: str) -> int:
        """Count estimated tokens using chars/4 formula."""
        if not text:
            return 0
        return max(1, len(text) // 4)
