"""Tests for LearningStore Protocol -- structural subtyping + contract base.

Contract tests define the behavioral specification for any LearningStore
implementation. Concrete adapters subclass LearningStoreContract with a
fixture providing the implementation under test.
"""

from __future__ import annotations

from typing import Any

import pytest

from token_sieve.domain.model import CompressionEvent, ContentType


class TestLearningStoreImports:
    """LearningStore Protocol and domain types are importable."""

    def test_import_learning_store(self) -> None:
        from token_sieve.domain.ports_learning import LearningStore

        assert LearningStore is not None

    def test_protocol_has_record_call(self) -> None:
        from token_sieve.domain.ports_learning import LearningStore

        assert hasattr(LearningStore, "record_call")

    def test_protocol_has_get_usage_stats(self) -> None:
        from token_sieve.domain.ports_learning import LearningStore

        assert hasattr(LearningStore, "get_usage_stats")

    def test_protocol_has_cache_result(self) -> None:
        from token_sieve.domain.ports_learning import LearningStore

        assert hasattr(LearningStore, "cache_result")

    def test_protocol_has_lookup_similar(self) -> None:
        from token_sieve.domain.ports_learning import LearningStore

        assert hasattr(LearningStore, "lookup_similar")

    def test_protocol_has_record_compression_event(self) -> None:
        from token_sieve.domain.ports_learning import LearningStore

        assert hasattr(LearningStore, "record_compression_event")

    def test_protocol_has_record_cooccurrence(self) -> None:
        from token_sieve.domain.ports_learning import LearningStore

        assert hasattr(LearningStore, "record_cooccurrence")

    def test_protocol_has_get_cooccurrence(self) -> None:
        from token_sieve.domain.ports_learning import LearningStore

        assert hasattr(LearningStore, "get_cooccurrence")

    def test_protocol_has_get_pipeline_config(self) -> None:
        from token_sieve.domain.ports_learning import LearningStore

        assert hasattr(LearningStore, "get_pipeline_config")

    def test_protocol_has_save_pipeline_config(self) -> None:
        from token_sieve.domain.ports_learning import LearningStore

        assert hasattr(LearningStore, "save_pipeline_config")

    def test_protocol_has_increment_regret_streak(self) -> None:
        from token_sieve.domain.ports_learning import LearningStore

        assert hasattr(LearningStore, "increment_regret_streak")

    def test_protocol_has_reset_regret_streak(self) -> None:
        from token_sieve.domain.ports_learning import LearningStore

        assert hasattr(LearningStore, "reset_regret_streak")


