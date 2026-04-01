"""Tests for IdempotentCallCache."""

from __future__ import annotations

import pytest

from token_sieve.adapters.cache.call_cache import IdempotentCallCache
from token_sieve.adapters.cache.invalidation import WriteThruInvalidator


class TestCacheMissAndHit:
    """Cache miss/hit behavior."""

    def test_cache_miss_returns_none(self) -> None:
        cache = IdempotentCallCache()
        assert cache.get("read_file", {"path": "/tmp/a.txt"}) is None

    def test_cache_hit_returns_cached_result(self) -> None:
        cache = IdempotentCallCache()
        result = {"content": "hello"}
        cache.put("read_file", {"path": "/tmp/a.txt"}, result)
        assert cache.get("read_file", {"path": "/tmp/a.txt"}) is result

    def test_different_args_cache_miss(self) -> None:
        cache = IdempotentCallCache()
        cache.put("read_file", {"path": "/tmp/a.txt"}, {"content": "a"})
        assert cache.get("read_file", {"path": "/tmp/b.txt"}) is None

    def test_different_tool_cache_miss(self) -> None:
        cache = IdempotentCallCache()
        cache.put("read_file", {"path": "/tmp/a.txt"}, {"content": "a"})
        assert cache.get("write_file", {"path": "/tmp/a.txt"}) is None

    def test_none_args_works(self) -> None:
        cache = IdempotentCallCache()
        cache.put("list_all", None, ["a", "b"])
        assert cache.get("list_all", None) == ["a", "b"]

    def test_empty_args_works(self) -> None:
        cache = IdempotentCallCache()
        cache.put("list_all", {}, ["a", "b"])
        assert cache.get("list_all", {}) == ["a", "b"]


class TestKeyDeterminism:
    """Cache key computation is deterministic regardless of arg order."""

    def test_key_same_for_different_arg_order(self) -> None:
        cache = IdempotentCallCache()
        result = {"data": 42}
        cache.put("tool", {"b": 2, "a": 1}, result)
        assert cache.get("tool", {"a": 1, "b": 2}) is result

    def test_key_different_for_different_values(self) -> None:
        cache = IdempotentCallCache()
        cache.put("tool", {"a": 1}, "result1")
        assert cache.get("tool", {"a": 2}) is None


class TestSessionScoped:
    """Session-scoped: clear_all resets."""

    def test_clear_all_removes_everything(self) -> None:
        cache = IdempotentCallCache()
        cache.put("tool1", {"a": 1}, "r1")
        cache.put("tool2", {"b": 2}, "r2")
        cache.clear_all()
        assert cache.get("tool1", {"a": 1}) is None
        assert cache.get("tool2", {"b": 2}) is None


class TestInvalidation:
    """Invalidation from WriteThruInvalidator clears related entries."""

    def test_invalidate_clears_tool_entries(self) -> None:
        cache = IdempotentCallCache()
        cache.put("read_file", {"path": "a"}, "r1")
        cache.put("read_file", {"path": "b"}, "r2")
        cache.put("list_items", {}, "r3")
        cache.invalidate("read_file")
        assert cache.get("read_file", {"path": "a"}) is None
        assert cache.get("read_file", {"path": "b"}) is None
        assert cache.get("list_items", {}) == "r3"  # unrelated preserved

    def test_invalidation_via_write_thru(self) -> None:
        """Integration: WriteThruInvalidator notifies cache."""
        inv = WriteThruInvalidator()
        cache = IdempotentCallCache()
        inv.register_observer(cache)
        cache.put("read_file", {"path": "a"}, "cached")
        inv.invalidate_for("read_file")
        assert cache.get("read_file", {"path": "a"}) is None


class TestBoundedSize:
    """Bounded size with LRU eviction."""

    def test_evicts_oldest_when_exceeding_max(self) -> None:
        cache = IdempotentCallCache(max_entries=3)
        cache.put("t1", {"k": "1"}, "r1")
        cache.put("t2", {"k": "2"}, "r2")
        cache.put("t3", {"k": "3"}, "r3")
        # Adding a 4th should evict the oldest (t1)
        cache.put("t4", {"k": "4"}, "r4")
        assert cache.get("t1", {"k": "1"}) is None  # evicted
        assert cache.get("t4", {"k": "4"}) == "r4"  # present

    def test_access_refreshes_lru(self) -> None:
        cache = IdempotentCallCache(max_entries=3)
        cache.put("t1", {"k": "1"}, "r1")
        cache.put("t2", {"k": "2"}, "r2")
        cache.put("t3", {"k": "3"}, "r3")
        # Access t1 to refresh it
        cache.get("t1", {"k": "1"})
        # Add t4 — should evict t2 (now oldest), not t1
        cache.put("t4", {"k": "4"}, "r4")
        assert cache.get("t1", {"k": "1"}) == "r1"  # still present
        assert cache.get("t2", {"k": "2"}) is None  # evicted

    def test_default_max_entries_is_200(self) -> None:
        cache = IdempotentCallCache()
        assert cache._max_entries == 200


class TestGlobalInvalidation:
    """Finding 6: Mutating calls must invalidate ALL cached entries globally."""

    def test_invalidate_all_clears_entire_cache(self) -> None:
        """invalidate_all() clears every entry regardless of tool name."""
        cache = IdempotentCallCache()
        cache.put("read_file", {"path": "a"}, "r1")
        cache.put("list_items", {}, "r2")
        cache.put("search", {"q": "x"}, "r3")
        cache.invalidate_all()
        assert cache.get("read_file", {"path": "a"}) is None
        assert cache.get("list_items", {}) is None
        assert cache.get("search", {"q": "x"}) is None

    def test_write_thru_global_invalidation(self) -> None:
        """WriteThruInvalidator triggers global invalidation on mutating call."""
        inv = WriteThruInvalidator()
        cache = IdempotentCallCache()
        inv.register_observer(cache)
        cache.put("read_file", {"path": "a"}, "cached_read")
        cache.put("list_items", {}, "cached_list")
        # Mutating call to write_file should invalidate ALL entries
        inv.invalidate_for("write_file")
        assert cache.get("read_file", {"path": "a"}) is None
        assert cache.get("list_items", {}) is None
