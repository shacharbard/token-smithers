"""Tests for Phase 07 proxy hooks: adapter registry + pipeline wiring.

Verifies:
- test_output_compressor and bm25_sentence_selector exist in _ADAPTER_REGISTRY
- Default adapter ordering includes both new adapters in correct positions
- TestOutputCompressor strips PASSED lines from pytest output in pipeline
"""
from __future__ import annotations

import pytest

from token_sieve.server.proxy import ProxyServer


class TestAdapterRegistryPhase07:
    """Phase 07 adapters are in the adapter registry."""

    def test_test_output_compressor_in_registry(self) -> None:
        assert "test_output_compressor" in ProxyServer._ADAPTER_REGISTRY

    def test_bm25_sentence_selector_in_registry(self) -> None:
        assert "bm25_sentence_selector" in ProxyServer._ADAPTER_REGISTRY


class TestDefaultAdapterOrderPhase07:
    """Default adapter ordering includes Phase 07 adapters correctly."""

    def test_test_output_compressor_in_defaults(self) -> None:
        from token_sieve.config.schema import _default_adapters

        names = [a.name for a in _default_adapters()]
        assert "test_output_compressor" in names

    def test_bm25_sentence_selector_in_defaults(self) -> None:
        from token_sieve.config.schema import _default_adapters

        names = [a.name for a in _default_adapters()]
        assert "bm25_sentence_selector" in names

    def test_test_output_compressor_before_progressive_disclosure(self) -> None:
        """test_output_compressor fires before progressive_disclosure."""
        from token_sieve.config.schema import _default_adapters

        names = [a.name for a in _default_adapters()]
        toc_idx = names.index("test_output_compressor")
        pd_idx = names.index("progressive_disclosure")
        assert toc_idx < pd_idx, (
            f"test_output_compressor (idx={toc_idx}) must come before "
            f"progressive_disclosure (idx={pd_idx})"
        )

    def test_bm25_sentence_selector_after_sentence_scorer(self) -> None:
        """bm25_sentence_selector appears after sentence_scorer."""
        from token_sieve.config.schema import _default_adapters

        names = [a.name for a in _default_adapters()]
        bm25_idx = names.index("bm25_sentence_selector")
        scorer_idx = names.index("sentence_scorer")
        assert bm25_idx > scorer_idx, (
            f"bm25_sentence_selector (idx={bm25_idx}) must come after "
            f"sentence_scorer (idx={scorer_idx})"
        )


class TestTestOutputCompressorInPipeline:
    """TestOutputCompressor strips PASSED lines from pytest output."""

    def test_test_output_compressor_in_pipeline(self) -> None:
        """Mock pytest output through pipeline, verify PASSED lines stripped."""
        from token_sieve.config.schema import TokenSieveConfig
        from token_sieve.domain.model import ContentEnvelope, ContentType

        config = TokenSieveConfig(
            compression={
                "size_gate_threshold": 0,
                "adapters": [
                    {"name": "test_output_compressor"},
                ],
            }
        )
        proxy = ProxyServer.create_from_config(config)

        pytest_output = (
            "============================= test session starts "
            "=============================\n"
            "collected 5 items\n"
            "\n"
            "tests/test_a.py::test_one PASSED\n"
            "tests/test_a.py::test_two PASSED\n"
            "tests/test_a.py::test_three PASSED\n"
            "tests/test_b.py::test_four FAILED\n"
            "\n"
            "=========================== short test summary info "
            "============================\n"
            "FAILED tests/test_b.py::test_four - AssertionError: 1 != 2\n"
            "========================= 1 failed, 3 passed in 0.5s "
            "==========================\n"
        )

        envelope = ContentEnvelope(
            content=pytest_output,
            content_type=ContentType.TEXT,
            metadata={"source_tool": "Bash"},
        )

        result, events = proxy._pipeline.process(envelope)

        # PASSED lines should be removed
        assert "PASSED" not in result.content
        # FAILED lines and summary should be preserved
        assert "FAILED" in result.content
        assert "1 failed" in result.content
