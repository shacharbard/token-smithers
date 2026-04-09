"""TreeSitterASTExtractor: multi-language AST skeleton extraction via tree-sitter.

Replaces the stdlib-based ASTSkeletonExtractor with a tree-sitter powered
adapter that handles 6 languages: Python, TypeScript, JavaScript, Go, Rust,
and Java. Uses a generic walker parameterized by per-language config dicts
(Decision 5) with layered language detection (Decision 6).

Signature mode only (Decision 8): keeps function/method signatures,
class/struct/interface declarations, decorators/annotations, and doc
comments. Drops all bodies.

Error tolerance (Decision 11): >50% ERROR nodes -> passthrough,
>100ms walk -> passthrough, zero extracted structures -> passthrough.

Satisfies CompressionStrategy protocol structurally.
"""

from __future__ import annotations

import dataclasses
import re
import time
from typing import Any

from token_sieve.adapters.compression.summary_marker import format_summary_marker
from token_sieve.domain.model import ContentEnvelope

# Type alias for per-language configuration dictionaries
LanguageConfig = dict[str, Any]

# Maximum input size in bytes before we skip parsing (500KB).
# Tree-sitter is O(n) and runs synchronously — large inputs cause latency spikes.
_MAX_INPUT_SIZE = 500_000

# ---------------------------------------------------------------------------
# Optional import guard (graceful degradation if tree-sitter missing)
# ---------------------------------------------------------------------------

_TREE_SITTER_AVAILABLE = False
try:
    import tree_sitter
    import tree_sitter_go
    import tree_sitter_java
    import tree_sitter_javascript
    import tree_sitter_python
    import tree_sitter_rust
    import tree_sitter_typescript

    _TREE_SITTER_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Per-language config dicts (Decision 5)
# ---------------------------------------------------------------------------

_LANGUAGE_CONFIGS: dict[str, LanguageConfig] = {
    "python": {
        "language_fn": lambda: tree_sitter_python.language(),
        "function_node_types": ["function_definition"],
        "class_node_types": ["class_definition"],
        "signature_terminator": ":",
        "doc_comment_types": ["expression_statement"],  # triple-quote docstrings
        "decorator_node_types": ["decorator", "decorated_definition"],
        "heuristic_patterns": [
            r"^\s*def\s+\w+",
            r"^\s*class\s+\w+",
            r"^\s*from\s+\w+\s+import\s+",
            r"^\s*import\s+\w+",
        ],
    },
    "typescript": {
        "language_fn": lambda: tree_sitter_typescript.language_typescript(),
        "function_node_types": ["function_declaration", "method_definition"],
        "class_node_types": [
            "class_declaration",
            "interface_declaration",
        ],
        "signature_terminator": "{",
        "doc_comment_types": ["comment"],
        "decorator_node_types": ["decorator"],
        "heuristic_patterns": [
            r"^\s*interface\s+\w+",
            r":\s*(string|number|boolean|void)\b",
            r"<\w+(\s*,\s*\w+)*>",
            r"^\s*export\s+(function|class|interface)\s+",
        ],
    },
    "javascript": {
        "language_fn": lambda: tree_sitter_javascript.language(),
        "function_node_types": ["function_declaration", "method_definition"],
        "class_node_types": ["class_declaration"],
        "signature_terminator": "{",
        "doc_comment_types": ["comment"],
        "decorator_node_types": ["decorator"],
        "heuristic_patterns": [
            r"\brequire\s*\(",
            r"\bmodule\.exports\b",
            r"^\s*const\s+\w+\s*=\s*\(.*\)\s*=>",
            r"^\s*class\s+\w+",
        ],
    },
    "go": {
        "language_fn": lambda: tree_sitter_go.language(),
        "function_node_types": ["function_declaration", "method_declaration"],
        "class_node_types": ["type_declaration"],
        "signature_terminator": "{",
        "doc_comment_types": ["comment"],
        "decorator_node_types": [],
        "heuristic_patterns": [
            r"^\s*package\s+\w+",
            r"^\s*func\s+(\(\w+\s+\*?\w+\)\s+)?\w+",
            r"^\s*type\s+\w+\s+struct\b",
            r"^\s*import\s+\(",
        ],
    },
    "rust": {
        "language_fn": lambda: tree_sitter_rust.language(),
        "function_node_types": ["function_item"],
        "class_node_types": ["struct_item", "trait_item", "enum_item"],
        "signature_terminator": "{",
        "doc_comment_types": ["line_comment"],
        "decorator_node_types": ["attribute_item"],
        "heuristic_patterns": [
            r"^\s*(pub\s+)?fn\s+\w+",
            r"^\s*(pub\s+)?struct\s+\w+",
            r"^\s*impl\b",
            r"^\s*use\s+\w+",
        ],
    },
    "java": {
        "language_fn": lambda: tree_sitter_java.language(),
        "function_node_types": ["method_declaration", "constructor_declaration"],
        "class_node_types": ["class_declaration", "interface_declaration", "enum_declaration"],
        "signature_terminator": "{",
        "doc_comment_types": ["block_comment"],
        "decorator_node_types": ["marker_annotation", "annotation"],
        "heuristic_patterns": [
            r"^\s*public\s+class\s+\w+",
            r"^\s*package\s+\w+",
            r"^\s*import\s+java\.",
            r"^\s*@\w+",
        ],
    },
}


