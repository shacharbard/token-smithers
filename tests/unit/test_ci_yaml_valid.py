"""Structural assertions on .github/workflows/ci.yml (D4d matrix shape).

The Phase 09 wave 5 CI matrix must have exactly 4 jobs:
  - linux-3.12-c       (full suite, LC_ALL=C)
  - linux-3.11-c       (full suite, LC_ALL=C)
  - macos-3.12-c       (full suite, LC_ALL=C)
  - linux-3.12-locale  (determinism subset, LC_ALL=de_DE.UTF-8)

These tests load the YAML and walk the strategy.matrix.include list.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_CI_YML = Path(__file__).parent.parent.parent / ".github" / "workflows" / "ci.yml"


def _load_matrix_include() -> list[dict]:
    if not _CI_YML.is_file():
        pytest.fail(f"CI workflow not found at {_CI_YML}")
    data = yaml.safe_load(_CI_YML.read_text())
    jobs = data.get("jobs", {})
    # Find the first job that has a matrix.include list.
    for _name, job in jobs.items():
        strategy = job.get("strategy", {}) or {}
        matrix = strategy.get("matrix", {}) or {}
        include = matrix.get("include")
        if include:
            return include
    pytest.fail("No job with strategy.matrix.include found in ci.yml")
    return []  # pragma: no cover


def test_ci_has_four_matrix_jobs() -> None:
    """The matrix must contain exactly 4 include entries."""
    include = _load_matrix_include()
    assert len(include) == 4, (
        f"Expected 4 matrix jobs, got {len(include)}: {include!r}"
    )


def test_ci_includes_locale_canary() -> None:
    """Exactly one entry must run under LC_ALL=de_DE.UTF-8."""
    include = _load_matrix_include()
    locale_entries = [
        e for e in include if e.get("LC_ALL") == "de_DE.UTF-8"
    ]
    assert len(locale_entries) == 1, (
        f"Expected exactly one de_DE.UTF-8 entry; got {locale_entries!r}"
    )


def test_ci_includes_macos() -> None:
    """At least one entry must run on macOS."""
    include = _load_matrix_include()
    macos = [e for e in include if str(e.get("os", "")).startswith("macos")]
    assert len(macos) >= 1, f"Expected a macOS entry; got {include!r}"


def test_ci_includes_python_3_11_and_3_12() -> None:
    """Both 3.11 and 3.12 must appear in the matrix."""
    include = _load_matrix_include()
    versions = {str(e.get("python")) for e in include}
    assert "3.11" in versions, f"Missing python 3.11; saw {versions}"
    assert "3.12" in versions, f"Missing python 3.12; saw {versions}"
