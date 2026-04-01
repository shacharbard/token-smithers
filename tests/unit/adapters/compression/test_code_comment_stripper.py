"""Tests for CodeCommentStripper adapter.

Inherits CompressionStrategyContract for protocol compliance.
CodeCommentStripper is a lossy adapter: off by default, opt-in via enabled=True.
"""

from __future__ import annotations

import pytest

from tests.unit.adapters.conftest import CompressionStrategyContract
from token_sieve.adapters.compression.code_comment_stripper import CodeCommentStripper
from token_sieve.domain.model import ContentType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def strategy():
    """Provide enabled CodeCommentStripper for contract tests."""
    return CodeCommentStripper(enabled=True)


@pytest.fixture()
def disabled_strategy():
    """CodeCommentStripper with default (disabled) state."""
    return CodeCommentStripper()


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestCodeCommentStripperContract(CompressionStrategyContract):
    """CodeCommentStripper must satisfy the CompressionStrategy contract."""


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

PYTHON_WITH_COMMENTS = '''\
# This is a file-level comment
# explaining the module purpose

import os
import sys

# Configuration constants
MAX_RETRIES = 3
TIMEOUT = 30  # seconds

def process_data(items):
    # Loop through each item
    for item in items:
        result = transform(item)
        yield result  # yield transformed items

class DataProcessor:
    """A class that processes data.

    This docstring should be removed.
    It spans multiple lines.
    """

    def __init__(self, config):
        self.config = config

    def run(self):
        """Run the processor."""
        return self.config.get("key")
'''

PYTHON_CODE_ONLY = '''\
import os
import sys

MAX_RETRIES = 3
TIMEOUT = 30

def process_data(items):
    for item in items:
        result = transform(item)
        yield result

class DataProcessor:
    def __init__(self, config):
        self.config = config

    def run(self):
        return self.config.get("key")
'''

JS_WITH_COMMENTS = '''\
// Import dependencies
import { useState } from 'react';

/* Configuration
   for the app */
const MAX_RETRIES = 3;

// Helper function
function processData(items) {
    // Transform each item
    return items.map(item => transform(item)); // inline
}

/**
 * A class for processing data.
 * Has multiple methods.
 */
class DataProcessor {
    constructor(config) {
        this.config = config;
    }
}
'''

NON_CODE_CONTENT = """\
This is just a regular text document.
It has no code patterns at all.
Just paragraphs of plain text.
Nothing resembling programming.
No functions, no classes, no imports.
""".strip()

SHORT_CODE = """\
# Just a comment
x = 1
""".strip()


# ---------------------------------------------------------------------------
# Specific tests
# ---------------------------------------------------------------------------


class TestCodeCommentStripperSpecific:
    """CodeCommentStripper-specific behavioral tests."""

    def test_python_full_line_comments_removed(self, strategy, make_envelope):
        """Full-line Python # comments are removed."""
        envelope = make_envelope(content=PYTHON_WITH_COMMENTS, content_type=ContentType.CODE)
        result = strategy.compress(envelope)
        # Full-line comments should be gone
        for line in result.content.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("[token-sieve:"):
                assert not stripped.startswith("#"), f"Full-line comment not stripped: {stripped}"

    def test_python_inline_comments_preserved(self, strategy, make_envelope):
        """Inline comments on code lines are preserved (safer default)."""
        envelope = make_envelope(content=PYTHON_WITH_COMMENTS, content_type=ContentType.CODE)
        result = strategy.compress(envelope)
        # Lines with code + inline comment should still have the code part
        assert "TIMEOUT = 30" in result.content

    def test_python_docstrings_removed(self, strategy, make_envelope):
        """Python triple-quote docstrings are removed."""
        envelope = make_envelope(content=PYTHON_WITH_COMMENTS, content_type=ContentType.CODE)
        result = strategy.compress(envelope)
        assert '"""A class that processes data.' not in result.content
        assert "This docstring should be removed." not in result.content

    def test_js_single_line_comments_removed(self, strategy, make_envelope):
        """JS/TS // full-line comments are removed."""
        envelope = make_envelope(content=JS_WITH_COMMENTS, content_type=ContentType.CODE)
        result = strategy.compress(envelope)
        for line in result.content.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("[token-sieve:"):
                assert not stripped.startswith("//"), f"JS comment not stripped: {stripped}"

    def test_js_block_comments_removed(self, strategy, make_envelope):
        """JS /* */ block comments are removed."""
        envelope = make_envelope(content=JS_WITH_COMMENTS, content_type=ContentType.CODE)
        result = strategy.compress(envelope)
        assert "/* Configuration" not in result.content
        assert "/**" not in result.content
        assert "* A class for processing data." not in result.content

    def test_code_only_content_unchanged(self, strategy, make_envelope):
        """Code without comments is returned mostly unchanged."""
        envelope = make_envelope(content=PYTHON_CODE_ONLY, content_type=ContentType.CODE)
        result = strategy.compress(envelope)
        # All code lines should still be present
        assert "import os" in result.content
        assert "def process_data" in result.content
        assert "class DataProcessor" in result.content

    def test_summary_marker_appended(self, strategy, make_envelope):
        """Summary marker is appended showing lines removed."""
        envelope = make_envelope(content=PYTHON_WITH_COMMENTS, content_type=ContentType.CODE)
        result = strategy.compress(envelope)
        assert "[token-sieve:" in result.content
        assert "CodeCommentStripper" in result.content

    def test_non_code_not_handled(self, strategy, make_envelope):
        """Non-code content -> can_handle returns False."""
        envelope = make_envelope(content=NON_CODE_CONTENT)
        assert strategy.can_handle(envelope) is False

    def test_disabled_by_default(self, make_envelope):
        """Default CodeCommentStripper has enabled=False -> can_handle False."""
        s = CodeCommentStripper()
        envelope = make_envelope(content=PYTHON_WITH_COMMENTS, content_type=ContentType.CODE)
        assert s.can_handle(envelope) is False

    def test_enabled_false_explicit(self, disabled_strategy, make_envelope):
        """enabled=False -> always returns can_handle False."""
        envelope = make_envelope(content=PYTHON_WITH_COMMENTS, content_type=ContentType.CODE)
        assert disabled_strategy.can_handle(envelope) is False

    def test_preserves_content_type(self, strategy, make_envelope):
        """Content type is preserved after compression."""
        envelope = make_envelope(content=PYTHON_WITH_COMMENTS, content_type=ContentType.CODE)
        result = strategy.compress(envelope)
        assert result.content_type == ContentType.CODE

    def test_can_handle_true_for_code_content_type(self, strategy, make_envelope):
        """ContentType.CODE -> can_handle True."""
        envelope = make_envelope(content=PYTHON_WITH_COMMENTS, content_type=ContentType.CODE)
        assert strategy.can_handle(envelope) is True

    def test_can_handle_true_for_code_patterns_in_text(self, strategy, make_envelope):
        """Text with code patterns (def/class/import) -> can_handle True."""
        envelope = make_envelope(content=PYTHON_WITH_COMMENTS, content_type=ContentType.TEXT)
        assert strategy.can_handle(envelope) is True

    def test_savings_on_commented_code(self, strategy, make_envelope):
        """Commented code achieves measurable savings."""
        envelope = make_envelope(content=PYTHON_WITH_COMMENTS, content_type=ContentType.CODE)
        result = strategy.compress(envelope)
        assert len(result.content) < len(envelope.content)
