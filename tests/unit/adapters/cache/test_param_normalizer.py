"""Tests for parameter normalization utilities."""

from __future__ import annotations

import pytest

from token_sieve.adapters.cache.param_normalizer import (
    compute_args_hash,
    compute_similarity,
    normalize_args,
)


class TestNormalizeArgs:
    """normalize_args produces deterministic canonical form."""

    def test_reordered_keys_produce_same_output(self) -> None:
        a = {"path": "/src/main.py", "line": 10}
        b = {"line": 10, "path": "/src/main.py"}
        assert normalize_args(a) == normalize_args(b)

    def test_nested_keys_sorted_recursively(self) -> None:
        a = {"outer": {"z": 1, "a": 2}}
        b = {"outer": {"a": 2, "z": 1}}
        assert normalize_args(a) == normalize_args(b)

    def test_string_values_lowercased(self) -> None:
        a = {"path": "/SRC/Main.PY"}
        b = {"path": "/src/main.py"}
        assert normalize_args(a) == normalize_args(b)

    def test_whitespace_stripped(self) -> None:
        a = {"path": "  /src/main.py  "}
        b = {"path": "/src/main.py"}
        assert normalize_args(a) == normalize_args(b)

    def test_trailing_slash_removed(self) -> None:
        a = {"path": "/src/utils/"}
        b = {"path": "/src/utils"}
        assert normalize_args(a) == normalize_args(b)

    def test_none_null_empty_normalized(self) -> None:
        """None, 'null', and '' all normalize to the same form."""
        a = {"val": None}
        b = {"val": "null"}
        c = {"val": ""}
        assert normalize_args(a) == normalize_args(b) == normalize_args(c)

    def test_numeric_values_preserved(self) -> None:
        result = normalize_args({"count": 42, "ratio": 3.14})
        assert "42" in result
        assert "3.14" in result

    def test_empty_dict(self) -> None:
        result = normalize_args({})
        assert result == "{}"

    def test_list_values_sorted_if_strings(self) -> None:
        """String lists are sorted for determinism."""
        a = {"tags": ["beta", "alpha"]}
        b = {"tags": ["alpha", "beta"]}
        assert normalize_args(a) == normalize_args(b)


class TestComputeArgsHash:
    """compute_args_hash returns stable SHA-256 digests."""

    def test_same_args_same_hash(self) -> None:
        a = {"path": "/src/main.py", "line": 10}
        b = {"line": 10, "path": "/src/main.py"}
        assert compute_args_hash(a) == compute_args_hash(b)

    def test_different_args_different_hash(self) -> None:
        a = {"path": "/src/main.py"}
        b = {"path": "/src/other.py"}
        assert compute_args_hash(a) != compute_args_hash(b)

    def test_hash_is_hex_string(self) -> None:
        h = compute_args_hash({"key": "value"})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestComputeSimilarity:
    """compute_similarity uses SequenceMatcher ratio."""

    def test_identical_strings_return_1(self) -> None:
        assert compute_similarity("hello", "hello") == 1.0

    def test_completely_different_below_half(self) -> None:
        assert compute_similarity("abcdef", "xyz123") < 0.5

    def test_similar_strings_high_score(self) -> None:
        # Only difference is trailing slash
        score = compute_similarity(
            '{"path": "/src/main.py"}',
            '{"path": "/src/main.py/"}',
        )
        assert score >= 0.85

    def test_empty_strings_return_1(self) -> None:
        assert compute_similarity("", "") == 1.0
