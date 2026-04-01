"""Tests for AttentionScore frozen dataclass value object."""

from __future__ import annotations

import time

import pytest


class TestAttentionScoreConstruction:
    """AttentionScore is constructable with required fields."""

    def test_create_with_all_fields(self) -> None:
        from token_sieve.domain.attention_score import AttentionScore

        now = time.monotonic()
        score = AttentionScore(
            tool_name="read_file",
            reference_count=3,
            last_referenced=now,
            decay_score=0.85,
        )
        assert score.tool_name == "read_file"
        assert score.reference_count == 3
        assert score.last_referenced == now
        assert score.decay_score == 0.85

    def test_default_decay_score(self) -> None:
        from token_sieve.domain.attention_score import AttentionScore

        score = AttentionScore(
            tool_name="search",
            reference_count=1,
            last_referenced=0.0,
        )
        assert score.decay_score == 0.0


class TestAttentionScoreImmutability:
    """AttentionScore is frozen -- fields cannot be mutated."""

    def test_frozen_tool_name(self) -> None:
        from token_sieve.domain.attention_score import AttentionScore

        score = AttentionScore(
            tool_name="x", reference_count=1, last_referenced=0.0
        )
        with pytest.raises(AttributeError):
            score.tool_name = "y"  # type: ignore[misc]

    def test_frozen_reference_count(self) -> None:
        from token_sieve.domain.attention_score import AttentionScore

        score = AttentionScore(
            tool_name="x", reference_count=1, last_referenced=0.0
        )
        with pytest.raises(AttributeError):
            score.reference_count = 99  # type: ignore[misc]

    def test_frozen_decay_score(self) -> None:
        from token_sieve.domain.attention_score import AttentionScore

        score = AttentionScore(
            tool_name="x",
            reference_count=1,
            last_referenced=0.0,
            decay_score=0.5,
        )
        with pytest.raises(AttributeError):
            score.decay_score = 1.0  # type: ignore[misc]


class TestAttentionScoreEquality:
    """AttentionScore supports equality and hashing."""

    def test_equal_scores(self) -> None:
        from token_sieve.domain.attention_score import AttentionScore

        a = AttentionScore(
            tool_name="t", reference_count=2, last_referenced=1.0, decay_score=0.5
        )
        b = AttentionScore(
            tool_name="t", reference_count=2, last_referenced=1.0, decay_score=0.5
        )
        assert a == b

    def test_different_scores(self) -> None:
        from token_sieve.domain.attention_score import AttentionScore

        a = AttentionScore(
            tool_name="t", reference_count=2, last_referenced=1.0, decay_score=0.5
        )
        b = AttentionScore(
            tool_name="t", reference_count=3, last_referenced=1.0, decay_score=0.5
        )
        assert a != b

    def test_hashable(self) -> None:
        from token_sieve.domain.attention_score import AttentionScore

        score = AttentionScore(
            tool_name="t", reference_count=1, last_referenced=0.0
        )
        assert isinstance(hash(score), int)

    def test_usable_in_set(self) -> None:
        from token_sieve.domain.attention_score import AttentionScore

        a = AttentionScore(
            tool_name="t", reference_count=1, last_referenced=0.0
        )
        b = AttentionScore(
            tool_name="t", reference_count=1, last_referenced=0.0
        )
        assert len({a, b}) == 1
