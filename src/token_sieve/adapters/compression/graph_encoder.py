"""GraphAdjacencyEncoder: compact dependency graphs to adjacency notation.

Converts verbose JSON dependency/import graphs into compact adjacency
notation: ``A->B,C; B->D``. Detects graph-like structures via key
heuristics.

Satisfies CompressionStrategy protocol structurally.
"""

from __future__ import annotations

import dataclasses
import json

from token_sieve.adapters.compression._json_utils import (
    JSON_START_RE as _JSON_START_RE,
    try_parse_json,
)
from token_sieve.domain.model import ContentEnvelope

# Keys that signal graph-like content
_GRAPH_KEYS = {"dependencies", "imports", "nodes", "edges", "children", "requires"}


class GraphAdjacencyEncoder:
    """Compact dependency/import graphs from verbose JSON to adjacency notation.

    Satisfies CompressionStrategy protocol structurally.
    """

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Return True if content is JSON with graph-like keys and array values."""
        content = envelope.content.strip()
        if not _JSON_START_RE.match(content):
            return False

        parsed = try_parse_json(content)
        if parsed is None:
            return False

        if not isinstance(parsed, dict):
            return False

        found_keys = set(parsed.keys()) & _GRAPH_KEYS
        if not found_keys:
            return False

        # Check that at least one graph key has array/dict values (actual graph data)
        for key in found_keys:
            value = parsed[key]
            if isinstance(value, dict):
                # dict of node -> neighbors (adjacency list)
                if any(isinstance(v, list) for v in value.values()):
                    return True
            elif isinstance(value, list) and value:
                return True

        return False

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Convert graph JSON to adjacency notation."""
        content = envelope.content.strip()
        parsed = try_parse_json(content)
        if parsed is None:
            return envelope

        if not isinstance(parsed, dict):
            return envelope

        adjacency: dict[str, list[str]] = {}
        _extract_graph(parsed, adjacency)

        # Count nodes and edges
        all_nodes: set[str] = set()
        edge_count = 0
        for node, neighbors in adjacency.items():
            all_nodes.add(node)
            all_nodes.update(neighbors)
            edge_count += len(neighbors)

        node_count = len(all_nodes)

        # Serialize as adjacency notation (sorted for determinism)
        parts: list[str] = []
        for node in sorted(adjacency.keys()):
            neighbors = adjacency[node]
            if neighbors:
                parts.append(f"{node}->{','.join(sorted(neighbors))}")
            else:
                parts.append(node)

        adjacency_str = "; ".join(parts)
        marker = f"# [token-sieve] Graph: {node_count} nodes, {edge_count} edges"

        compressed = f"{marker}\n{adjacency_str}"
        return dataclasses.replace(envelope, content=compressed)


def _extract_graph(
    parsed: dict,
    adjacency: dict[str, list[str]],
) -> None:
    """Extract graph structure from various JSON formats."""
    # Format 1: adjacency list {"dependencies": {"A": ["B", "C"]}}
    for key in ("dependencies", "imports", "children", "requires"):
        if key in parsed and isinstance(parsed[key], dict):
            for node, neighbors in parsed[key].items():
                if isinstance(neighbors, list):
                    adjacency[str(node)] = [str(n) for n in neighbors]

    # Format 2: nodes/edges {"nodes": [...], "edges": [{"from": ..., "to": ...}]}
    if "nodes" in parsed and "edges" in parsed:
        nodes_val = parsed["nodes"]
        edges_val = parsed["edges"]
        if isinstance(nodes_val, list) and isinstance(edges_val, list):
            # Initialize all nodes
            for node in nodes_val:
                node_str = str(node)
                if node_str not in adjacency:
                    adjacency[node_str] = []
            # Add edges
            for edge in edges_val:
                if isinstance(edge, dict):
                    src = str(edge.get("from", edge.get("source", "")))
                    dst = str(edge.get("to", edge.get("target", "")))
                    if src and dst:
                        if src not in adjacency:
                            adjacency[src] = []
                        adjacency[src].append(dst)
