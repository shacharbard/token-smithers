"""Tests for SentenceScorer adapter (sumy-based prose extraction)."""

from __future__ import annotations

import pytest

from token_sieve.adapters.compression.sentence_scorer import SentenceScorer
from token_sieve.domain.model import ContentEnvelope, ContentType

from tests.unit.adapters.conftest import CompressionStrategyContract


# ---------------------------------------------------------------------------
# Prose fixture helpers
# ---------------------------------------------------------------------------
_PROSE_CONTENT = (
    "Machine learning is a subset of artificial intelligence. "
    "It allows computers to learn from data without being explicitly programmed. "
    "Deep learning uses neural networks with many layers. "
    "Natural language processing handles text and speech. "
    "Computer vision deals with image recognition. "
    "Reinforcement learning trains agents through rewards. "
    "Transfer learning reuses models trained on one task for another. "
    "Supervised learning uses labeled data for training. "
    "Unsupervised learning finds patterns in unlabeled data. "
    "Semi-supervised learning combines both approaches effectively. "
    "The field has grown rapidly in recent years. "
    "Many applications exist in healthcare and finance."
)

_SHORT_PROSE = "This is short. Only two sentences."

_NON_PROSE = "key1=value1\nkey2=value2\nkey3=value3"


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------
class TestSentenceScorerContract(CompressionStrategyContract):
    """SentenceScorer must satisfy the CompressionStrategy contract."""

    @pytest.fixture()
    def strategy(self):
        return SentenceScorer()


# ---------------------------------------------------------------------------
# Specific tests
# ---------------------------------------------------------------------------
class TestSentenceScorerSpecific:
    """SentenceScorer-specific behavioral tests."""

    def test_can_handle_true_for_prose(self):
        """Prose content with 100+ words and 3+ sentences triggers can_handle."""
        envelope = ContentEnvelope(content=_PROSE_CONTENT, content_type=ContentType.TEXT)
        scorer = SentenceScorer()
        assert scorer.can_handle(envelope) is True

    def test_can_handle_false_for_non_prose(self):
        """Non-prose content (key-value pairs, no sentences) returns False."""
        envelope = ContentEnvelope(content=_NON_PROSE, content_type=ContentType.TEXT)
        scorer = SentenceScorer()
        assert scorer.can_handle(envelope) is False

    def test_can_handle_false_for_short_prose(self):
        """Short prose with fewer than 5 sentences returns False."""
        envelope = ContentEnvelope(content=_SHORT_PROSE, content_type=ContentType.TEXT)
        scorer = SentenceScorer()
        assert scorer.can_handle(envelope) is False

    def test_compress_extracts_top_k_sentences(self):
        """compress() extracts top-K sentences from prose."""
        envelope = ContentEnvelope(content=_PROSE_CONTENT, content_type=ContentType.TEXT)
        scorer = SentenceScorer(sentence_count=5)
        result = scorer.compress(envelope)
        # Result should be shorter than the original
        assert len(result.content) < len(_PROSE_CONTENT)
        # Result should contain some sentences from original
        assert result.content  # non-empty

    def test_compress_configurable_sentence_count(self):
        """Configuring sentence_count changes output length."""
        envelope = ContentEnvelope(content=_PROSE_CONTENT, content_type=ContentType.TEXT)
        scorer_3 = SentenceScorer(sentence_count=3)
        scorer_7 = SentenceScorer(sentence_count=7)
        result_3 = scorer_3.compress(envelope)
        result_7 = scorer_7.compress(envelope)
        # More sentences should produce longer output
        assert len(result_7.content) > len(result_3.content)

    def test_compress_preserves_content_type(self):
        """compress() preserves the envelope's content_type."""
        envelope = ContentEnvelope(content=_PROSE_CONTENT, content_type=ContentType.TEXT)
        scorer = SentenceScorer()
        result = scorer.compress(envelope)
        assert result.content_type == ContentType.TEXT

    def test_short_prose_passthrough(self):
        """Content below sentence threshold is not handled (can_handle False)."""
        few_sentences = (
            "First sentence here. Second sentence here. Third sentence here."
        )
        envelope = ContentEnvelope(content=few_sentences, content_type=ContentType.TEXT)
        scorer = SentenceScorer()
        assert scorer.can_handle(envelope) is False

    def test_sumy_not_installed_graceful_fallback(self, monkeypatch):
        """If sumy import fails, compress() returns content unchanged."""
        import token_sieve.adapters.compression.sentence_scorer as mod

        # Simulate sumy being unavailable
        monkeypatch.setattr(mod, "_SUMY_AVAILABLE", False)
        envelope = ContentEnvelope(content=_PROSE_CONTENT, content_type=ContentType.TEXT)
        scorer = SentenceScorer()
        result = scorer.compress(envelope)
        assert result.content == _PROSE_CONTENT

    def test_default_sentence_count(self):
        """Default sentence_count is 5."""
        scorer = SentenceScorer()
        assert scorer.sentence_count == 5

    def test_algorithm_parameter(self):
        """SentenceScorer accepts algorithm parameter."""
        scorer = SentenceScorer(algorithm="textrank")
        assert scorer.algorithm == "textrank"

    def test_compress_result_is_subset_of_original(self):
        """Extracted sentences should be substrings of the original."""
        envelope = ContentEnvelope(content=_PROSE_CONTENT, content_type=ContentType.TEXT)
        scorer = SentenceScorer(sentence_count=3)
        result = scorer.compress(envelope)
        # Each sentence in result should appear in original
        for sentence in result.content.split(". "):
            sentence = sentence.strip().rstrip(".")
            if sentence:
                assert sentence in _PROSE_CONTENT
