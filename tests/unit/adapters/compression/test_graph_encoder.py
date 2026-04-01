"""Tests for GraphAdjacencyEncoder.

RED phase: contract tests + specific behavioral tests.
"""

from __future__ import annotations

import json

import pytest

from token_sieve.domain.model import ContentEnvelope, ContentType

from tests.unit.adapters.conftest import CompressionStrategyContract


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_DEPENDENCY_GRAPH = json.dumps({
    "dependencies": {
        "moduleA": ["moduleB", "moduleC"],
        "moduleB": ["moduleD"],
        "moduleC": ["moduleD", "moduleE"],
        "moduleD": ["moduleF"],
    }
})

_NODES_EDGES_GRAPH = json.dumps({
    "nodes": ["A", "B", "C", "D"],
    "edges": [
        {"from": "A", "to": "B"},
        {"from": "A", "to": "C"},
        {"from": "B", "to": "D"},
        {"from": "C", "to": "D"},
    ],
})

_CHILDREN_GRAPH = json.dumps({
    "children": {
        "root": ["child1", "child2"],
        "child1": ["grandchild1"],
        "child2": [],
    }
})

_NON_GRAPH_JSON = json.dumps({
    "name": "test",
    "version": "1.0",
    "settings": {"debug": True, "verbose": False},
})

_EMPTY_GRAPH = json.dumps({"dependencies": {}})

_CYCLIC_GRAPH = json.dumps({
    "dependencies": {
        "A": ["B"],
        "B": ["C"],
        "C": ["A"],
    }
})

_NON_JSON = "This is plain text, not JSON."

_IMPORTS_GRAPH = json.dumps({
    "imports": {
        "app.py": ["os", "sys", "flask"],
        "utils.py": ["os", "pathlib"],
    }
})


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestGraphEncoderContract(CompressionStrategyContract):
    """GraphAdjacencyEncoder must satisfy the CompressionStrategy contract."""

    @pytest.fixture()
    def strategy(self):
        from token_sieve.adapters.compression.graph_encoder import (
            GraphAdjacencyEncoder,
        )

        return GraphAdjacencyEncoder()


# ---------------------------------------------------------------------------
# Specific behavioral tests
# ---------------------------------------------------------------------------