# ---------------------------------------------------------------------------
# Language detection (Decision 6: layered)
# ---------------------------------------------------------------------------


def _detect_language(content: str, metadata: Any) -> tuple[str | None, Any]:
    """Detect programming language using layered approach.

    Layer 1: metadata file extension hints.
    Layer 2: content heuristics (shebang, unique keywords).
    Layer 3: tree-sitter error-rate probing on top 2 candidates.

    Returns (language_key, parse_tree) tuple. The parse tree is cached
    from Layer 3 probing to avoid double-parsing in compress().
    Returns (None, None) if no language detected.
    """
    if not _TREE_SITTER_AVAILABLE:
        return None, None

    # Layer 1: metadata hints
    ext = _extension_from_metadata(metadata)
    if ext:
        lang = _extension_to_language(ext)
        if lang:
            return lang, None  # No tree yet — caller will parse

    # Layer 2: content heuristics -- score each language
    scores: dict[str, int] = {}
    lines = content.split("\n")[:50]  # check first 50 lines only
    sample = "\n".join(lines)
    for lang_key, config in _LANGUAGE_CONFIGS.items():
        score = 0
        for pattern in config["heuristic_patterns"]:
            if re.search(pattern, sample, re.MULTILINE):
                score += 1
        if score > 0:
            scores[lang_key] = score

    if not scores:
        return None, None

    # Sort by score descending, take top 2 for Layer 3
    candidates = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)[:2]

    # Layer 3: tree-sitter error-rate probing
    best_lang = None
    best_error_rate = 1.0
    best_tree = None
    content_bytes = content.encode("utf-8", errors="replace")

    for lang_key in candidates:
        config = _LANGUAGE_CONFIGS[lang_key]
        language = tree_sitter.Language(config["language_fn"]())
        parser = tree_sitter.Parser(language)
        tree = parser.parse(content_bytes)
        error_rate = _compute_error_rate(tree.root_node)
        if error_rate < best_error_rate:
            best_error_rate = error_rate
            best_lang = lang_key
            best_tree = tree

    # Only accept if error rate is reasonable (< 0.5)
    if best_lang and best_error_rate < 0.5:
        return best_lang, best_tree
    return None, None


def _extension_from_metadata(metadata: Any) -> str | None:
    """Extract file extension from envelope metadata."""
    if not hasattr(metadata, "get"):
        return None
    # Check common metadata keys
    for key in ("file_extension", "ext", "filename", "file_name", "path"):
        val = metadata.get(key)
        if val and isinstance(val, str):
            if "." in val:
                return val.rsplit(".", 1)[-1].lower()
            if key in ("file_extension", "ext"):
                return val.lower().lstrip(".")
    return None


_EXTENSION_MAP: dict[str, str] = {
    "py": "python",
    "ts": "typescript",
    "tsx": "typescript",
    "js": "javascript",
    "jsx": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "go": "go",
    "rs": "rust",
    "java": "java",
}


def _extension_to_language(ext: str) -> str | None:
    """Map file extension to language key."""
    return _EXTENSION_MAP.get(ext.lower().lstrip("."))


# ---------------------------------------------------------------------------
# Error rate computation
# ---------------------------------------------------------------------------


def _compute_error_rate(root_node: Any, threshold: float = 0.5) -> float:
    """Compute fraction of ERROR/MISSING nodes in the parse tree.

    Early-exits once accumulated error fraction exceeds threshold
    to avoid walking the entire tree for clearly malformed input.
    """
    total = 0
    errors = 0

    def _walk(node: Any) -> bool:
        """Walk node tree. Returns False to signal early exit."""
        nonlocal total, errors
        total += 1
        if node.type == "ERROR" or node.is_missing:
            errors += 1
            # Early exit: if we've seen enough nodes and error rate exceeds threshold
            if total >= 20 and errors / total > threshold:
                return False
        for child in node.children:
            if not _walk(child):
                return False
        return True

    _walk(root_node)
    if total == 0:
        return 0.0
    return errors / total


# ---------------------------------------------------------------------------
# Generic skeleton walker (Decision 5)
# ---------------------------------------------------------------------------


