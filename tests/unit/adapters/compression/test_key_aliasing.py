"""Tests for KeyAliasingStrategy.

RED phase: contract tests + specific behavioral tests.
"""

from __future__ import annotations

import json

import pytest

from token_sieve.domain.model import ContentEnvelope, ContentType

from tests.unit.adapters.conftest import CompressionStrategyContract


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_JSON_REPEATED_LONG_KEYS = json.dumps(
    [
        {"functionDefinition": "foo", "parameterName": "x", "returnType": "int"}
        for _ in range(6)
    ]
)

_JSON_SHORT_KEYS = json.dumps(
    [{"id": i, "name": f"item{i}"} for i in range(10)]
)

_JSON_INFREQUENT_LONG_KEYS = json.dumps(
    {
        "functionDefinition": "foo",
        "parameterName": "bar",
        "somethingElse": "baz",
    }
)

_NON_JSON_CONTENT = "This is plain text, not JSON at all."

_YAML_LIKE_CONTENT = """name: test
functionDefinition: foo
functionDefinition: bar
functionDefinition: baz
functionDefinition: qux
functionDefinition: quux
functionDefinition: corge
"""


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestKeyAliasingContract(CompressionStrategyContract):
    """KeyAliasingStrategy must satisfy the CompressionStrategy contract."""

    @pytest.fixture()
    def strategy(self):
        from token_sieve.adapters.compression.key_aliasing import (
            KeyAliasingStrategy,
        )

        return KeyAliasingStrategy()


# ---------------------------------------------------------------------------
# Specific behavioral tests
# ---------------------------------------------------------------------------


class TestKeyAliasingSpecific:
    """KeyAliasingStrategy-specific behavioral tests."""

    def test_can_handle_true_repeated_long_keys(self):
        """JSON with 6 occurrences of 'functionDefinition' (>=10 chars, >=5 times)."""
        from token_sieve.adapters.compression.key_aliasing import (
            KeyAliasingStrategy,
        )

        envelope = ContentEnvelope(
            content=_JSON_REPEATED_LONG_KEYS, content_type=ContentType.JSON
        )
        strategy = KeyAliasingStrategy()
        assert strategy.can_handle(envelope) is True

    def test_can_handle_false_short_keys(self):
        """JSON with only short keys (< 10 chars) returns False."""
        from token_sieve.adapters.compression.key_aliasing import (
            KeyAliasingStrategy,
        )

        envelope = ContentEnvelope(
            content=_JSON_SHORT_KEYS, content_type=ContentType.JSON
        )
        strategy = KeyAliasingStrategy()
        assert strategy.can_handle(envelope) is False

    def test_can_handle_false_infrequent_long_keys(self):
        """JSON with long keys appearing < 5 times returns False."""
        from token_sieve.adapters.compression.key_aliasing import (
            KeyAliasingStrategy,
        )

        envelope = ContentEnvelope(
            content=_JSON_INFREQUENT_LONG_KEYS, content_type=ContentType.JSON
        )
        strategy = KeyAliasingStrategy()
        assert strategy.can_handle(envelope) is False

    def test_can_handle_false_non_json(self):
        """Non-JSON content returns False."""
        from token_sieve.adapters.compression.key_aliasing import (
            KeyAliasingStrategy,
        )

        envelope = ContentEnvelope(
            content=_NON_JSON_CONTENT, content_type=ContentType.TEXT
        )
        strategy = KeyAliasingStrategy()
        assert strategy.can_handle(envelope) is False

    def test_compress_aliases_repeated_keys(self):
        """Repeated long keys are replaced with short aliases."""
        from token_sieve.adapters.compression.key_aliasing import (
            KeyAliasingStrategy,
        )

        envelope = ContentEnvelope(
            content=_JSON_REPEATED_LONG_KEYS, content_type=ContentType.JSON
        )
        strategy = KeyAliasingStrategy()
        result = strategy.compress(envelope)
        # Should contain alias header
        assert "# aliases:" in result.content
        # Should contain short alias like k0
        assert "k0" in result.content
        # Original long key should NOT appear in the body (only in header)
        lines = result.content.split("\n")
        header_line = lines[0]
        body = "\n".join(lines[1:])
        assert "functionDefinition" in header_line  # in alias declaration
        assert "functionDefinition" not in body  # replaced in body

    def test_compress_alias_header_parseable(self):
        """Alias header follows the format '# aliases: k0=originalKey, ...'."""
        from token_sieve.adapters.compression.key_aliasing import (
            KeyAliasingStrategy,
        )

        envelope = ContentEnvelope(
            content=_JSON_REPEATED_LONG_KEYS, content_type=ContentType.JSON
        )
        strategy = KeyAliasingStrategy()
        result = strategy.compress(envelope)
        header = result.content.split("\n")[0]
        assert header.startswith("# aliases:")
        # Parse alias pairs
        alias_part = header.split("# aliases:")[1].strip()
        pairs = [p.strip() for p in alias_part.split(",")]
        for pair in pairs:
            assert "=" in pair
            alias, original = pair.split("=", 1)
            assert alias.startswith("k")

    def test_compress_preserves_content_type(self):
        """compress() preserves the envelope's content_type."""
        from token_sieve.adapters.compression.key_aliasing import (
            KeyAliasingStrategy,
        )

        envelope = ContentEnvelope(
            content=_JSON_REPEATED_LONG_KEYS, content_type=ContentType.JSON
        )
        strategy = KeyAliasingStrategy()
        result = strategy.compress(envelope)
        assert result.content_type == ContentType.JSON

    def test_compress_result_shorter(self):
        """Aliased content should be shorter than original."""
        from token_sieve.adapters.compression.key_aliasing import (
            KeyAliasingStrategy,
        )

        envelope = ContentEnvelope(
            content=_JSON_REPEATED_LONG_KEYS, content_type=ContentType.JSON
        )
        strategy = KeyAliasingStrategy()
        result = strategy.compress(envelope)
        assert len(result.content) < len(envelope.content)

    def test_configurable_thresholds(self):
        """min_occurrences and min_key_length are configurable."""
        from token_sieve.adapters.compression.key_aliasing import (
            KeyAliasingStrategy,
        )

        strategy = KeyAliasingStrategy(min_occurrences=3, min_key_length=5)
        assert strategy.min_occurrences == 3
        assert strategy.min_key_length == 5
