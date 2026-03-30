"""Tests for CharEstimateCounter -- chars/4 token estimation.

TDD RED phase: these tests define the counter contract before implementation.
"""

from __future__ import annotations

import pytest

from token_sieve.domain.ports import TokenCounter


class TestCharEstimateCounter:
    """CharEstimateCounter uses chars/4 approximation for token counting."""

    def test_char_estimate_empty_string(self):
        from token_sieve.domain.counters import CharEstimateCounter

        counter = CharEstimateCounter()
        assert counter.count("") == 0

    def test_char_estimate_known_text(self):
        from token_sieve.domain.counters import CharEstimateCounter

        counter = CharEstimateCounter()
        # "hello world" = 11 chars, 11 // 4 = 2, but min 1 for non-empty
        assert counter.count("hello world") == 2

    def test_char_estimate_satisfies_token_counter_protocol(self):
        from token_sieve.domain.counters import CharEstimateCounter

        counter = CharEstimateCounter()
        assert isinstance(counter, TokenCounter)

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("", 0),
            ("a", 1),  # 1 char -> max(1, 0) = 1
            ("ab", 1),  # 2 chars -> max(1, 0) = 1
            ("abc", 1),  # 3 chars -> max(1, 0) = 1
            ("abcd", 1),  # 4 chars -> max(1, 1) = 1
            ("abcde", 1),  # 5 chars -> max(1, 1) = 1
            ("a" * 8, 2),  # 8 chars -> max(1, 2) = 2
            ("a" * 100, 25),  # 100 chars -> max(1, 25) = 25
            ("a" * 1000, 250),  # 1000 chars -> max(1, 250) = 250
        ],
    )
    def test_char_estimate_formula(self, text: str, expected: int):
        from token_sieve.domain.counters import CharEstimateCounter

        counter = CharEstimateCounter()
        assert counter.count(text) == expected