class TestLearningTypesImports:
    """ToolUsageRecord and CooccurrenceRecord are importable frozen dataclasses."""

    def test_import_tool_usage_record(self) -> None:
        from token_sieve.domain.learning_types import ToolUsageRecord

        assert ToolUsageRecord is not None

    def test_import_cooccurrence_record(self) -> None:
        from token_sieve.domain.learning_types import CooccurrenceRecord

        assert CooccurrenceRecord is not None

    def test_tool_usage_record_frozen(self) -> None:
        from token_sieve.domain.learning_types import ToolUsageRecord

        record = ToolUsageRecord(
            tool_name="read_file",
            server_id="default",
            call_count=5,
            last_called_at="2026-04-01T10:00:00Z",
        )
        with pytest.raises(AttributeError):
            record.call_count = 10  # type: ignore[misc]

    def test_cooccurrence_record_frozen(self) -> None:
        from token_sieve.domain.learning_types import CooccurrenceRecord

        record = CooccurrenceRecord(
            tool_a="read_file",
            tool_b="write_file",
            co_count=3,
            last_seen="2026-04-01T10:00:00Z",
        )
        with pytest.raises(AttributeError):
            record.co_count = 10  # type: ignore[misc]

    def test_tool_usage_record_fields(self) -> None:
        from token_sieve.domain.learning_types import ToolUsageRecord

        record = ToolUsageRecord(
            tool_name="read_file",
            server_id="default",
            call_count=5,
            last_called_at="2026-04-01T10:00:00Z",
        )
        assert record.tool_name == "read_file"
        assert record.server_id == "default"
        assert record.call_count == 5
        assert record.last_called_at == "2026-04-01T10:00:00Z"

    def test_cooccurrence_record_fields(self) -> None:
        from token_sieve.domain.learning_types import CooccurrenceRecord

        record = CooccurrenceRecord(
            tool_a="read_file",
            tool_b="write_file",
            co_count=3,
            last_seen="2026-04-01T10:00:00Z",
        )
        assert record.tool_a == "read_file"
        assert record.tool_b == "write_file"
        assert record.co_count == 3
        assert record.last_seen == "2026-04-01T10:00:00Z"

    def test_import_pipeline_config(self) -> None:
        from token_sieve.domain.learning_types import PipelineConfig

        assert PipelineConfig is not None

    def test_pipeline_config_frozen(self) -> None:
        from token_sieve.domain.learning_types import PipelineConfig

        config = PipelineConfig(
            tool_name="read_file",
            server_id="default",
            adapter_order=("whitespace", "null_field"),
            disabled_adapters=(),
            eval_count=5,
            regret_streak=0,
            last_eval_at="2026-04-01T10:00:00Z",
            created_at="2026-04-01T09:00:00Z",
        )
        with pytest.raises(AttributeError):
            config.eval_count = 10  # type: ignore[misc]

    def test_pipeline_config_fields(self) -> None:
        from token_sieve.domain.learning_types import PipelineConfig

        config = PipelineConfig(
            tool_name="read_file",
            server_id="server1",
            adapter_order=("whitespace", "null_field"),
            disabled_adapters=("rle",),
            eval_count=10,
            regret_streak=2,
            last_eval_at="2026-04-01T10:00:00Z",
            created_at="2026-04-01T09:00:00Z",
        )
        assert config.tool_name == "read_file"
        assert config.server_id == "server1"
        assert config.adapter_order == ("whitespace", "null_field")
        assert config.disabled_adapters == ("rle",)
        assert config.eval_count == 10
        assert config.regret_streak == 2
        assert config.last_eval_at == "2026-04-01T10:00:00Z"
        assert config.created_at == "2026-04-01T09:00:00Z"

    def test_pipeline_config_defaults(self) -> None:
        from token_sieve.domain.learning_types import PipelineConfig

        config = PipelineConfig(tool_name="t", server_id="s")
        assert config.adapter_order == ()
        assert config.disabled_adapters == ()
        assert config.eval_count == 0
        assert config.regret_streak == 0


class TestLearningStoreStructuralSubtyping:
    """Plain class satisfying Protocol method signatures is accepted."""

    def test_runtime_checkable(self) -> None:
        """LearningStore is @runtime_checkable, supports isinstance()."""
        from token_sieve.domain.learning_types import (
            CooccurrenceRecord,
            PipelineConfig,
            ToolUsageRecord,
        )
        from token_sieve.domain.ports_learning import LearningStore

        class MockStore:
            async def record_call(self, tool_name: str, server_id: str) -> None:
                pass

            async def get_usage_stats(self, server_id: str) -> list[ToolUsageRecord]:
                return []

            async def cache_result(
                self, tool_name: str, args_normalized: str, result: str
            ) -> None:
                pass

            async def lookup_similar(
                self, tool_name: str, args_normalized: str, threshold: float
            ) -> str | None:
                return None

            async def record_compression_event(
                self, session_id: str, event: CompressionEvent, tool_name: str
            ) -> None:
                pass

            async def record_cooccurrence(
                self, tool_a: str, tool_b: str
            ) -> None:
                pass

            async def get_cooccurrence(
                self, tool_name: str
            ) -> list[CooccurrenceRecord]:
                return []

            async def get_pipeline_config(
                self, tool_name: str, server_id: str
            ) -> PipelineConfig | None:
                return None

            async def save_pipeline_config(
                self, config: PipelineConfig
            ) -> None:
                pass

            async def increment_regret_streak(
                self, tool_name: str, server_id: str
            ) -> int:
                return 1

            async def reset_regret_streak(
                self, tool_name: str, server_id: str
            ) -> None:
                pass

            async def save_frozen_order(
                self, server_id: str, order: list[str]
            ) -> None:
                pass

            async def load_frozen_order(
                self, server_id: str
            ) -> list[str] | None:
                return None

            async def get_session_report(self, session_id: str) -> dict:
                return {}

            async def get_cross_server_stats(self) -> list[dict]:
                return []

            async def get_adapter_effectiveness(
                self, limit: int = 10
            ) -> list[dict]:
                return []

            async def get_savings_trend(
                self, sessions: int = 10
            ) -> list[dict]:
                return []

        assert isinstance(MockStore(), LearningStore)

    def test_missing_method_not_instance(self) -> None:
        """Class missing a method does NOT satisfy the Protocol."""
        from token_sieve.domain.ports_learning import LearningStore

        class IncompleteStore:
            async def record_call(self, tool_name: str, server_id: str) -> None:
                pass
            # Missing all other methods

        assert not isinstance(IncompleteStore(), LearningStore)


