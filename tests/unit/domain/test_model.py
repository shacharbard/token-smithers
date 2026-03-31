"""Tests for domain model value objects."""

from __future__ import annotations

import dataclasses
from types import MappingProxyType

import pytest

from token_sieve.domain.model import (
    CompressedResult,
    CompressionEvent,
    ContentEnvelope,
    ContentType,
    TokenBudget,
)


# --- ContentType enum ---


class TestContentType:
    def test_has_all_expected_members(self):
        expected = {"TEXT", "JSON", "CODE", "CLI_OUTPUT", "UNKNOWN"}
        actual = {member.name for member in ContentType}
        assert actual == expected

    def test_members_are_distinct(self):
        values = [member.value for member in ContentType]
        assert len(values) == len(set(values))


# --- ContentEnvelope ---


class TestContentEnvelope:
    def test_construction(self, make_envelope):
        env = make_envelope(content="hello world")
        assert env.content == "hello world"
        assert env.content_type == ContentType.TEXT

    def test_frozen_immutability(self, make_envelope):
        env = make_envelope()
        with pytest.raises(dataclasses.FrozenInstanceError):
            env.content = "changed"

    def test_metadata_is_mapping_proxy(self, make_envelope):
        env = make_envelope(metadata={"key": "value"})
        assert isinstance(env.metadata, MappingProxyType)
        assert env.metadata["key"] == "value"

    def test_metadata_is_immutable(self, make_envelope):
        env = make_envelope(metadata={"key": "value"})
        with pytest.raises(TypeError):
            env.metadata["new_key"] = "fail"

    def test_empty_content_raises_value_error(self):
        with pytest.raises(ValueError, match="content must not be empty"):
            ContentEnvelope(content="", content_type=ContentType.TEXT)

    def test_default_metadata_is_empty_mapping_proxy(self):
        env = ContentEnvelope(content="x", content_type=ContentType.TEXT)
        assert isinstance(env.metadata, MappingProxyType)
        assert len(env.metadata) == 0

    def test_replace_returns_new_instance(self, make_envelope):
        env = make_envelope(content="original")
        new_env = dataclasses.replace(env, content="compressed")
        assert new_env.content == "compressed"
        assert env.content == "original"
        assert new_env is not env

    def test_replace_preserves_content_type(self, make_envelope):
        env = make_envelope(content="original", content_type=ContentType.CODE)
        new_env = dataclasses.replace(env, content="compressed")
        assert new_env.content_type == ContentType.CODE

    def test_equality_by_value(self):
        env1 = ContentEnvelope(content="a", content_type=ContentType.TEXT)
        env2 = ContentEnvelope(content="a", content_type=ContentType.TEXT)
        assert env1 == env2

    def test_inequality_on_different_content(self):
        env1 = ContentEnvelope(content="a", content_type=ContentType.TEXT)
        env2 = ContentEnvelope(content="b", content_type=ContentType.TEXT)
        assert env1 != env2

    def test_hashable(self, make_envelope):
        env = make_envelope()
        # Should not raise
        hash(env)

    # --- Finding 1: unhashable metadata rejected ---

    def test_unhashable_metadata_list_rejected(self):
        """Metadata containing a list value must raise TypeError."""
        with pytest.raises(TypeError, match="hashable"):
            ContentEnvelope(
                content="x",
                content_type=ContentType.TEXT,
                metadata={"key": [1, 2, 3]},
            )

    def test_unhashable_metadata_nested_dict_rejected(self):
        """Metadata containing a nested dict value must raise TypeError."""
        with pytest.raises(TypeError, match="hashable"):
            ContentEnvelope(
                content="x",
                content_type=ContentType.TEXT,
                metadata={"key": {"nested": "dict"}},
            )

    def test_hashable_scalar_metadata_accepted(self):
        """Metadata with str, int, float, bool, None values must be accepted."""
        env = ContentEnvelope(
            content="x",
            content_type=ContentType.TEXT,
            metadata={"s": "val", "i": 42, "f": 3.14, "b": True, "n": None},
        )
        # Should not raise and should be hashable
        hash(env)

    def test_content_type_variations(self):
        for ct in ContentType:
            env = ContentEnvelope(content="test", content_type=ct)
            assert env.content_type == ct


