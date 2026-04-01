"""Tests for FileRedirectStrategy adapter (oversized result file redirect)."""

from __future__ import annotations

import os
import tempfile

import pytest

from token_sieve.adapters.compression.file_redirect import FileRedirectStrategy
from token_sieve.domain.model import ContentEnvelope, ContentType

from tests.unit.adapters.conftest import CompressionStrategyContract


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------
class TestFileRedirectContract(CompressionStrategyContract):
    """FileRedirectStrategy must satisfy the CompressionStrategy contract."""

    @pytest.fixture()
    def strategy(self):
        # Low threshold so contract tests trigger can_handle
        return FileRedirectStrategy(threshold_tokens=1)


# ---------------------------------------------------------------------------
# Specific tests
# ---------------------------------------------------------------------------
class TestFileRedirectSpecific:
    """FileRedirectStrategy-specific behavioral tests."""

    def test_can_handle_true_above_threshold(self):
        """Content exceeding threshold_tokens triggers can_handle."""
        # ~100 tokens at 4 chars/token = ~400 chars
        content = "x " * 500  # ~1000 chars = ~250 tokens
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = FileRedirectStrategy(threshold_tokens=100)
        assert strategy.can_handle(envelope) is True

    def test_can_handle_false_below_threshold(self):
        """Content below threshold_tokens returns False."""
        envelope = ContentEnvelope(content="short content", content_type=ContentType.TEXT)
        strategy = FileRedirectStrategy(threshold_tokens=10000)
        assert strategy.can_handle(envelope) is False

    def test_compress_writes_temp_file(self):
        """compress() writes content to a temp file."""
        content = "x " * 500
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = FileRedirectStrategy(threshold_tokens=10)

        result = strategy.compress(envelope)

        # Result should be a pointer message
        assert "Result written to" in result.content
        assert "bytes" in result.content

    def test_compress_file_contains_original(self):
        """Temp file created by compress() contains the original content."""
        content = "this is the original content " * 50
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = FileRedirectStrategy(threshold_tokens=10)

        result = strategy.compress(envelope)

        # Extract file path from pointer message
        # Format: "Result written to {path}, {size} bytes"
        path = result.content.split("Result written to ")[1].split(",")[0]
        assert os.path.exists(path)
        with open(path) as f:
            file_content = f.read()
        assert file_content == content
        # Cleanup
        os.unlink(path)

    def test_compress_custom_output_dir(self, tmp_path):
        """Custom output_dir creates temp files in specified directory."""
        content = "data " * 200
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = FileRedirectStrategy(
            threshold_tokens=10, output_dir=str(tmp_path)
        )

        result = strategy.compress(envelope)
        path = result.content.split("Result written to ")[1].split(",")[0]
        assert path.startswith(str(tmp_path))
        assert os.path.exists(path)

    def test_compress_default_output_dir(self):
        """Default output_dir uses tempfile.gettempdir()."""
        content = "data " * 200
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = FileRedirectStrategy(threshold_tokens=10)

        result = strategy.compress(envelope)
        path = result.content.split("Result written to ")[1].split(",")[0]
        assert path.startswith(tempfile.gettempdir())
        os.unlink(path)

    def test_compress_preserves_content_type(self):
        """compress() preserves the envelope's content_type."""
        content = "data " * 200
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = FileRedirectStrategy(threshold_tokens=10)

        result = strategy.compress(envelope)
        assert result.content_type == ContentType.TEXT

    def test_default_threshold(self):
        """Default threshold_tokens is 10000."""
        strategy = FileRedirectStrategy()
        assert strategy.threshold_tokens == 10000

    def test_pointer_includes_byte_count(self):
        """Pointer message includes the byte count of written content."""
        content = "abc" * 100  # 300 bytes
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = FileRedirectStrategy(threshold_tokens=10)

        result = strategy.compress(envelope)
        assert "300 bytes" in result.content
        # Cleanup
        path = result.content.split("Result written to ")[1].split(",")[0]
        os.unlink(path)


class TestFileRedirectCleanup:
    """Finding 4 (P1): FileRedirectStrategy must track and clean up temp files."""

    def test_cleanup_removes_created_files(self):
        """cleanup() removes all temp files created by compress()."""
        content = "data " * 200
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = FileRedirectStrategy(threshold_tokens=10)

        result = strategy.compress(envelope)
        path = result.content.split("Result written to ")[1].split(",")[0]
        assert os.path.exists(path)

        strategy.cleanup()
        assert not os.path.exists(path)

    def test_cleanup_tracks_multiple_files(self):
        """cleanup() removes all files from multiple compress() calls."""
        strategy = FileRedirectStrategy(threshold_tokens=10)
        paths = []

        for i in range(3):
            content = f"data chunk {i} " * 200
            envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
            result = strategy.compress(envelope)
            path = result.content.split("Result written to ")[1].split(",")[0]
            paths.append(path)

        for p in paths:
            assert os.path.exists(p)

        strategy.cleanup()

        for p in paths:
            assert not os.path.exists(p)

    def test_cleanup_idempotent(self):
        """Calling cleanup() twice does not raise."""
        content = "data " * 200
        envelope = ContentEnvelope(content=content, content_type=ContentType.TEXT)
        strategy = FileRedirectStrategy(threshold_tokens=10)

        strategy.compress(envelope)
        strategy.cleanup()
        strategy.cleanup()  # Should not raise
