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


def test_ci_matrix_pins_pythonhashseed() -> None:
    """PYTHONHASHSEED must be set on every matrix lane.

    C5 fix: at least 3 lanes must pin PYTHONHASHSEED="0" (deterministic
    iteration order) and exactly 1 lane must set PYTHONHASHSEED="random"
    (surfaces dict-ordering bugs masked by a pinned seed).
    """
    include = _load_matrix_include()
    seeds = [str(e.get("PYTHONHASHSEED", "")) for e in include]
    pinned_zero = [s for s in seeds if s == "0"]
    randomized = [s for s in seeds if s == "random"]
    unset = [s for s in seeds if s == ""]

    assert not unset, (
        f"Every matrix lane must declare PYTHONHASHSEED; unset: {unset!r}"
    )
    assert len(pinned_zero) >= 3, (
        f"Expected at least 3 lanes with PYTHONHASHSEED='0'; got {pinned_zero!r}"
    )
    assert len(randomized) == 1, (
        f"Expected exactly 1 lane with PYTHONHASHSEED='random'; got {randomized!r}"
    )


def test_ci_env_block_exports_pythonhashseed() -> None:
    """The job env: block must export PYTHONHASHSEED from matrix."""
    if not _CI_YML.is_file():
        pytest.fail(f"CI workflow not found at {_CI_YML}")
    data = yaml.safe_load(_CI_YML.read_text())
    jobs = data.get("jobs", {})
    for _name, job in jobs.items():
        env = job.get("env", {}) or {}
        if "PYTHONHASHSEED" in env:
            assert "matrix.PYTHONHASHSEED" in str(env["PYTHONHASHSEED"]), (
                f"Job env.PYTHONHASHSEED must reference matrix.PYTHONHASHSEED; "
                f"got {env['PYTHONHASHSEED']!r}"
            )
            return
    pytest.fail("No job exports PYTHONHASHSEED via its env: block")