class TestGraphEncoderSpecific:
    """GraphAdjacencyEncoder-specific behavioral tests."""

    def test_can_handle_true_dependencies(self):
        """JSON with 'dependencies' key and array values triggers can_handle."""
        from token_sieve.adapters.compression.graph_encoder import (
            GraphAdjacencyEncoder,
        )

        envelope = ContentEnvelope(
            content=_DEPENDENCY_GRAPH, content_type=ContentType.JSON
        )
        strategy = GraphAdjacencyEncoder()
        assert strategy.can_handle(envelope) is True

    def test_can_handle_true_nodes_edges(self):
        """JSON with 'nodes' and 'edges' keys triggers can_handle."""
        from token_sieve.adapters.compression.graph_encoder import (
            GraphAdjacencyEncoder,
        )

        envelope = ContentEnvelope(
            content=_NODES_EDGES_GRAPH, content_type=ContentType.JSON
        )
        strategy = GraphAdjacencyEncoder()
        assert strategy.can_handle(envelope) is True

    def test_can_handle_true_imports(self):
        """JSON with 'imports' key and array values triggers can_handle."""
        from token_sieve.adapters.compression.graph_encoder import (
            GraphAdjacencyEncoder,
        )

        envelope = ContentEnvelope(
            content=_IMPORTS_GRAPH, content_type=ContentType.JSON
        )
        strategy = GraphAdjacencyEncoder()
        assert strategy.can_handle(envelope) is True

    def test_can_handle_false_non_graph(self):
        """Non-graph JSON returns False."""
        from token_sieve.adapters.compression.graph_encoder import (
            GraphAdjacencyEncoder,
        )

        envelope = ContentEnvelope(
            content=_NON_GRAPH_JSON, content_type=ContentType.JSON
        )
        strategy = GraphAdjacencyEncoder()
        assert strategy.can_handle(envelope) is False

    def test_can_handle_false_non_json(self):
        """Non-JSON content returns False."""
        from token_sieve.adapters.compression.graph_encoder import (
            GraphAdjacencyEncoder,
        )

        envelope = ContentEnvelope(
            content=_NON_JSON, content_type=ContentType.TEXT
        )
        strategy = GraphAdjacencyEncoder()
        assert strategy.can_handle(envelope) is False

    def test_compress_dependency_graph(self):
        """Dependency graph JSON produces adjacency notation."""
        from token_sieve.adapters.compression.graph_encoder import (
            GraphAdjacencyEncoder,
        )

        envelope = ContentEnvelope(
            content=_DEPENDENCY_GRAPH, content_type=ContentType.JSON
        )
        strategy = GraphAdjacencyEncoder()
        result = strategy.compress(envelope)

        # Should contain adjacency notation with arrows
        assert "->" in result.content
        # Should contain marker
        assert "# [token-sieve] Graph:" in result.content
        assert "nodes" in result.content
        assert "edges" in result.content

    def test_compress_nodes_edges_graph(self):
        """Nodes/edges format produces adjacency notation."""
        from token_sieve.adapters.compression.graph_encoder import (
            GraphAdjacencyEncoder,
        )

        envelope = ContentEnvelope(
            content=_NODES_EDGES_GRAPH, content_type=ContentType.JSON
        )
        strategy = GraphAdjacencyEncoder()
        result = strategy.compress(envelope)
        assert "->" in result.content
        assert "# [token-sieve] Graph:" in result.content

    def test_compress_empty_graph(self):
        """Empty dependency graph produces empty adjacency output."""
        from token_sieve.adapters.compression.graph_encoder import (
            GraphAdjacencyEncoder,
        )

        envelope = ContentEnvelope(
            content=_EMPTY_GRAPH, content_type=ContentType.JSON
        )
        strategy = GraphAdjacencyEncoder()
        # Empty graph: can_handle may be False (no array values)
        # or compress returns minimal output
        if strategy.can_handle(envelope):
            result = strategy.compress(envelope)
            assert "# [token-sieve] Graph:" in result.content
            assert "0 nodes" in result.content

    def test_compress_cyclic_graph(self):
        """Cyclic graphs are handled without infinite loops."""
        from token_sieve.adapters.compression.graph_encoder import (
            GraphAdjacencyEncoder,
        )

        envelope = ContentEnvelope(
            content=_CYCLIC_GRAPH, content_type=ContentType.JSON
        )
        strategy = GraphAdjacencyEncoder()
        result = strategy.compress(envelope)
        assert "->" in result.content
        # All 3 nodes should appear
        assert "A" in result.content
        assert "B" in result.content
        assert "C" in result.content

    def test_compress_result_shorter(self):
        """Adjacency notation should be shorter than verbose JSON."""
        from token_sieve.adapters.compression.graph_encoder import (
            GraphAdjacencyEncoder,
        )

        envelope = ContentEnvelope(
            content=_DEPENDENCY_GRAPH, content_type=ContentType.JSON
        )
        strategy = GraphAdjacencyEncoder()
        result = strategy.compress(envelope)
        assert len(result.content) < len(envelope.content)

    def test_compress_preserves_content_type(self):
        """compress() preserves the envelope's content_type."""
        from token_sieve.adapters.compression.graph_encoder import (
            GraphAdjacencyEncoder,
        )

        envelope = ContentEnvelope(
            content=_DEPENDENCY_GRAPH, content_type=ContentType.JSON
        )
        strategy = GraphAdjacencyEncoder()
        result = strategy.compress(envelope)
        assert result.content_type == ContentType.JSON
