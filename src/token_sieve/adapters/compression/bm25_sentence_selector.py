"""BM25-based sentence selector for relevance-aware content compression.

Scores sentences against the source tool name/context using BM25 ranking,
keeping the most relevant sentences. Falls back to simple term-frequency
scoring when ``rank_bm25`` is not installed.

Satisfies CompressionStrategy protocol structurally.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING

from token_sieve.adapters.compression.summary_marker import format_summary_marker
from token_sieve.domain.model import ContentEnvelope, ContentType

if TYPE_CHECKING:
    pass

# Sentence boundary regex — split on period/excl/question followed by space or EOL
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

_MIN_SENTENCES_DEFAULT = 5


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, filtering empty fragments."""
    parts = _SENTENCE_RE.split(text)
    return [s.strip() for s in parts if s.strip()]


def _estimate_tokens(text: str) -> int:
    """Estimate token count as chars // 4."""
    if not text:
        return 0
    return max(1, len(text) // 4)


class BM25SentenceSelector:
    """Select top-K sentences by BM25 relevance to source tool context.

    Satisfies CompressionStrategy protocol structurally.

    Args:
        threshold_tokens: Minimum estimated token count to trigger compression.
        keep_ratio: Fraction of sentences to keep (default 0.2 = 20%).
        min_sentences: Minimum sentences to keep regardless of ratio.
    """

    def __init__(
        self,
        *,
        threshold_tokens: int = 2000,
        keep_ratio: float = 0.2,
        min_sentences: int = _MIN_SENTENCES_DEFAULT,
    ) -> None:
        self._threshold_tokens = threshold_tokens
        self._keep_ratio = keep_ratio
        self._min_sentences = min_sentences

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Return True for TEXT content exceeding the token threshold."""
        if envelope.content_type != ContentType.TEXT:
            return False
        return _estimate_tokens(envelope.content) > self._threshold_tokens

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Compress by selecting top-K sentences ranked by BM25 relevance."""
        sentences = _split_sentences(envelope.content)
        if len(sentences) <= self._min_sentences:
            return envelope

        query = str(envelope.metadata.get("source_tool", ""))
        k = max(self._min_sentences, int(len(sentences) * self._keep_ratio))

        scored = self._score_sentences(sentences, query)
        # Sort by score descending, take top-K
        top_k_indices = sorted(
            range(len(scored)), key=lambda i: scored[i], reverse=True
        )[:k]
        # Restore original order for readability
        top_k_indices.sort()

        selected = [sentences[i] for i in top_k_indices]
        compressed = ". ".join(selected)
        if not compressed.endswith("."):
            compressed += "."

        original_count = len(sentences)
        kept_count = len(selected)
        marker = format_summary_marker(
            adapter_name="BM25SentenceSelector",
            original_count=original_count,
            kept_count=kept_count,
            kept_types="relevance-ranked",
        )
        compressed_content = compressed + "\n" + marker

        return dataclasses.replace(envelope, content=compressed_content)

    def _score_sentences(
        self, sentences: list[str], query: str
    ) -> list[float]:
        """Score sentences using BM25 or fallback to term frequency."""
        try:
            return self._score_bm25(sentences, query)
        except (ImportError, Exception):
            return self._score_frequency(sentences, query)

    @staticmethod
    def _score_bm25(sentences: list[str], query: str) -> list[float]:
        """Score using rank_bm25 library."""
        from rank_bm25 import BM25Okapi

        tokenized = [s.lower().split() for s in sentences]
        bm25 = BM25Okapi(tokenized)
        query_tokens = query.lower().split()
        if not query_tokens:
            # No query — use position-based scoring (favour early sentences)
            return [1.0 / (i + 1) for i in range(len(sentences))]
        scores = bm25.get_scores(query_tokens)
        return [float(s) for s in scores]

    @staticmethod
    def _score_frequency(sentences: list[str], query: str) -> list[float]:
        """Fallback: score by query term frequency + position bias."""
        query_terms = set(query.lower().split()) if query else set()
        scores: list[float] = []
        for i, sentence in enumerate(sentences):
            words = set(sentence.lower().split())
            # Term overlap score
            if query_terms:
                overlap = len(words & query_terms)
                term_score = overlap / len(query_terms)
            else:
                term_score = 0.0
            # Position bias: earlier sentences get a small bonus
            position_score = 1.0 / (i + 1)
            scores.append(term_score + 0.1 * position_score)
        return scores