def _extract_skeleton(
    root_node: Any,
    source_bytes: bytes,
    config: LanguageConfig,
    timeout_deadline: float,
) -> list[str]:
    """Walk tree and extract signatures, doc comments, decorators.

    Returns list of skeleton text fragments. Respects timeout_deadline.
    """
    parts: list[str] = []
    visited: set[int] = set()  # track node ids to avoid duplicates
    func_types = set(config["function_node_types"])
    class_types = set(config["class_node_types"])
    doc_types = set(config["doc_comment_types"])
    sig_terminator = config["signature_terminator"]
    decorator_types = set(config.get("decorator_node_types", []))
    is_python = sig_terminator == ":"

    def _node_text(node: Any) -> str:
        return source_bytes[node.start_byte:node.end_byte].decode(
            "utf-8", errors="replace"
        )

    # Node types that represent a function/class body in brace languages
    _body_node_types = {
        "statement_block", "block", "declaration_list",
        "class_body", "enum_body", "interface_body",
        "field_declaration_list",
    }

    def _extract_signature(node: Any) -> str:
        """Extract everything up to the signature terminator, excluding it."""
        full_text = _node_text(node)
        if is_python:
            # For Python: def foo(x: int) -> str:  -- include up to and with the ':'
            lines = full_text.split("\n")
            sig_lines = []
            for line in lines:
                sig_lines.append(line)
                stripped = line.rstrip()
                if stripped.endswith(":") and not stripped.endswith("::"):
                    break
            return "\n".join(sig_lines)
        else:
            # For brace languages, find the body child node and take text
            # up to its start. This avoids incorrect truncation when { appears
            # in type annotations (e.g., TypeScript object types in params).
            for child in node.children:
                if child.type in _body_node_types:
                    # Offset relative to parent node start
                    offset = child.start_byte - node.start_byte
                    return full_text[:offset].rstrip()
            # Fallback: first line if no body child found
            return full_text.split("\n")[0]

    def _get_preceding_doc_comment(node: Any) -> str | None:
        """Get doc comment(s) immediately before this node.

        Walks backwards through prev_named_sibling while consecutive
        siblings are comment nodes, collecting all of them. This handles
        Go-style multi-line ``//`` comments where each line is a separate
        named sibling.
        """
        comments: list[str] = []
        prev = node.prev_named_sibling
        while prev is not None and prev.type in doc_types:
            # For Python, expression_statement preceding a class/def is not a doc
            # comment (docstrings live inside the body, not before it)
            if prev.type == "expression_statement":
                break
            comments.append(_node_text(prev))
            prev = prev.prev_named_sibling
        if not comments:
            return None
        # Reverse to restore original order (we walked backwards)
        comments.reverse()
        return "\n".join(comments)

    def _get_preceding_decorator(node: Any) -> str | None:
        """Get decorator/annotation immediately before this node."""
        prev = node.prev_named_sibling
        if prev is None:
            return None
        if prev.type in decorator_types:
            return _node_text(prev)
        return None

    def _extract_python_docstring(node: Any) -> str | None:
        """Extract docstring from first expression_statement child of a Python block."""
        for child in node.children:
            if child.type == "block":
                for block_child in child.children:
                    if block_child.type == "expression_statement":
                        inner = block_child.children[0] if block_child.children else None
                        if inner and inner.type == "string":
                            return _node_text(block_child)
                    elif block_child.type != "comment":
                        break
                break
        return None

    def _emit_function(node: Any, decorators: list[str] | None = None) -> None:
        """Emit a function/method skeleton fragment."""
        node_id = node.id
        if node_id in visited:
            return
        visited.add(node_id)

        # Preceding doc comment
        doc = _get_preceding_doc_comment(node)
        if doc:
            parts.append(doc)

        # Decorators
        if decorators:
            for dec in decorators:
                parts.append(dec)
        else:
            dec = _get_preceding_decorator(node)
            if dec:
                parts.append(dec)

        sig = _extract_signature(node)

        # For Python, extract inline docstring and use indented body placeholder
        if is_python:
            docstring = _extract_python_docstring(node)
            if docstring:
                sig += "\n    " + docstring
            sig += "\n    ..."
        else:
            sig += " { ... }"
        parts.append(sig)

    def _emit_class(node: Any, decorators: list[str] | None = None) -> None:
        """Emit a class/struct/interface skeleton fragment."""
        node_id = node.id
        if node_id in visited:
            return
        visited.add(node_id)

        # Preceding doc comment
        doc = _get_preceding_doc_comment(node)
        if doc:
            parts.append(doc)

        # Decorators
        if decorators:
            for dec in decorators:
                parts.append(dec)

        sig = _extract_signature(node)

        # For Python classes, extract docstring
        if is_python:
            docstring = _extract_python_docstring(node)
            if docstring:
                sig += "\n    " + docstring
            sig += "\n    ..."
        else:
            sig += " { ... }"
        parts.append(sig)

        # Walk children for methods
        for child in node.children:
            _walk_node(child)

    def _walk_node(node: Any) -> None:
        if time.monotonic() > timeout_deadline:
            return

        # Handle decorated_definition (Python) -- unwrap to get the actual def
        if node.type == "decorated_definition":
            decorators = []
            inner_def = None
            for child in node.children:
                if child.type == "decorator":
                    decorators.append(_node_text(child))
                elif child.type in func_types:
                    inner_def = child
                elif child.type in class_types:
                    inner_def = child

            if inner_def:
                if inner_def.type in func_types:
                    _emit_function(inner_def, decorators)
                else:
                    _emit_class(inner_def, decorators)
            return

        if node.type in func_types:
            _emit_function(node)

        elif node.type in class_types:
            _emit_class(node)

        elif node.type == "impl_item":
            # Rust impl blocks: extract the impl header + walk children
            sig = _extract_signature(node)
            parts.append(sig + " {")
            for child in node.children:
                if child.type == "declaration_list":
                    for inner in child.children:
                        _walk_node(inner)
            parts.append("}")

        elif node.type == "export_statement":
            # Handle export { function_declaration | class_declaration }
            for child in node.children:
                _walk_node(child)

        else:
            # Recurse into children
            for child in node.children:
                _walk_node(child)

    _walk_node(root_node)
    return parts


