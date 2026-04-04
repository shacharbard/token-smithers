"""Smoke test: tree-sitter packages from [ast] extra are importable."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "tree_sitter",
        "tree_sitter_python",
        "tree_sitter_javascript",
        "tree_sitter_typescript",
        "tree_sitter_go",
        "tree_sitter_rust",
        "tree_sitter_java",
    ],
)
def test_ast_extra_importable(module_name: str) -> None:
    """Each tree-sitter grammar package declared in [ast] extra must be importable."""
    mod = importlib.import_module(module_name)
    assert mod is not None
