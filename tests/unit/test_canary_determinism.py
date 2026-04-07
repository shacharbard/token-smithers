"""Determinism canary — auto-discovering byte-equality test (D4a layer 3).

This test reads every ``*.txt`` fixture under ``tests/fixtures/canary/`` and
runs it through the production CLI compression pipeline twice. It asserts
the two outputs are byte-equal. A regression in any layer of the pipeline
that introduces non-determinism (timestamp insertion, dict reordering, locale
formatting drift) will produce a byte-level diff and fail the canary.

Adding a new fixture is a one-action operation: drop a file in the directory.
No test edit is required because discovery is via ``glob('*.txt')``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from token_sieve.cli.main import create_pipeline
from token_sieve.domain.model import ContentEnvelope, ContentType


_CANARY_DIR = Path(__file__).parent.parent / "fixtures" / "canary"
_FIXTURES = sorted(_CANARY_DIR.glob("*.txt")) if _CANARY_DIR.is_dir() else []


if not _FIXTURES:
    pytest.skip(
        f"No canary fixtures found under {_CANARY_DIR} — drop *.txt files to enable",
        allow_module_level=True,
    )


@pytest.mark.parametrize("fixture_path", _FIXTURES, ids=lambda p: p.name)
def test_canary_byte_equal_across_runs(fixture_path: Path) -> None:
    """Two identical compress() calls must yield byte-identical content."""
    raw = fixture_path.read_text()

    pipeline_a, _ = create_pipeline()
    env_a = ContentEnvelope(content=raw, content_type=ContentType.TEXT)
    out_a, _ = pipeline_a.process(env_a)

    pipeline_b, _ = create_pipeline()
    env_b = ContentEnvelope(content=raw, content_type=ContentType.TEXT)
    out_b, _ = pipeline_b.process(env_b)

    assert out_a.content.encode() == out_b.content.encode(), (
        f"Canary determinism violation for {fixture_path.name}: "
        f"two pipeline runs produced different bytes"
    )