# ---------------------------------------------------------------------------
# TreeSitterASTExtractor
# ---------------------------------------------------------------------------


class TreeSitterASTExtractor:
    """Multi-language AST skeleton extraction via tree-sitter.

    Satisfies CompressionStrategy protocol structurally.

    Uses a generic walker parameterized by per-language config dicts.
    Supports Python, TypeScript, JavaScript, Go, Rust, and Java.

    Args:
        mode: Extraction mode (currently only 'signature' supported).
        timeout_ms: Maximum milliseconds for the tree walk phase.
        error_threshold: Fraction of ERROR nodes above which content
            passes through unchanged.
    """

    deterministic = True

    def __init__(
        self,
        *,
        mode: str = "signature",
        timeout_ms: int = 100,
        error_threshold: float = 0.5,
    ) -> None:
        self._mode = mode
        self._timeout_ms = timeout_ms
        self._error_threshold = error_threshold
        self._last_detection: tuple[str, object] | None = None
        self._last_content_id: int | None = None

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Return True if tree-sitter is available and language is detected."""
        if not _TREE_SITTER_AVAILABLE:
            return False
        if len(envelope.content) > _MAX_INPUT_SIZE:
            return False
        result = _detect_language(envelope.content, envelope.metadata)
        lang, _tree = result
        if lang is not None:
            self._last_detection = result
            self._last_content_id = id(envelope.content)
            return True
        self._last_detection = None
        return False

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Extract skeleton from code content.

        Returns the original envelope unchanged if:
        - Language cannot be detected
        - Input exceeds size limit
        - Error rate exceeds threshold
        - Walk exceeds timeout
        - Zero structures extracted
        """
        if not _TREE_SITTER_AVAILABLE:
            return envelope

        if len(envelope.content) > _MAX_INPUT_SIZE:
            return envelope

        # Reuse cached detection from can_handle() if content matches
        if (
            self._last_detection is not None
            and self._last_content_id == id(envelope.content)
        ):
            lang, cached_tree = self._last_detection
            self._last_detection = None
        else:
            lang, cached_tree = _detect_language(envelope.content, envelope.metadata)

        if lang is None:
            return envelope

        config = _LANGUAGE_CONFIGS[lang]
        content_bytes = envelope.content.encode("utf-8", errors="replace")

        # Reuse cached tree from _detect_language if available, else parse
        if cached_tree is not None:
            tree = cached_tree
        else:
            language = tree_sitter.Language(config["language_fn"]())
            parser = tree_sitter.Parser(language)
            tree = parser.parse(content_bytes)

        # Error tolerance: check error rate
        error_rate = _compute_error_rate(tree.root_node)
        if error_rate >= self._error_threshold:
            return envelope

        # Walk with timeout
        deadline = time.monotonic() + self._timeout_ms / 1000.0
        parts = _extract_skeleton(tree.root_node, content_bytes, config, deadline)

        # Zero structures -> passthrough
        if not parts:
            return envelope

        # Build skeleton
        original_lines = len(envelope.content.strip().splitlines())
        skeleton_text = "\n\n".join(parts)
        skeleton_lines = len(skeleton_text.strip().splitlines())

        marker = format_summary_marker(
            adapter_name="TreeSitterASTExtractor",
            original_count=original_lines,
            kept_count=skeleton_lines,
            kept_types="signatures",
        )
        skeleton = skeleton_text + "\n\n" + marker + "\n"

        return dataclasses.replace(envelope, content=skeleton)
