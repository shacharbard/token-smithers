"""Tests for ProgressiveDisclosureStrategy.

RED phase: contract tests + specific behavioral tests.
"""

from __future__ import annotations

import os

import pytest

from token_sieve.domain.model import ContentEnvelope, ContentType

from tests.unit.adapters.conftest import CompressionStrategyContract


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# Large content (~250 tokens at 4 chars/token = ~1000 chars)
_LARGE_CONTENT = (
    "The quick brown fox jumps over the lazy dog. " * 100
)

_SMALL_CONTENT = "This is short content."

# Prose-like large content with distinct sentences for summary extraction
_PROSE_LARGE = (
    "Machine learning has transformed how we process data. "
    "Neural networks can identify complex patterns in images. "
    "Natural language processing enables machines to understand text. "
    "Deep learning models require large amounts of training data. "
    "Reinforcement learning teaches agents through trial and error. "
    "Transfer learning allows models to reuse knowledge. "
    "Generative models can create new content from learned distributions. "
    "Attention mechanisms help models focus on relevant parts of input. "
    "Transformer architectures have revolutionized sequence modeling. "
    "Gradient descent optimizes model parameters iteratively. "
) * 20  # ~2000 words, well above threshold


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestProgressiveDisclosureContract(CompressionStrategyContract):
    """ProgressiveDisclosureStrategy must satisfy the CompressionStrategy contract."""

    @pytest.fixture()
    def strategy(self):
        from token_sieve.adapters.compression.progressive_disclosure import (
            ProgressiveDisclosureStrategy,
        )

        # Low threshold so contract tests trigger can_handle
        return ProgressiveDisclosureStrategy(threshold_tokens=1)


# ---------------------------------------------------------------------------
# Specific behavioral tests
# ---------------------------------------------------------------------------


class TestProgressiveDisclosureSpecific:
    """ProgressiveDisclosureStrategy-specific behavioral tests."""

    def test_can_handle_true_large_content(self):
        """Content above threshold_tokens triggers can_handle."""
        from token_sieve.adapters.compression.progressive_disclosure import (
            ProgressiveDisclosureStrategy,
        )

        envelope = ContentEnvelope(
            content=_LARGE_CONTENT, content_type=ContentType.TEXT
        )
        strategy = ProgressiveDisclosureStrategy(threshold_tokens=100)
        assert strategy.can_handle(envelope) is True

    def test_can_handle_false_small_content(self):
        """Content below threshold_tokens returns False."""
        from token_sieve.adapters.compression.progressive_disclosure import (
            ProgressiveDisclosureStrategy,
        )

        envelope = ContentEnvelope(
            content=_SMALL_CONTENT, content_type=ContentType.TEXT
        )
        strategy = ProgressiveDisclosureStrategy(threshold_tokens=10000)
        assert strategy.can_handle(envelope) is False

    def test_compress_returns_structured_envelope(self):
        """Large content returns summary + file pointer."""
        from token_sieve.adapters.compression.progressive_disclosure import (
            ProgressiveDisclosureStrategy,
        )

        envelope = ContentEnvelope(
            content=_LARGE_CONTENT, content_type=ContentType.TEXT
        )
        strategy = ProgressiveDisclosureStrategy(threshold_tokens=100)
        result = strategy.compress(envelope)

        assert "[token-sieve/progressive]" in result.content
        assert "Summary:" in result.content
        assert "Full result:" in result.content
        assert "bytes" in result.content
        assert "read_file" in result.content

    def test_compress_file_exists(self):
        """Temp file created by compress() actually exists."""
        from token_sieve.adapters.compression.progressive_disclosure import (
            ProgressiveDisclosureStrategy,
        )

        envelope = ContentEnvelope(
            content=_LARGE_CONTENT, content_type=ContentType.TEXT
        )
        strategy = ProgressiveDisclosureStrategy(threshold_tokens=100)
        result = strategy.compress(envelope)

        # Extract file path
        for line in result.content.splitlines():
            if "Full result:" in line:
                # Format: Full result: /path/to/file (NNNN bytes)
                path = line.split("Full result:")[1].strip().split(" (")[0]
                assert os.path.exists(path)
                # Verify file contains original content
                with open(path) as f:
                    assert f.read() == _LARGE_CONTENT
                os.unlink(path)
                break
        else:
            pytest.fail("No 'Full result:' line found in output")

    def test_compress_summary_is_head_truncation_fallback(self):
        """Without SentenceScorer, summary falls back to head truncation."""
        from token_sieve.adapters.compression.progressive_disclosure import (
            ProgressiveDisclosureStrategy,
        )

        envelope = ContentEnvelope(
            content=_LARGE_CONTENT, content_type=ContentType.TEXT
        )
        strategy = ProgressiveDisclosureStrategy(
            threshold_tokens=100, summary_tokens=50
        )
        result = strategy.compress(envelope)

        # Summary should be shorter than original
        summary_line = ""
        for line in result.content.splitlines():
            if line.startswith("Summary:"):
                summary_line = line
                break
        assert summary_line
        summary_text = summary_line.split("Summary:")[1].strip()
        assert len(summary_text) < len(_LARGE_CONTENT)
        assert len(summary_text) > 0

        # Cleanup temp file
        for line in result.content.splitlines():
            if "Full result:" in line:
                path = line.split("Full result:")[1].strip().split(" (")[0]
                if os.path.exists(path):
                    os.unlink(path)

    def test_compress_preserves_content_type(self):
        """compress() preserves the envelope's content_type."""
        from token_sieve.adapters.compression.progressive_disclosure import (
            ProgressiveDisclosureStrategy,
        )

        envelope = ContentEnvelope(
            content=_LARGE_CONTENT, content_type=ContentType.TEXT
        )
        strategy = ProgressiveDisclosureStrategy(threshold_tokens=100)
        result = strategy.compress(envelope)
        assert result.content_type == ContentType.TEXT

        # Cleanup
        for line in result.content.splitlines():
            if "Full result:" in line:
                path = line.split("Full result:")[1].strip().split(" (")[0]
                if os.path.exists(path):
                    os.unlink(path)

    def test_default_threshold(self):
        """Default threshold_tokens is 10000."""
        from token_sieve.adapters.compression.progressive_disclosure import (
            ProgressiveDisclosureStrategy,
        )

        strategy = ProgressiveDisclosureStrategy()
        assert strategy.threshold_tokens == 10000

    def test_configurable_summary_tokens(self):
        """summary_tokens is configurable."""
        from token_sieve.adapters.compression.progressive_disclosure import (
            ProgressiveDisclosureStrategy,
        )

        strategy = ProgressiveDisclosureStrategy(summary_tokens=300)
        assert strategy.summary_tokens == 300

    def test_cleanup_removes_files(self):
        """cleanup() removes created temp files."""
        from token_sieve.adapters.compression.progressive_disclosure import (
            ProgressiveDisclosureStrategy,
        )

        envelope = ContentEnvelope(
            content=_LARGE_CONTENT, content_type=ContentType.TEXT
        )
        strategy = ProgressiveDisclosureStrategy(threshold_tokens=100)
        result = strategy.compress(envelope)

        # Extract path
        path = None
        for line in result.content.splitlines():
            if "Full result:" in line:
                path = line.split("Full result:")[1].strip().split(" (")[0]
                break

        assert path and os.path.exists(path)
        strategy.cleanup()
        assert not os.path.exists(path)