# --- CompressionEvent ---


class TestCompressionEvent:
    def test_construction(self, make_event):
        event = make_event(original_tokens=200, compressed_tokens=80)
        assert event.original_tokens == 200
        assert event.compressed_tokens == 80
        assert event.strategy_name == "test_strategy"

    def test_savings_ratio(self, make_event):
        event = make_event(original_tokens=100, compressed_tokens=25)
        assert event.savings_ratio == pytest.approx(0.75)

    def test_savings_ratio_zero_original(self, make_event):
        event = make_event(original_tokens=0, compressed_tokens=0)
        assert event.savings_ratio == 0.0

    def test_savings_ratio_no_compression(self, make_event):
        event = make_event(original_tokens=100, compressed_tokens=100)
        assert event.savings_ratio == pytest.approx(0.0)

    def test_frozen_immutability(self, make_event):
        event = make_event()
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.original_tokens = 999

    def test_content_type_recorded(self, make_event):
        event = make_event(content_type=ContentType.JSON)
        assert event.content_type == ContentType.JSON


# --- TokenBudget ---


class TestTokenBudget:
    def test_construction(self, make_budget):
        budget = make_budget(total=1000, used=200)
        assert budget.total == 1000
        assert budget.used == 200

    def test_remaining(self, make_budget):
        budget = make_budget(total=1000, used=300)
        assert budget.remaining == 700

    def test_is_exceeded_false(self, make_budget):
        budget = make_budget(total=1000, used=300)
        assert budget.is_exceeded is False

    def test_is_exceeded_true(self, make_budget):
        budget = make_budget(total=1000, used=1100)
        assert budget.is_exceeded is True

    def test_is_exceeded_at_boundary(self, make_budget):
        budget = make_budget(total=1000, used=1000)
        assert budget.is_exceeded is False

    def test_consume_returns_new_instance(self, make_budget):
        budget = make_budget(total=1000, used=200)
        new_budget = budget.consume(100)
        assert new_budget.used == 300
        assert new_budget.total == 1000
        assert budget.used == 200  # original unchanged

    def test_frozen_immutability(self, make_budget):
        budget = make_budget()
        with pytest.raises(dataclasses.FrozenInstanceError):
            budget.used = 500

    # --- Finding 2: negative values rejected ---

    def test_negative_total_raises(self):
        with pytest.raises(ValueError, match="total"):
            TokenBudget(total=-1, used=0)

    def test_negative_used_raises(self):
        with pytest.raises(ValueError, match="used"):
            TokenBudget(total=100, used=-1)

    def test_negative_consume_raises(self, make_budget):
        budget = make_budget(total=100, used=0)
        with pytest.raises(ValueError, match="tokens"):
            budget.consume(-10)


# --- CompressedResult ---


class TestCompressedResult:
    def test_construction(self, make_envelope, make_event):
        env = make_envelope(content="compressed output")
        event = make_event()
        result = CompressedResult(envelope=env, events=[event])
        assert result.envelope is env
        assert len(result.events) == 1

    def test_events_is_tuple(self, make_envelope, make_event):
        env = make_envelope(content="result")
        result = CompressedResult(
            envelope=env, events=[make_event(), make_event()]
        )
        assert isinstance(result.events, tuple)

    def test_events_accepts_tuple_directly(self, make_envelope, make_event):
        env = make_envelope(content="result")
        events_tuple = (make_event(),)
        result = CompressedResult(envelope=env, events=events_tuple)
        assert isinstance(result.events, tuple)
        assert len(result.events) == 1

    def test_frozen_immutability(self, make_envelope):
        env = make_envelope()
        result = CompressedResult(envelope=env, events=[])
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.envelope = env
