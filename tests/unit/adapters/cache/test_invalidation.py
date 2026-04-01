"""Tests for WriteThruInvalidator shared invalidation."""

from __future__ import annotations

import pytest

from token_sieve.adapters.cache.invalidation import WriteThruInvalidator


class _FakeObserver:
    """Test observer that records invalidation calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def invalidate(self, tool_name: str) -> None:
        self.calls.append(tool_name)


class TestIsMutating:
    """is_mutating() detects mutating tool names."""

    def test_write_tool_is_mutating(self) -> None:
        inv = WriteThruInvalidator()
        assert inv.is_mutating("file_write") is True

    def test_create_tool_is_mutating(self) -> None:
        inv = WriteThruInvalidator()
        assert inv.is_mutating("create_file") is True

    def test_delete_tool_is_mutating(self) -> None:
        inv = WriteThruInvalidator()
        assert inv.is_mutating("delete_resource") is True

    def test_update_tool_is_mutating(self) -> None:
        inv = WriteThruInvalidator()
        assert inv.is_mutating("update_config") is True

    def test_set_tool_is_mutating(self) -> None:
        inv = WriteThruInvalidator()
        assert inv.is_mutating("set_value") is True

    def test_remove_tool_is_mutating(self) -> None:
        inv = WriteThruInvalidator()
        assert inv.is_mutating("remove_entry") is True

    def test_add_tool_is_mutating(self) -> None:
        inv = WriteThruInvalidator()
        assert inv.is_mutating("add_item") is True

    def test_read_tool_is_not_mutating(self) -> None:
        inv = WriteThruInvalidator()
        assert inv.is_mutating("read_file") is False

    def test_get_tool_is_not_mutating(self) -> None:
        inv = WriteThruInvalidator()
        assert inv.is_mutating("get_data") is False

    def test_list_tool_is_not_mutating(self) -> None:
        inv = WriteThruInvalidator()
        assert inv.is_mutating("list_items") is False

    def test_search_tool_is_not_mutating(self) -> None:
        inv = WriteThruInvalidator()
        assert inv.is_mutating("search_docs") is False

    def test_case_insensitive(self) -> None:
        inv = WriteThruInvalidator()
        assert inv.is_mutating("FILE_WRITE") is True
        assert inv.is_mutating("Create_File") is True


class TestInvalidateFor:
    """invalidate_for() notifies all registered observers."""

    def test_notifies_single_observer(self) -> None:
        inv = WriteThruInvalidator()
        obs = _FakeObserver()
        inv.register_observer(obs)
        inv.invalidate_for("file_write")
        assert obs.calls == ["file_write"]

    def test_notifies_multiple_observers(self) -> None:
        inv = WriteThruInvalidator()
        obs1 = _FakeObserver()
        obs2 = _FakeObserver()
        inv.register_observer(obs1)
        inv.register_observer(obs2)
        inv.invalidate_for("delete_file")
        assert obs1.calls == ["delete_file"]
        assert obs2.calls == ["delete_file"]

    def test_no_observers_does_not_raise(self) -> None:
        inv = WriteThruInvalidator()
        inv.invalidate_for("file_write")  # should not raise


class TestCustomPatterns:
    """Custom mutating patterns configurable."""

    def test_custom_patterns(self) -> None:
        inv = WriteThruInvalidator(mutating_patterns={"deploy", "publish"})
        assert inv.is_mutating("deploy_app") is True
        assert inv.is_mutating("publish_release") is True
        assert inv.is_mutating("write_file") is False  # not in custom set

    def test_empty_patterns_nothing_mutates(self) -> None:
        inv = WriteThruInvalidator(mutating_patterns=set())
        assert inv.is_mutating("write_file") is False
        assert inv.is_mutating("delete_all") is False


class TestGlobalInvalidation:
    """Finding 6: invalidate_for must trigger global invalidation on observers."""

    def test_invalidate_for_calls_invalidate_all_on_observers(self) -> None:
        """invalidate_for() must call invalidate_all() (not invalidate(tool_name))."""

        class _TrackingObserver:
            def __init__(self) -> None:
                self.invalidated_tools: list[str] = []
                self.invalidate_all_called = False

            def invalidate(self, tool_name: str) -> None:
                self.invalidated_tools.append(tool_name)

            def invalidate_all(self) -> None:
                self.invalidate_all_called = True

        inv = WriteThruInvalidator()
        obs = _TrackingObserver()
        inv.register_observer(obs)
        inv.invalidate_for("write_file")
        assert obs.invalidate_all_called is True
