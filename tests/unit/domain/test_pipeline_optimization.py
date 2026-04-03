"""Tests for per-tool pipeline chain filtering via PipelineConfig."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from token_sieve.domain.model import ContentEnvelope, ContentType
from token_sieve.domain.pipeline import CompressionPipeline


def _make_strategy(name: str, savings: int = 10) -> MagicMock:
    """Create a fake strategy that compresses by removing `savings` chars."""
    strategy = MagicMock()
    strategy.__class__ = type(name, (), {})
    type(strategy).__name__ = name
    strategy.can_handle = MagicMock(return_value=True)

    def compress_side_effect(envelope: ContentEnvelope) -> ContentEnvelope:
        content = envelope.content
        # Remove `savings` chars to simulate compression
        compressed = content[: max(1, len(content) - savings * 4)]
        return ContentEnvelope(
            content=compressed,
            content_type=envelope.content_type,
            metadata=envelope.metadata,
        )

    strategy.compress = MagicMock(side_effect=compress_side_effect)
    return strategy


def _make_counter() -> MagicMock:
    counter = MagicMock()
    counter.count = MagicMock(side_effect=lambda text: max(1, len(text) // 4))
    return counter


def _make_config_store(config=None) -> MagicMock:
    """Create a fake pipeline config store."""
    store = MagicMock()
    store.get_pipeline_config = MagicMock(return_value=config)
    store.save_pipeline_config = MagicMock()
    return store


class TestPerToolFiltering:
    """Pipeline filters adapter chain based on PipelineConfig."""

    def test_disabled_adapters_are_skipped(self) -> None:
        """When disabled_adapters metadata is set, those adapters are skipped.

        C2 fix: disabled_adapters are now passed via envelope metadata
        (comma-separated string) by the async caller, not via
        pipeline_config_store (which was a sync→async mismatch).
        """
        counter = _make_counter()
        pipeline = CompressionPipeline(counter=counter)

        s1 = _make_strategy("NullFieldElider")
        s2 = _make_strategy("SmartTruncation")
        s3 = _make_strategy("WhitespaceNormalizer")
        pipeline.register(ContentType.TEXT, s1)
        pipeline.register(ContentType.TEXT, s2)
        pipeline.register(ContentType.TEXT, s3)

        envelope = ContentEnvelope(
            content="x" * 200,
            content_type=ContentType.TEXT,
            metadata={
                "source_tool": "read_file",
                "disabled_adapters": "SmartTruncation",
            },
        )
        pipeline.process(envelope)

        # SmartTruncation should NOT have been called
        s1.compress.assert_called()
        s2.compress.assert_not_called()
        s3.compress.assert_called()

    def test_full_chain_when_no_config(self) -> None:
        """Without PipelineConfig (< 10 calls), full chain runs."""
        counter = _make_counter()
        pipeline = CompressionPipeline(counter=counter)

        s1 = _make_strategy("NullFieldElider")
        s2 = _make_strategy("SmartTruncation")
        pipeline.register(ContentType.TEXT, s1)
        pipeline.register(ContentType.TEXT, s2)

        config_store = _make_config_store(None)  # No config yet
        pipeline.pipeline_config_store = config_store

        envelope = ContentEnvelope(
            content="x" * 200,
            content_type=ContentType.TEXT,
            metadata={"source_tool": "new_tool"},
        )
        pipeline.process(envelope)

        # Both should run
        s1.compress.assert_called()
        s2.compress.assert_called()

    def test_full_chain_without_source_tool(self) -> None:
        """Without source_tool in metadata, full chain runs."""
        counter = _make_counter()
        pipeline = CompressionPipeline(counter=counter)

        s1 = _make_strategy("NullFieldElider")
        pipeline.register(ContentType.TEXT, s1)

        config_store = _make_config_store(None)
        pipeline.pipeline_config_store = config_store

        envelope = ContentEnvelope(
            content="x" * 200,
            content_type=ContentType.TEXT,
        )
        pipeline.process(envelope)

        s1.compress.assert_called()

    def test_reeval_runs_full_chain_on_boundary(self) -> None:
        """On re-evaluation boundary, proxy omits disabled_adapters so
        the pipeline runs the full chain. C2 fix: re-eval logic is now
        in the async proxy caller; pipeline just reads metadata."""
        counter = _make_counter()
        pipeline = CompressionPipeline(counter=counter)

        s1 = _make_strategy("NullFieldElider")
        s2 = _make_strategy("SmartTruncation")
        pipeline.register(ContentType.TEXT, s1)
        pipeline.register(ContentType.TEXT, s2)

        # No disabled_adapters in metadata = full chain (re-eval boundary)
        envelope = ContentEnvelope(
            content="x" * 200,
            content_type=ContentType.TEXT,
            metadata={"source_tool": "read_file"},
        )
        pipeline.process(envelope)

        # Both should run
        s1.compress.assert_called()
        s2.compress.assert_called()

    def test_no_config_store_runs_full_chain(self) -> None:
        """Pipeline without config_store attribute runs full chain."""
        counter = _make_counter()
        pipeline = CompressionPipeline(counter=counter)

        s1 = _make_strategy("NullFieldElider")
        pipeline.register(ContentType.TEXT, s1)

        # No pipeline_config_store attribute at all
        envelope = ContentEnvelope(
            content="x" * 200,
            content_type=ContentType.TEXT,
            metadata={"source_tool": "read_file"},
        )
        pipeline.process(envelope)

        s1.compress.assert_called()
