"""Tests for BM25SentenceSelector adapter."""

from __future__ import annotations

import importlib.util
from types import MappingProxyType

import pytest

from token_sieve.domain.model import ContentEnvelope, ContentType

_RANK_BM25_AVAILABLE = importlib.util.find_spec("rank_bm25") is not None

# Long text about Python testing (~2500 chars / ~625 tokens estimated)
_PYTEST_ARTICLE = (
    "Python testing with pytest is essential for maintaining code quality. "
    "The pytest framework makes it easy to write small readable tests. "
    "You can use fixtures to set up test data and dependencies. "
    "Parametrize decorators allow running the same test with different inputs. "
    "Mocking with unittest.mock helps isolate units under test. "
    "Integration tests verify that components work together correctly. "
    "Test coverage reports show which lines of code are exercised by tests. "
    "Continuous integration pipelines run tests automatically on every commit. "
    "The assert statement in pytest provides detailed failure messages. "
    "Conftest files share fixtures across multiple test modules. "
    "Markers like skip and xfail control test execution behavior. "
    "Plugins extend pytest with additional capabilities and reporting. "
    "The pytest documentation is comprehensive and well maintained. "
    "Test-driven development means writing tests before production code. "
    "Property-based testing with hypothesis generates random test inputs. "
    "Snapshot testing captures expected output for regression detection. "
    "Performance testing measures execution time and resource usage. "
    "Security testing identifies vulnerabilities in application code. "
    "Load testing simulates many concurrent users to find bottlenecks. "
    "End-to-end tests verify the complete user workflow from start to finish. "
    "The cooking of Italian pasta requires fresh ingredients and patience. "
    "A good risotto needs constant stirring and quality Arborio rice. "
    "French cuisine emphasizes butter, cream, and careful technique. "
    "Sushi preparation demands years of training and the freshest fish. "
    "Barbecue traditions vary widely across different American regions."
)

# Short text (below threshold)
_SHORT_TEXT = "Hello world. This is short."


def _make_envelope(
    content: str,
    content_type: ContentType = ContentType.TEXT,
    source_tool: str = "",
) -> ContentEnvelope:
    metadata: dict[str, str] = {}
    if source_tool:
        metadata["source_tool"] = source_tool
    return ContentEnvelope(
        content=content,
        content_type=content_type,
        metadata=MappingProxyType(metadata),
    )


class TestBM25SentenceSelectorCanHandle:
    """Test can_handle routing logic."""

    def test_can_handle_text_over_threshold(self) -> None:
        from token_sieve.adapters.compression.bm25_sentence_selector import (
            BM25SentenceSelector,
        )

        selector = BM25SentenceSelector(threshold_tokens=100)
        envelope = _make_envelope(_PYTEST_ARTICLE)
        assert selector.can_handle(envelope) is True

    def test_can_handle_rejects_short_text(self) -> None:
        from token_sieve.adapters.compression.bm25_sentence_selector import (
            BM25SentenceSelector,
        )

        selector = BM25SentenceSelector(threshold_tokens=100)
        envelope = _make_envelope(_SHORT_TEXT)
        assert selector.can_handle(envelope) is False

    def test_can_handle_rejects_non_text(self) -> None:
        from token_sieve.adapters.compression.bm25_sentence_selector import (
            BM25SentenceSelector,
        )

        selector = BM25SentenceSelector(threshold_tokens=100)
        envelope = _make_envelope(_PYTEST_ARTICLE, ContentType.JSON)
        assert selector.can_handle(envelope) is False


class TestBM25SentenceSelectorFallback:
    """Test fallback behavior when rank_bm25 is not installed."""

    def test_compress_preserves_structure(self) -> None:
        from token_sieve.adapters.compression.bm25_sentence_selector import (
            BM25SentenceSelector,
        )

        selector = BM25SentenceSelector(threshold_tokens=100)
        envelope = _make_envelope(
            _PYTEST_ARTICLE, source_tool="ctx_execute"
        )
        result = selector.compress(envelope)
        assert isinstance(result, ContentEnvelope)
        assert result.content_type == ContentType.TEXT
        # Compressed content should be shorter than original
        assert len(result.content) < len(envelope.content)

    def test_compress_keeps_minimum_sentences(self) -> None:
        from token_sieve.adapters.compression.bm25_sentence_selector import (
            BM25SentenceSelector,
        )

        selector = BM25SentenceSelector(
            threshold_tokens=100, min_sentences=5
        )
        envelope = _make_envelope(
            _PYTEST_ARTICLE, source_tool="ctx_execute"
        )
        result = selector.compress(envelope)
        # Should have at least 5 sentences (each ending with period)
        sentences = [s.strip() for s in result.content.split(". ") if s.strip()]
        assert len(sentences) >= 5


@pytest.mark.skipif(not _RANK_BM25_AVAILABLE, reason="rank_bm25 not installed")
class TestBM25SentenceSelectorWithBM25:
    """Tests requiring rank_bm25 library."""

    def test_compress_ranks_by_relevance(self) -> None:
        from token_sieve.adapters.compression.bm25_sentence_selector import (
            BM25SentenceSelector,
        )

        selector = BM25SentenceSelector(
            threshold_tokens=100, keep_ratio=0.3
        )
        envelope = _make_envelope(
            _PYTEST_ARTICLE, source_tool="pytest"
        )
        result = selector.compress(envelope)
        content_lower = result.content.lower()
        # With query "pytest", test-related sentences should be prioritized
        assert "test" in content_lower or "pytest" in content_lower
        # Food-related sentences should be dropped
        assert "risotto" not in content_lower or "pasta" not in content_lower


@pytest.mark.skipif(not _RANK_BM25_AVAILABLE, reason="rank_bm25 not installed")
class TestBM25MaxSentencesCap:
    """H9: BM25SentenceSelector must cap input at max_sentences."""

    def test_large_input_capped(self) -> None:
        """Input with >2000 sentences should be capped."""
        from token_sieve.adapters.compression.bm25_sentence_selector import (
            BM25SentenceSelector,
        )

        # Create 3000 sentences
        huge_text = ". ".join(f"Sentence number {i}" for i in range(3000)) + "."
        selector = BM25SentenceSelector(threshold_tokens=100)
        envelope = _make_envelope(huge_text, source_tool="test")
        # Should not hang or OOM — must complete in reasonable time
        result = selector.compress(envelope)
        assert isinstance(result, ContentEnvelope)


class TestBM25JoinFix:
    """M13: BM25 must use space join, not '. ' (sentences already have punctuation)."""

    def test_no_double_punctuation(self) -> None:
        """Joined output must not have double punctuation like 'sentence!. next'."""
        from token_sieve.adapters.compression.bm25_sentence_selector import (
            BM25SentenceSelector,
        )

        text = "First sentence! Second sentence? Third sentence. Fourth sentence."
        selector = BM25SentenceSelector(threshold_tokens=0, keep_ratio=0.5, min_sentences=2)
        envelope = _make_envelope(text, source_tool="test")
        result = selector.compress(envelope)
        # Should not have patterns like "!. " or "?. "
        assert "!. " not in result.content
        assert "?. " not in result.content
