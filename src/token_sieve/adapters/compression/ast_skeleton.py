"""ASTSkeletonExtractor: extract function/class signatures from Python source.

For tool results containing Python source code, returns only function/class
signatures and docstrings, dropping function bodies. Uses stdlib ast.parse().

Satisfies CompressionStrategy protocol structurally.
"""

from __future__ import annotations

import ast
import dataclasses
import re
import textwrap

from token_sieve.domain.model import ContentEnvelope


# Heuristic signals for detecting Python source
_PYTHON_SIGNALS = [
    re.compile(r"^\s*def\s+\w+", re.MULTILINE),
    re.compile(r"^\s*class\s+\w+", re.MULTILINE),
    re.compile(r"^\s*import\s+\w+", re.MULTILINE),
    re.compile(r"^\s*from\s+\w+\s+import\s+", re.MULTILINE),
]

_MIN_SIGNALS = 2  # Need at least 2 Python signals


class ASTSkeletonExtractor:
    """Extract function/class signatures + docstrings from Python source.

    Satisfies CompressionStrategy protocol structurally.
    Python-only; uses stdlib ast.parse(). Falls back to passthrough on
    parse errors.
    """

    deterministic = True

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Detect Python source via heuristics (>=2 signals)."""
        content = envelope.content
        signal_count = sum(
            1 for pattern in _PYTHON_SIGNALS if pattern.search(content)
        )
        return signal_count >= _MIN_SIGNALS

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Parse Python source and extract skeleton."""
        content = envelope.content
        try:
            tree = ast.parse(content)
        except SyntaxError:
            # Graceful fallback: return content unchanged
            return envelope

        lines = content.splitlines()
        line_count = len(lines)

        skeleton_parts: list[str] = []
        _extract_skeleton(tree, skeleton_parts, indent=0)

        if not skeleton_parts:
            return envelope

        marker = (
            f"# [token-sieve] Full source: {line_count} lines, "
            f"skeleton shown"
        )
        skeleton = "\n\n".join(skeleton_parts) + f"\n\n{marker}\n"

        return dataclasses.replace(envelope, content=skeleton)


def _extract_skeleton(
    node: ast.AST,
    parts: list[str],
    indent: int,
) -> None:
    """Recursively extract signatures and docstrings from AST nodes."""
    prefix = "    " * indent

    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            sig = _function_signature(child)
            block = f"{prefix}def {sig}:"
            docstring = ast.get_docstring(child)
            if docstring:
                doc_indent = "    " * (indent + 1)
                block += f'\n{doc_indent}"""{ docstring}"""'
            block += f"\n{prefix}    ..."
            parts.append(block)

        elif isinstance(child, ast.ClassDef):
            bases = ", ".join(
                ast.unparse(b) for b in child.bases
            )
            class_line = f"{prefix}class {child.name}"
            if bases:
                class_line += f"({bases})"
            class_line += ":"

            docstring = ast.get_docstring(child)
            if docstring:
                doc_indent = "    " * (indent + 1)
                class_line += f'\n{doc_indent}"""{docstring}"""'

            parts.append(class_line)
            # Recurse into class body for methods
            _extract_skeleton(child, parts, indent + 1)


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Build function signature string from AST node."""
    args = node.args
    parts: list[str] = []

    # Positional args (may include self/cls)
    num_defaults = len(args.defaults)
    num_args = len(args.args)
    non_default_count = num_args - num_defaults

    for i, arg in enumerate(args.args):
        name = arg.arg
        if i >= non_default_count:
            default = args.defaults[i - non_default_count]
            try:
                default_str = ast.unparse(default)
            except Exception:
                default_str = "..."
            parts.append(f"{name}={default_str}")
        else:
            parts.append(name)

    # *args
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")

    # keyword-only args
    kw_defaults = args.kw_defaults
    for i, arg in enumerate(args.kwonlyargs):
        default = kw_defaults[i]
        if default is not None:
            try:
                default_str = ast.unparse(default)
            except Exception:
                default_str = "..."
            parts.append(f"{arg.arg}={default_str}")
        else:
            parts.append(arg.arg)

    # **kwargs
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")

    return f"{node.name}({', '.join(parts)})"
