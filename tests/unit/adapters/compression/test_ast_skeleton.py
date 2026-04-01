"""Tests for ASTSkeletonExtractor.

RED phase: contract tests + specific behavioral tests.
"""

from __future__ import annotations

import pytest

from token_sieve.domain.model import ContentEnvelope, ContentType

from tests.unit.adapters.conftest import CompressionStrategyContract


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_PYTHON_MULTI_FUNC = '''\
import os
import sys


def calculate_total(items):
    """Sum all items in the list."""
    total = 0
    for item in items:
        total += item
    return total


def format_output(value, prefix="Result"):
    """Format a value with a prefix string."""
    formatted = f"{prefix}: {value}"
    print(formatted)
    return formatted


def validate_input(data):
    """Check that input data is valid."""
    if not isinstance(data, dict):
        raise TypeError("Expected dict")
    if "name" not in data:
        raise ValueError("Missing name")
    return True
'''

_PYTHON_CLASS = '''\
class Calculator:
    """A simple calculator class."""

    def __init__(self, precision=2):
        """Initialize with precision."""
        self.precision = precision
        self._history = []

    def add(self, a, b):
        """Add two numbers."""
        result = round(a + b, self.precision)
        self._history.append(result)
        return result

    def subtract(self, a, b):
        """Subtract b from a."""
        result = round(a - b, self.precision)
        self._history.append(result)
        return result

    def get_history(self):
        """Return calculation history."""
        return list(self._history)
'''

_NON_PYTHON = """\
This is just plain text that has no Python code in it.
It talks about various things but doesn't define functions or classes.
There are no import statements here either.
"""

_MALFORMED_PYTHON = '''\
def broken_function(
    # This is syntactically invalid Python
    if True
        return "broken"
'''

_PYTHON_WITH_DECORATORS = '''\
import functools


def my_decorator(func):
    """A custom decorator."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        print("Before")
        result = func(*args, **kwargs)
        print("After")
        return result
    return wrapper


@my_decorator
def decorated_function(x, y):
    """A decorated function."""
    return x + y
'''


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestASTSkeletonContract(CompressionStrategyContract):
    """ASTSkeletonExtractor must satisfy the CompressionStrategy contract."""

    @pytest.fixture()
    def strategy(self):
        from token_sieve.adapters.compression.ast_skeleton import (
            ASTSkeletonExtractor,
        )

        return ASTSkeletonExtractor()


# ---------------------------------------------------------------------------
# Specific behavioral tests
# ---------------------------------------------------------------------------


class TestASTSkeletonSpecific:
    """ASTSkeletonExtractor-specific behavioral tests."""

    def test_can_handle_true_for_python(self):
        """Python source with multiple defs triggers can_handle."""
        from token_sieve.adapters.compression.ast_skeleton import (
            ASTSkeletonExtractor,
        )

        envelope = ContentEnvelope(
            content=_PYTHON_MULTI_FUNC, content_type=ContentType.CODE
        )
        strategy = ASTSkeletonExtractor()
        assert strategy.can_handle(envelope) is True

    def test_can_handle_false_for_non_python(self):
        """Non-Python content returns False."""
        from token_sieve.adapters.compression.ast_skeleton import (
            ASTSkeletonExtractor,
        )

        envelope = ContentEnvelope(
            content=_NON_PYTHON, content_type=ContentType.TEXT
        )
        strategy = ASTSkeletonExtractor()
        assert strategy.can_handle(envelope) is False

    def test_compress_multi_function_skeleton(self):
        """Multi-function Python source returns signatures + docstrings."""
        from token_sieve.adapters.compression.ast_skeleton import (
            ASTSkeletonExtractor,
        )

        envelope = ContentEnvelope(
            content=_PYTHON_MULTI_FUNC, content_type=ContentType.CODE
        )
        strategy = ASTSkeletonExtractor()
        result = strategy.compress(envelope)

        # Should contain function signatures
        assert "def calculate_total(items):" in result.content
        assert "def format_output(value, prefix=" in result.content
        assert "def validate_input(data):" in result.content
        # Should contain docstrings
        assert "Sum all items" in result.content
        # Should NOT contain function bodies
        assert "total += item" not in result.content
        assert "print(formatted)" not in result.content
        # Should include marker
        assert "[token-sieve]" in result.content
        assert "skeleton shown" in result.content

    def test_compress_class_skeleton(self):
        """Class with methods returns class + method signatures."""
        from token_sieve.adapters.compression.ast_skeleton import (
            ASTSkeletonExtractor,
        )

        envelope = ContentEnvelope(
            content=_PYTHON_CLASS, content_type=ContentType.CODE
        )
        strategy = ASTSkeletonExtractor()
        result = strategy.compress(envelope)

        assert "class Calculator:" in result.content
        assert "def __init__(self, precision=2):" in result.content
        assert "def add(self, a, b):" in result.content
        # Should NOT contain method bodies
        assert "self._history.append" not in result.content

    def test_compress_syntax_error_fallback(self):
        """Malformed Python falls back to returning content unchanged."""
        from token_sieve.adapters.compression.ast_skeleton import (
            ASTSkeletonExtractor,
        )

        envelope = ContentEnvelope(
            content=_MALFORMED_PYTHON, content_type=ContentType.CODE
        )
        strategy = ASTSkeletonExtractor()
        # can_handle may be True (heuristic detects 'def')
        # but compress should gracefully return original
        result = strategy.compress(envelope)
        assert result.content == _MALFORMED_PYTHON

    def test_compress_result_shorter(self):
        """Skeleton should be shorter than the full source."""
        from token_sieve.adapters.compression.ast_skeleton import (
            ASTSkeletonExtractor,
        )

        envelope = ContentEnvelope(
            content=_PYTHON_MULTI_FUNC, content_type=ContentType.CODE
        )
        strategy = ASTSkeletonExtractor()
        result = strategy.compress(envelope)
        assert len(result.content) < len(envelope.content)

    def test_compress_preserves_content_type(self):
        """compress() preserves the envelope's content_type."""
        from token_sieve.adapters.compression.ast_skeleton import (
            ASTSkeletonExtractor,
        )

        envelope = ContentEnvelope(
            content=_PYTHON_MULTI_FUNC, content_type=ContentType.CODE
        )
        strategy = ASTSkeletonExtractor()
        result = strategy.compress(envelope)
        assert result.content_type == ContentType.CODE

    def test_compress_includes_line_count_marker(self):
        """Marker includes the original line count."""
        from token_sieve.adapters.compression.ast_skeleton import (
            ASTSkeletonExtractor,
        )

        envelope = ContentEnvelope(
            content=_PYTHON_MULTI_FUNC, content_type=ContentType.CODE
        )
        strategy = ASTSkeletonExtractor()
        result = strategy.compress(envelope)
        line_count = len(_PYTHON_MULTI_FUNC.strip().splitlines())
        assert str(line_count) in result.content
