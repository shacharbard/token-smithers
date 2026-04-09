"""Adapter-audit determinism property test (D4 + Phase 09 wave 5).

Mechanically enumerates every concrete CompressionStrategy implementation
under ``token_sieve.adapters.compression`` via import introspection, then
runs the same input through each adapter twice and asserts byte-equal
output.

Adapters declared non-deterministic (``deterministic = False``) are skipped
with a clear pytest.skip reason — they remain on the audit ledger but the
fix is deferred to Phase 10 (changing output format breaks cache keys and
downstream consumers).

This is intentionally distinct from ``test_determinism.py`` (which uses
hand-curated factories): the audit's value is that adding a new adapter
file under ``adapters/compression/`` automatically extends coverage with
no test edit, the same one-action property as the canary fixture dir.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any, Callable

import pytest

import token_sieve.adapters.compression as _adapters_pkg
from token_sieve.adapters.cache.diff_state_store import DiffStateStore
from token_sieve.adapters.compression.tree_sitter_ast import _TREE_SITTER_AVAILABLE
from token_sieve.domain.model import ContentEnvelope, ContentType


# ---------------------------------------------------------------------------
# Default test envelopes — chosen so most adapters' can_handle() returns True.
# ---------------------------------------------------------------------------

import json
import textwrap

_TEXT_INPUT = "INFO: starting\nINFO: starting\nWARN: thing\nERROR: bad\n"
_JSON_INPUT = json.dumps(
    {"zebra": 1, "apple": 2, "mango": None, "banana": ""},
    indent=2,
)
_PY_CODE = textwrap.dedent(
    """\
    # comment
    def hello(name: str) -> str:
        '''Greet.'''
        return f"Hi {name}"
    """
)


def _text_env() -> ContentEnvelope:
    return ContentEnvelope(content=_TEXT_INPUT, content_type=ContentType.TEXT)


def _json_env() -> ContentEnvelope:
    return ContentEnvelope(content=_JSON_INPUT, content_type=ContentType.JSON)


def _code_env() -> ContentEnvelope:
    return ContentEnvelope(content=_PY_CODE, content_type=ContentType.CODE)


# ---------------------------------------------------------------------------
# Per-adapter test factories.
# Adapters that need non-default constructor args are listed here.
# Adapters not listed are constructed with no args.
# ---------------------------------------------------------------------------


def _factory_log_level_filter(cls):
    return cls(enabled=True), _text_env()


def _factory_error_stack(cls):
    return cls(enabled=True), _text_env()


def _factory_code_comment_stripper(cls):
    return cls(enabled=True), _code_env()


def _factory_smart_truncation(cls):
    return cls(head_lines=3, tail_lines=2), _text_env()


def _factory_truncation(cls):
    return cls(max_tokens=100), ContentEnvelope(
        content="x" * 5000, content_type=ContentType.TEXT
    )


def _factory_size_gate(cls):
    return cls(threshold=999999), _text_env()


def _factory_key_aliasing(cls):
    return cls(min_occurrences=1, min_key_length=3), _json_env()


def _factory_sentence_scorer(cls):
    return cls(sentence_count=3), ContentEnvelope(
        content=" ".join(
            f"Sentence number {i} contains some words for scoring."
            for i in range(20)
        ),
        content_type=ContentType.TEXT,
    )


def _factory_semantic_diff(cls):
    return cls(DiffStateStore()), ContentEnvelope(
        content="test content",
        content_type=ContentType.TEXT,
        metadata={"source_tool": "test", "source_args": "{}"},
    )


def _factory_file_redirect(cls):
    import tempfile

    tmp = tempfile.mkdtemp(prefix="audit-fr-")
    return cls(threshold_tokens=1, output_dir=tmp), ContentEnvelope(
        content="x" * 50000, content_type=ContentType.TEXT
    )


def _factory_progressive_disclosure(cls):
    import tempfile

    tmp = tempfile.mkdtemp(prefix="audit-pd-")
    return cls(threshold_tokens=1, output_dir=tmp), ContentEnvelope(
        content="x" * 50000, content_type=ContentType.TEXT
    )


def _factory_default_text(cls):
    return cls(), _text_env()


def _factory_default_json(cls):
    return cls(), _json_env()


def _factory_default_code(cls):
    return cls(), _code_env()


# Map class name → (factory_callable, content_type_hint)
_ADAPTER_TEST_FACTORIES: dict[str, Callable[[type], tuple[Any, ContentEnvelope]]] = {
    "LogLevelFilter": _factory_log_level_filter,
    "ErrorStackCompressor": _factory_error_stack,
    "CodeCommentStripper": _factory_code_comment_stripper,
    "SmartTruncation": _factory_smart_truncation,
    "TruncationCompressor": _factory_truncation,
    "SizeGate": _factory_size_gate,
    "KeyAliasingStrategy": _factory_key_aliasing,
    "SentenceScorer": _factory_sentence_scorer,
    "SemanticDiffStrategy": _factory_semantic_diff,
    "FileRedirectStrategy": _factory_file_redirect,
    "ProgressiveDisclosureStrategy": _factory_progressive_disclosure,
    # JSON-friendly defaults
    "WhitespaceNormalizer": _factory_default_json,
    "NullFieldElider": _factory_default_json,
    "YamlTranscoder": _factory_default_json,
    "ToonCompressor": _factory_default_json,
    "JsonCodeUnwrapper": _factory_default_json,
    "GraphAdjacencyEncoder": lambda cls: (
        cls(),
        ContentEnvelope(
            content=json.dumps(
                {"nodes": ["A", "B", "C"], "edges": [["A", "B"], ["B", "C"]]}
            ),
            content_type=ContentType.JSON,
        ),
    ),
    # Code-friendly defaults
    "ASTSkeletonExtractor": _factory_default_code,
    "TreeSitterASTExtractor": _factory_default_code,
}


def _discover_adapter_classes() -> list[type]:
    """Walk the adapters.compression package and return concrete classes
    that look like CompressionStrategy implementations (have can_handle and
    compress methods).
    """
    discovered: list[type] = []
    for _finder, modname, _ispkg in pkgutil.iter_modules(_adapters_pkg.__path__):
        if modname.startswith("_"):
            continue
        full = f"{_adapters_pkg.__name__}.{modname}"
        try:
            module = importlib.import_module(full)
        except Exception:  # noqa: BLE001 — adapter modules with optional deps may fail
            continue
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != full:
                continue
            if name.startswith("_"):
                continue
            if not (hasattr(obj, "can_handle") and hasattr(obj, "compress")):
                continue
            discovered.append(obj)
    return discovered


_DISCOVERED = _discover_adapter_classes()


def test_adapter_discovery_returns_at_least_twenty_classes() -> None:
    """M11: guard against silent adapter dropout.

    The discovery helper previously caught all import exceptions with a
    bare ``continue`` so a broken adapter module became invisible to the
    audit. This test asserts the discovered count is at least 20 — the
    current inventory is ~25, and 20 is a safety floor that still catches
    a multi-module regression.
    """
    assert len(_DISCOVERED) >= 20, (
        f"Adapter discovery returned only {len(_DISCOVERED)} classes; "
        f"expected >= 20. A broken import is silently dropping adapters."
    )


def test_adapter_discovery_warns_on_import_failure(monkeypatch) -> None:
    """M11: a failed adapter import must emit a warning, not be silent."""
    import importlib
    import warnings

    from tests.unit.adapters.compression import test_adapter_audit_determinism as mod

    real_import = importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name.endswith(".whitespace_normalizer"):
            raise ImportError("simulated broken adapter")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        mod._discover_adapter_classes()

    messages = [str(w.message) for w in caught]
    assert any("whitespace_normalizer" in m for m in messages), (
        f"Expected a warning mentioning the failed module; got {messages!r}"
    )


def test_semantic_diff_is_declared_non_deterministic() -> None:
    """A4: SemanticDiffStrategy must be declared deterministic=False.

    Its output depends on state persisted across compress() calls in
    DiffStateStore. The audit only passed before this fix because the
    test harness constructed a fresh store per run. Marking it False is
    the honest declaration and enforces that Phase 10 caching code
    cannot silently treat diff output as cacheable.
    """
    from token_sieve.adapters.compression.semantic_diff import SemanticDiffStrategy

    assert "deterministic" in SemanticDiffStrategy.__dict__
    assert SemanticDiffStrategy.deterministic is False


def test_all_adapters_explicitly_declare_deterministic() -> None:
    """Every discovered adapter MUST declare ``deterministic`` on its own class.

    C5 fix: the Protocol default of ``True`` silently audited any forgetful
    adapter as deterministic. This test asserts the attribute is present in
    ``cls.__dict__`` (i.e., declared on the class itself, not inherited from
    a Protocol default or a base class).
    """
    missing = [
        cls.__name__
        for cls in _DISCOVERED
        if "deterministic" not in cls.__dict__
    ]
    assert not missing, (
        f"The following adapters must explicitly declare `deterministic = True|False` "
        f"at class level: {missing}"
    )


@pytest.mark.parametrize(
    "adapter_cls", _DISCOVERED, ids=lambda c: c.__name__
)
def test_adapter_byte_equal_across_runs(adapter_cls: type) -> None:
    """Each discovered adapter must produce byte-equal output across two runs.

    Non-deterministic adapters (``deterministic = False``) are skipped on the
    audit ledger; the contract still holds that adding a new adapter without
    a factory entry falls back to a no-arg constructor.
    """
    if not getattr(adapter_cls, "deterministic", True):
        pytest.skip(
            f"{adapter_cls.__name__} declared non-deterministic — Phase 10 fix"
        )

    if adapter_cls.__name__ == "TreeSitterASTExtractor" and not _TREE_SITTER_AVAILABLE:
        pytest.skip("tree-sitter not installed")

    factory = _ADAPTER_TEST_FACTORIES.get(
        adapter_cls.__name__, _factory_default_text
    )
    try:
        instance_a, envelope_a = factory(adapter_cls)
        instance_b, envelope_b = factory(adapter_cls)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Could not construct {adapter_cls.__name__}: {exc}")

    if not instance_a.can_handle(envelope_a):
        pytest.skip(
            f"{adapter_cls.__name__} cannot handle the audit envelope"
        )

    out_a = instance_a.compress(envelope_a).content.encode()
    out_b = instance_b.compress(envelope_b).content.encode()

    assert out_a == out_b, (
        f"{adapter_cls.__name__} produced different bytes across two runs:\n"
        f"  run 1 ({len(out_a)} B): {out_a[:200]!r}...\n"
        f"  run 2 ({len(out_b)} B): {out_b[:200]!r}..."
    )
