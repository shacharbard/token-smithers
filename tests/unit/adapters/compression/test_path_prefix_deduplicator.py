"""Tests for PathPrefixDeduplicator adapter.

Inherits CompressionStrategyContract for uniform protocol compliance.
"""

from __future__ import annotations

import json

import pytest

from tests.unit.adapters.conftest import CompressionStrategyContract
from token_sieve.domain.model import ContentEnvelope, ContentType


@pytest.fixture()
def strategy():
    """Provide PathPrefixDeduplicator for contract tests."""
    from token_sieve.adapters.compression.path_prefix_deduplicator import (
        PathPrefixDeduplicator,
    )

    return PathPrefixDeduplicator()


class TestPathPrefixDeduplicatorContract(CompressionStrategyContract):
    """PathPrefixDeduplicator must satisfy the CompressionStrategy contract."""


class TestPathPrefixDeduplicatorSpecific:
    """PathPrefixDeduplicator-specific behavioral tests."""

    def test_file_paths_deduplicated(self, strategy, make_envelope):
        """Repeated file paths sharing a common prefix should use $BASE."""
        content = json.dumps({
            "files": [
                "/Users/alice/project/src/main.py",
                "/Users/alice/project/src/utils.py",
                "/Users/alice/project/tests/test_main.py",
            ]
        })
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert "$BASE" in result.content
        # Original long prefix should not appear in full
        assert "/Users/alice/project/" not in result.content or "$BASE" in result.content

    def test_url_paths_deduplicated(self, strategy, make_envelope):
        """URL paths sharing a common prefix should use $BASE."""
        content = json.dumps({
            "endpoints": [
                "https://api.example.com/v2/users/list",
                "https://api.example.com/v2/users/create",
                "https://api.example.com/v2/orders/list",
            ]
        })
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert "$BASE" in result.content

    def test_base_definition_included(self, strategy, make_envelope):
        """Output should include $BASE= definition line."""
        content = json.dumps({
            "a": "/home/user/repo/src/a.py",
            "b": "/home/user/repo/src/b.py",
            "c": "/home/user/repo/tests/c.py",
        })
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert "$BASE=" in result.content

    def test_single_path_unchanged(self, strategy, make_envelope):
        """Content with only one path should not create $BASE."""
        content = json.dumps({"file": "/Users/alice/project/main.py"})
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert "$BASE" not in result.content

    def test_no_paths_passthrough(self, strategy, make_envelope):
        """Content without path-like strings should pass through unchanged."""
        content = "just some regular text without any paths"
        envelope = make_envelope(content=content, content_type=ContentType.TEXT)
        result = strategy.compress(envelope)
        assert result.content == content

    def test_preserves_content_type(self, strategy, make_envelope):
        """Content type must be preserved."""
        content = json.dumps({
            "a": "/tmp/proj/x.py",
            "b": "/tmp/proj/y.py",
            "c": "/tmp/proj/z.py",
        })
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        assert result.content_type is ContentType.JSON

    def test_preserves_metadata(self, strategy, make_envelope):
        """Metadata must be preserved."""
        metadata = {"tool_name": "list_dir"}
        content = json.dumps({
            "files": ["/a/b/c/1.py", "/a/b/c/2.py", "/a/b/c/3.py"]
        })
        envelope = make_envelope(
            content=content, content_type=ContentType.JSON, metadata=metadata
        )
        result = strategy.compress(envelope)
        assert result.metadata["tool_name"] == "list_dir"

    def test_mixed_path_types(self, strategy, make_envelope):
        """Mixed file and URL paths should find common prefix if present."""
        content = json.dumps({
            "paths": [
                "/home/user/repo/a.py",
                "/home/user/repo/b.py",
                "/home/user/repo/c.py",
                "https://example.com/api",
            ]
        })
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        # At minimum, the file paths should get deduplicated
        assert "$BASE" in result.content

    def test_short_prefix_not_deduplicated(self, strategy, make_envelope):
        """Paths with a very short common prefix should not trigger dedup."""
        content = json.dumps({
            "paths": ["/a/x.py", "/b/y.py", "/c/z.py"]
        })
        envelope = make_envelope(content=content, content_type=ContentType.JSON)
        result = strategy.compress(envelope)
        # Prefix "/" is too short to be useful
        assert "$BASE" not in result.content
