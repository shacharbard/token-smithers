"""Tests for AttentionTracker Protocol — structural subtyping."""

from __future__ import annotations

from typing import Any

import pytest


class TestAttentionTrackerImports:
    """AttentionTracker Protocol is importable."""

    def test_import_attention_tracker(self) -> None:
        from token_sieve.domain.ports_attention import AttentionTracker

        assert AttentionTracker is not None

    def test_protocol_has_record_reference(self) -> None:
        from token_sieve.domain.ports_attention import AttentionTracker

        assert hasattr(AttentionTracker, "record_reference")

    def test_protocol_has_get_score(self) -> None:
        from token_sieve.domain.ports_attention import AttentionTracker

        assert hasattr(AttentionTracker, "get_score")

    def test_protocol_has_get_all_scores(self) -> None:
        from token_sieve.domain.ports_attention import AttentionTracker

        assert hasattr(AttentionTracker, "get_all_scores")


class TestAttentionTrackerStructuralSubtyping:
    """Plain classes satisfying Protocol method signatures are accepted."""

    def test_runtime_checkable(self) -> None:
        """AttentionTracker is @runtime_checkable, supports isinstance()."""
        from token_sieve.domain.attention_score import AttentionScore
        from token_sieve.domain.ports_attention import AttentionTracker

        class MockTracker:
            def record_reference(self, tool_name: str, session_id: str) -> None:
                pass

            def get_score(self, tool_name: str) -> AttentionScore | None:
                return None

            def get_all_scores(self) -> list[AttentionScore]:
                return []

        assert isinstance(MockTracker(), AttentionTracker)

    def test_missing_method_not_instance(self) -> None:
        """Class missing a method does NOT satisfy the Protocol."""
        from token_sieve.domain.ports_attention import AttentionTracker

        class IncompleteTracker:
            def record_reference(self, tool_name: str, session_id: str) -> None:
                pass
            # Missing get_score and get_all_scores

        assert not isinstance(IncompleteTracker(), AttentionTracker)

    def test_mock_tracker_record_and_get(self) -> None:
        """A mock implementation can record and retrieve scores."""
        from token_sieve.domain.attention_score import AttentionScore
        from token_sieve.domain.ports_attention import AttentionTracker

        class SimpleTracker:
            def __init__(self) -> None:
                self._counts: dict[str, int] = {}

            def record_reference(self, tool_name: str, session_id: str) -> None:
                self._counts[tool_name] = self._counts.get(tool_name, 0) + 1

            def get_score(self, tool_name: str) -> AttentionScore | None:
                count = self._counts.get(tool_name)
                if count is None:
                    return None
                return AttentionScore(
                    tool_name=tool_name,
                    reference_count=count,
                    last_referenced=0.0,
                )

            def get_all_scores(self) -> list[AttentionScore]:
                return [
                    AttentionScore(
                        tool_name=name,
                        reference_count=count,
                        last_referenced=0.0,
                    )
                    for name, count in self._counts.items()
                ]

        tracker = SimpleTracker()
        assert isinstance(tracker, AttentionTracker)

        tracker.record_reference("read_file", "s1")
        tracker.record_reference("read_file", "s1")
        score = tracker.get_score("read_file")
        assert score is not None
        assert score.reference_count == 2
        assert tracker.get_score("unknown") is None
        assert len(tracker.get_all_scores()) == 1


class TestAttentionTrackerZeroDeps:
    """ports_attention.py has zero external dependencies."""

    def test_no_external_imports(self) -> None:
        import importlib
        import inspect

        mod = importlib.import_module("token_sieve.domain.ports_attention")
        source = inspect.getsource(mod)
        # Only stdlib and local imports allowed
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                # Allow stdlib and local token_sieve imports
                assert not any(
                    pkg in stripped
                    for pkg in ["pydantic", "mcp", "yaml", "requests", "httpx"]
                ), f"External import found: {stripped}"
