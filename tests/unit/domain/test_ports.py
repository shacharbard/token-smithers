"""Tests for domain Protocol interfaces (ports)."""

from __future__ import annotations

from typing import Any

import pytest

from token_sieve.domain.model import (
    CompressionEvent,
    ContentEnvelope,
    ContentType,
)
from token_sieve.domain.ports import (
    BackendToolAdapter,
    CompressionStrategy,
    DeduplicationStrategy,
    MetricsCollector,
    SessionRepository,
    TokenCounter,
)


# --- Import smoke tests ---


class TestProtocolImports:
    """All Protocol interfaces are importable."""

    def test_import_compression_strategy(self):
        assert CompressionStrategy is not None

    def test_import_deduplication_strategy(self):
        assert DeduplicationStrategy is not None

    def test_import_backend_tool_adapter(self):
        assert BackendToolAdapter is not None

    def test_import_session_repository(self):
        assert SessionRepository is not None

    def test_import_metrics_collector(self):
        assert MetricsCollector is not None

    def test_import_token_counter(self):
        assert TokenCounter is not None


# --- Structural subtyping tests ---


class TestProtocolStructuralSubtyping:
    """Plain classes satisfying Protocol method signatures are accepted."""

    def test_token_counter_runtime_checkable(self):
        """TokenCounter is @runtime_checkable, supports isinstance()."""

        class SimpleCounter:
            def count(self, text: str) -> int:
                return len(text)

        counter = SimpleCounter()
        assert isinstance(counter, TokenCounter)

    def test_compression_strategy_structural(self, make_envelope):
        """A plain class with matching methods works as CompressionStrategy."""

        class NoopStrategy:
            def can_handle(self, envelope: ContentEnvelope) -> bool:
                return True

            def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
                return envelope

        strategy = NoopStrategy()
        env = make_envelope(content="hello")
        assert isinstance(strategy.can_handle(env), bool)
        assert isinstance(strategy.compress(env), ContentEnvelope)

    def test_deduplication_strategy_structural(self):
        """A plain class with matching methods works as DeduplicationStrategy."""

        class NoopDedup:
            def is_duplicate(self, envelope: ContentEnvelope, session: Any) -> bool:
                return False

            def get_reference(self, envelope: ContentEnvelope, session: Any) -> str:
                return ""

        dedup = NoopDedup()
        assert isinstance(dedup.is_duplicate(None, None), bool)
        assert isinstance(dedup.get_reference(None, None), str)

    def test_backend_tool_adapter_structural(self):
        """A plain class with call_tool works as BackendToolAdapter."""

        class MockAdapter:
            def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
                return {"result": "ok"}

        adapter = MockAdapter()
        result = adapter.call_tool("test", {})
        assert result == {"result": "ok"}

    def test_session_repository_structural(self):
        """A plain class with get/save works as SessionRepository."""

        class InMemoryRepo:
            def get(self, session_id: str) -> Any:
                return None

            def save(self, session: Any) -> None:
                pass

        repo = InMemoryRepo()
        assert repo.get("test") is None
        repo.save(None)  # Should not raise

    def test_metrics_collector_structural(self):
        """A plain class with record/session_summary/strategy_breakdown works."""

        class InMemoryMetrics:
            def record(self, event: CompressionEvent) -> None:
                pass

            def session_summary(self) -> dict:
                return {}

            def strategy_breakdown(self) -> dict:
                return {}

        metrics = InMemoryMetrics()
        metrics.record(None)
        assert isinstance(metrics.session_summary(), dict)
        assert isinstance(metrics.strategy_breakdown(), dict)


# --- CompressionStrategyContract base class ---


class CompressionStrategyContract:
    """Base contract every CompressionStrategy implementation must satisfy.

    Concrete test classes inherit this and provide a `strategy` fixture.
    """

    @pytest.fixture
    def strategy(self) -> CompressionStrategy:
        raise NotImplementedError("Subclass must provide a strategy fixture")

    def test_can_handle_returns_bool(self, strategy, make_envelope):
        env = make_envelope(content="hello world")
        result = strategy.can_handle(env)
        assert isinstance(result, bool)

    def test_compress_returns_envelope(self, strategy, make_envelope):
        env = make_envelope(content="hello world " * 50)
        result = strategy.compress(env)
        assert isinstance(result, ContentEnvelope)

    def test_compress_preserves_content_type(self, strategy, make_envelope):
        env = make_envelope(content="hello world " * 50, content_type=ContentType.CODE)
        result = strategy.compress(env)
        assert result.content_type == env.content_type


# --- Contract test validation with MockStrategy ---


class TestMockStrategy(CompressionStrategyContract):
    """Validates the contract test pattern works end-to-end with MockStrategy."""

    @pytest.fixture
    def strategy(self, mock_strategy):
        return mock_strategy
