"""SentenceScorer: TextRank-based prose extraction via sumy.

Extracts the most important sentences from prose content using TextRank
(or LSA as fallback). Sumy is an optional dependency — if unavailable,
compress() returns content unchanged (error boundary pattern).

Satisfies CompressionStrategy protocol structurally.
"""

from __future__ import annotations

import dataclasses
import re

from token_sieve.domain.model import ContentEnvelope

# Try importing sumy — graceful fallback if missing
_SUMY_AVAILABLE = False
try:
    from sumy.nlp.tokenizers import Tokenizer
    from sumy.parsers.plaintext import PlaintextParser
    from sumy.summarizers.text_rank import TextRankSummarizer
    from sumy.summarizers.lsa import LsaSummarizer

    _SUMY_AVAILABLE = True
except ImportError:
    pass


# Minimum thresholds for prose detection
_MIN_WORD_COUNT = 100
_MIN_SENTENCE_COUNT = 5


class SentenceScorer:
    """Extract top-K sentences from prose content via TextRank/LSA.

    Satisfies CompressionStrategy protocol structurally.

    Args:
        sentence_count: Number of top sentences to extract (default 5).
        algorithm: Summarization algorithm — 'textrank' or 'lsa' (default 'textrank').
    """

    deterministic = True

    def __init__(
        self,
        sentence_count: int = 5,
        algorithm: str = "textrank",
    ) -> None:
        self.sentence_count = sentence_count
        self.algorithm = algorithm

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Return True for prose content with enough sentences and words."""
        content = envelope.content
        # Word count check
        words = content.split()
        if len(words) < _MIN_WORD_COUNT:
            return False
        # Sentence count check: count sentence-ending punctuation
        sentences = re.split(r'[.!?]+', content)
        # Filter empty fragments
        sentences = [s.strip() for s in sentences if s.strip()]
        return len(sentences) >= _MIN_SENTENCE_COUNT

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Extract top-K sentences using TextRank/LSA via sumy."""
        if not _SUMY_AVAILABLE:
            return envelope

        try:
            parser = PlaintextParser.from_string(
                envelope.content, Tokenizer("english")
            )

            if self.algorithm == "lsa":
                summarizer = LsaSummarizer()
            else:
                summarizer = TextRankSummarizer()

            sentences = summarizer(
                parser.document, self.sentence_count
            )

            extracted = " ".join(str(s) for s in sentences)

            if not extracted:
                return envelope

            return dataclasses.replace(envelope, content=extracted)
        except Exception:
            # Error boundary: any sumy failure returns content unchanged
            return envelope