class TestLearningStoreZeroDeps:
    """ports_learning.py has zero external dependencies."""

    def test_no_external_imports(self) -> None:
        import importlib
        import inspect

        mod = importlib.import_module("token_sieve.domain.ports_learning")
        source = inspect.getsource(mod)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                assert not any(
                    pkg in stripped
                    for pkg in ["pydantic", "mcp", "yaml", "requests", "httpx", "aiosqlite"]
                ), f"External import found: {stripped}"

    def test_learning_types_no_external_imports(self) -> None:
        import importlib
        import inspect

        mod = importlib.import_module("token_sieve.domain.learning_types")
        source = inspect.getsource(mod)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                assert not any(
                    pkg in stripped
                    for pkg in ["pydantic", "mcp", "yaml", "requests", "httpx", "aiosqlite"]
                ), f"External import found: {stripped}"


class LearningStoreContract:
    """Contract test base class for LearningStore implementations.

    Subclass this with a @pytest.fixture named ``store`` that returns
    the concrete implementation. All tests use async to match Protocol.
    """

    @pytest.fixture()
    def store(self):
        """Override in subclass to provide concrete LearningStore."""
        raise NotImplementedError

    async def test_cold_start_usage_stats_empty(self, store) -> None:
        """Fresh store returns empty list for usage stats."""
        stats = await store.get_usage_stats("default")
        assert stats == []

    async def test_cold_start_lookup_returns_none(self, store) -> None:
        """Fresh store returns None for lookup."""
        result = await store.lookup_similar("read_file", '{"path": "/tmp"}', 0.85)
        assert result is None

    async def test_cold_start_cooccurrence_empty(self, store) -> None:
        """Fresh store returns empty cooccurrence list."""
        records = await store.get_cooccurrence("read_file")
        assert records == []

    async def test_record_call_and_retrieve(self, store) -> None:
        """Record a call, then retrieve usage stats."""
        await store.record_call("read_file", "server1")
        stats = await store.get_usage_stats("server1")
        assert len(stats) == 1
        assert stats[0].tool_name == "read_file"
        assert stats[0].server_id == "server1"
        assert stats[0].call_count == 1

    async def test_record_call_increments(self, store) -> None:
        """Multiple calls increment count."""
        await store.record_call("read_file", "server1")
        await store.record_call("read_file", "server1")
        stats = await store.get_usage_stats("server1")
        assert len(stats) == 1
        assert stats[0].call_count == 2

    async def test_cache_result_and_lookup(self, store) -> None:
        """Cache a result, then look it up by exact args."""
        await store.cache_result("read_file", '{"path": "/tmp/a.txt"}', "file content")
        result = await store.lookup_similar(
            "read_file", '{"path": "/tmp/a.txt"}', 0.85
        )
        assert result == "file content"

    async def test_lookup_below_threshold_returns_none(self, store) -> None:
        """Lookup with non-matching args returns None."""
        await store.cache_result("read_file", '{"path": "/tmp/a.txt"}', "content a")
        result = await store.lookup_similar(
            "read_file", '{"path": "/completely/different"}', 0.85
        )
        assert result is None

    async def test_record_compression_event(self, store) -> None:
        """Recording a compression event does not raise."""
        event = CompressionEvent(
            original_tokens=100,
            compressed_tokens=50,
            strategy_name="whitespace_normalizer",
            content_type=ContentType.TEXT,
        )
        await store.record_compression_event("session1", event, "read_file")

    async def test_record_cooccurrence_and_retrieve(self, store) -> None:
        """Record cooccurrence, then retrieve."""
        await store.record_cooccurrence("read_file", "write_file")
        records = await store.get_cooccurrence("read_file")
        assert len(records) == 1
        assert records[0].tool_b == "write_file"
        assert records[0].co_count == 1

    async def test_cooccurrence_increments(self, store) -> None:
        """Multiple cooccurrences increment count."""
        await store.record_cooccurrence("read_file", "write_file")
        await store.record_cooccurrence("read_file", "write_file")
        records = await store.get_cooccurrence("read_file")
        assert len(records) == 1
        assert records[0].co_count == 2

    async def test_usage_stats_filtered_by_server(self, store) -> None:
        """Usage stats are filtered by server_id."""
        await store.record_call("read_file", "server1")
        await store.record_call("write_file", "server2")
        stats = await store.get_usage_stats("server1")
        assert len(stats) == 1
        assert stats[0].tool_name == "read_file"

    # --- PipelineConfig contract tests ---

    async def test_get_pipeline_config_cold_start(self, store) -> None:
        """Fresh store returns None for pipeline config."""
        result = await store.get_pipeline_config("read_file", "default")
        assert result is None

    async def test_save_and_get_pipeline_config(self, store) -> None:
        """Save a pipeline config, then retrieve it."""
        from token_sieve.domain.learning_types import PipelineConfig

        config = PipelineConfig(
            tool_name="read_file",
            server_id="server1",
            adapter_order=("whitespace", "null_field"),
            disabled_adapters=("rle",),
            eval_count=5,
            regret_streak=1,
            last_eval_at="2026-04-01T10:00:00Z",
            created_at="2026-04-01T09:00:00Z",
        )
        await store.save_pipeline_config(config)
        retrieved = await store.get_pipeline_config("read_file", "server1")
        assert retrieved is not None
        assert retrieved.tool_name == "read_file"
        assert retrieved.server_id == "server1"
        assert retrieved.adapter_order == ("whitespace", "null_field")
        assert retrieved.disabled_adapters == ("rle",)
        assert retrieved.eval_count == 5
        assert retrieved.regret_streak == 1

    async def test_save_pipeline_config_upsert(self, store) -> None:
        """Second save overwrites the first."""
        from token_sieve.domain.learning_types import PipelineConfig

        config1 = PipelineConfig(
            tool_name="read_file",
            server_id="default",
            adapter_order=("a",),
            last_eval_at="2026-04-01T10:00:00Z",
            created_at="2026-04-01T09:00:00Z",
        )
        await store.save_pipeline_config(config1)

        config2 = PipelineConfig(
            tool_name="read_file",
            server_id="default",
            adapter_order=("a", "b"),
            eval_count=10,
            last_eval_at="2026-04-01T11:00:00Z",
            created_at="2026-04-01T09:00:00Z",
        )
        await store.save_pipeline_config(config2)

        retrieved = await store.get_pipeline_config("read_file", "default")
        assert retrieved is not None
        assert retrieved.adapter_order == ("a", "b")
        assert retrieved.eval_count == 10

    async def test_increment_regret_streak(self, store) -> None:
        """Increment regret streak returns new value."""
        from token_sieve.domain.learning_types import PipelineConfig

        config = PipelineConfig(
            tool_name="read_file",
            server_id="default",
            regret_streak=0,
            last_eval_at="2026-04-01T10:00:00Z",
            created_at="2026-04-01T09:00:00Z",
        )
        await store.save_pipeline_config(config)

        new_streak = await store.increment_regret_streak("read_file", "default")
        assert new_streak == 1

        new_streak = await store.increment_regret_streak("read_file", "default")
        assert new_streak == 2

    async def test_reset_regret_streak(self, store) -> None:
        """Reset regret streak sets it to zero."""
        from token_sieve.domain.learning_types import PipelineConfig

        config = PipelineConfig(
            tool_name="read_file",
            server_id="default",
            regret_streak=3,
            last_eval_at="2026-04-01T10:00:00Z",
            created_at="2026-04-01T09:00:00Z",
        )
        await store.save_pipeline_config(config)

        await store.reset_regret_streak("read_file", "default")
        retrieved = await store.get_pipeline_config("read_file", "default")
        assert retrieved is not None
        assert retrieved.regret_streak == 0

    async def test_record_compression_event_with_regret(self, store) -> None:
        """Recording a compression event with is_regret=True does not raise."""
        event = CompressionEvent(
            original_tokens=50,
            compressed_tokens=80,
            strategy_name="whitespace_normalizer",
            content_type=ContentType.TEXT,
            is_regret=True,
        )
        await store.record_compression_event("session1", event, "read_file")
