"""Tests for DiffStateStore."""

from __future__ import annotations

import pytest

from token_sieve.adapters.cache.diff_state_store import DiffStateStore
from token_sieve.adapters.cache.invalidation import WriteThruInvalidator


class TestStoreAndRetrieve:
    """store_result() saves content, get_previous() retrieves."""

    def test_store_and_retrieve(self) -> None:
        store = DiffStateStore()
        store.store_result("read_file", {"path": "a"}, "content A")
        assert store.get_previous("read_file", {"path": "a"}) == "content A"

    def test_get_previous_returns_none_on_miss(self) -> None:
        store = DiffStateStore()
        assert store.get_previous("read_file", {"path": "a"}) is None

    def test_overwrite_returns_latest(self) -> None:
        store = DiffStateStore()
        store.store_result("tool", {"k": "1"}, "v1")
        store.store_result("tool", {"k": "1"}, "v2")
        assert store.get_previous("tool", {"k": "1"}) == "v2"


class TestLRUEviction:
    """LRU eviction at cap (100 default)."""

    def test_evicts_at_cap(self) -> None:
        store = DiffStateStore(max_entries=3)
        store.store_result("t1", {"k": "1"}, "v1")
        store.store_result("t2", {"k": "2"}, "v2")
        store.store_result("t3", {"k": "3"}, "v3")
        store.store_result("t4", {"k": "4"}, "v4")
        assert store.get_previous("t1", {"k": "1"}) is None  # evicted
        assert store.get_previous("t4", {"k": "4"}) == "v4"

    def test_default_max_entries_is_100(self) -> None:
        store = DiffStateStore()
        assert store._max_entries == 100


class TestInvalidation:
    """Invalidation observer clears entries."""

    def test_invalidate_clears_tool_entries(self) -> None:
        store = DiffStateStore()
        store.store_result("read_file", {"path": "a"}, "v1")
        store.store_result("read_file", {"path": "b"}, "v2")
        store.store_result("list_items", {}, "v3")
        store.invalidate("read_file")
        assert store.get_previous("read_file", {"path": "a"}) is None
        assert store.get_previous("read_file", {"path": "b"}) is None
        assert store.get_previous("list_items", {}) == "v3"

    def test_invalidation_via_write_thru(self) -> None:
        inv = WriteThruInvalidator()
        store = DiffStateStore()
        inv.register_observer(store)
        store.store_result("read_file", {"path": "a"}, "cached")
        inv.invalidate_for("read_file")
        assert store.get_previous("read_file", {"path": "a"}) is None


class TestGlobalInvalidation:
    """Finding 6: DiffStateStore must support global invalidation."""

    def test_invalidate_all_clears_entire_store(self) -> None:
        """invalidate_all() clears every entry regardless of tool name."""
        store = DiffStateStore()
        store.store_result("read_file", {"path": "a"}, "r1")
        store.store_result("list_items", {}, "r2")
        store.invalidate_all()
        assert store.get_previous("read_file", {"path": "a"}) is None
        assert store.get_previous("list_items", {}) is None

    def test_write_thru_global_invalidation(self) -> None:
        """WriteThruInvalidator triggers global invalidation on mutating call."""
        inv = WriteThruInvalidator()
        store = DiffStateStore()
        inv.register_observer(store)
        store.store_result("read_file", {"path": "a"}, "cached_read")
        store.store_result("list_items", {}, "cached_list")
        inv.invalidate_for("write_file")
        assert store.get_previous("read_file", {"path": "a"}) is None
        assert store.get_previous("list_items", {}) is None
