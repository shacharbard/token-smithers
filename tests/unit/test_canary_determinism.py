"""Determinism canary — auto-discovering byte-equality test (D4a layer 3).

This test reads every ``*.txt`` fixture under ``tests/fixtures/canary/`` and
runs it through the production CLI compression pipeline twice. It asserts
the two outputs are byte-equal. A regression in any layer of the pipeline
that introduces non-determinism (timestamp insertion, dict reordering, locale
formatting drift) will produce a byte-level diff and fail the canary.

Adding a new fixture is a one-action operation: drop a file in the directory.
No test edit is required because discovery is via ``glob('*.txt')``.

A second layer — ``test_canary_output_matches_committed_golden_hash`` — hashes
the compressed output and compares against
``tests/fixtures/canary/GOLDEN_HASHES.json``. This catches cross-process /
library-upgrade drift that the same-process byte-equality test cannot.
To intentionally update a golden hash after a pipeline change, regenerate the
JSON with a one-liner and commit with an explanatory message:

    python -c "import json, hashlib, pathlib; \
from token_sieve.cli.main import create_pipeline; \
from token_sieve.domain.model import ContentEnvelope, ContentType; \
d=pathlib.Path('tests/fixtures/canary'); \
out={}; \
[out.update({p.name: hashlib.sha256(create_pipeline()[0].process(ContentEnvelope(content=p.read_text(), content_type=ContentType.TEXT))[0].content.encode()).hexdigest()}) for p in sorted(d.glob('*.txt'))]; \
(d/'GOLDEN_HASHES.json').write_text(json.dumps(out, indent=2, sort_keys=True) + chr(10))"
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from token_sieve.cli.main import create_pipeline
from token_sieve.domain.model import ContentEnvelope, ContentType


_CANARY_DIR = Path(__file__).parent.parent / "fixtures" / "canary"
_FIXTURES = sorted(_CANARY_DIR.glob("*.txt")) if _CANARY_DIR.is_dir() else []
_GOLDEN_HASHES_PATH = _CANARY_DIR / "GOLDEN_HASHES.json"


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


@pytest.mark.parametrize("fixture_path", _FIXTURES, ids=lambda p: p.name)
def test_canary_output_matches_committed_golden_hash(fixture_path: Path) -> None:
    """Compressed output bytes must match the committed golden sha256.

    This is the cross-process / cross-version layer: the same-process test
    cannot catch a library upgrade that deterministically shifts output bytes,
    because both calls live in the same interpreter with the same library
    versions. Committing a golden hash and comparing every CI run against it
    catches that drift the first time it happens, not the first time a user
    hits a cache miss.

    When a hash legitimately changes (e.g., intentional pipeline adjustment),
    regenerate ``GOLDEN_HASHES.json`` using the one-liner in the module
    docstring and commit the new file with a message explaining why.
    """
    assert _GOLDEN_HASHES_PATH.is_file(), (
        f"Golden hashes file missing at {_GOLDEN_HASHES_PATH}. "
        f"See module docstring for the regeneration one-liner."
    )
    golden = json.loads(_GOLDEN_HASHES_PATH.read_text())

    pipeline, _ = create_pipeline()
    env = ContentEnvelope(content=fixture_path.read_text(), content_type=ContentType.TEXT)
    out, _ = pipeline.process(env)
    observed = hashlib.sha256(out.content.encode()).hexdigest()

    expected = golden.get(fixture_path.name)
    assert expected is not None, (
        f"No golden hash recorded for {fixture_path.name}. "
        f"Regenerate {_GOLDEN_HASHES_PATH.name} (see module docstring)."
    )
    assert observed == expected, (
        f"Golden hash mismatch for {fixture_path.name}:\n"
        f"  expected: {expected}\n"
        f"  observed: {observed}\n"
        f"If this change is intentional, regenerate GOLDEN_HASHES.json."
    )
