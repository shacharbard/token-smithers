"""Tests for D4d + H1: locale handling is via subprocess env, never parent.

H1 supersedes the prior batch-4 D4d decision. The rationale is:
  1. Mutating the process-global locale is not thread-safe and forces
     getpreferredencoding() to ASCII, crashing subprocess.run(text=True)
     on any non-ASCII child output.
  2. The original goal of "deterministic child formatting" is still met by
     passing LC_ALL=C / LANG=C via the subprocess env kwarg, which is
     thread-safe and does not affect the parent.

The previous test here asserted that the child saw the user's LANG intact.
Under H1 that is inverted: the child MUST see LC_ALL=C / LANG=C so
wrapped tools produce locale-stable output that compresses deterministically.
"""

from __future__ import annotations

import locale

import pytest

from token_sieve.cli import compress as compress_cli


@pytest.fixture(autouse=True)
def _no_bypass_store(monkeypatch):
    monkeypatch.setattr(compress_cli, "_get_bypass_store", lambda: None)


def test_parent_locale_is_not_mutated(monkeypatch) -> None:
    """compress.run() must not mutate the parent process locale (H1).

    The previous version of this test asserted the opposite (that the
    parent got switched to C). Under H1 that behavior is a bug — locale
    mutation is not thread-safe and breaks UTF-8 decoding of child output.
    """
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.setenv("TSIEV_WRAP_CMD", "true")

    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    before = locale.setlocale(locale.LC_ALL)

    compress_cli.run([])

    after = locale.setlocale(locale.LC_ALL)
    assert after == before, (
        f"compress.run() must not mutate parent locale; before={before!r} after={after!r}"
    )


def test_wrapped_subprocess_sees_lc_all_c(monkeypatch, capsys) -> None:
    """The wrapped subprocess MUST see LC_ALL=C / LANG=C (H1).

    Previously, batch 4 asserted the wrapped subprocess should inherit the
    user's LANG. H1 inverts this: deterministic child formatting is the
    whole point of injecting LC_ALL=C, and it must be done via the env
    kwarg (thread-safe) rather than via mutating the parent locale.
    """
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.setenv("TSIEV_WRAP_CMD", 'printf "%s|%s" "$LC_ALL" "$LANG"')

    compress_cli.run([])

    captured = capsys.readouterr()
    assert "C|C" in captured.out, (
        f"Wrapped subprocess must see LC_ALL=C and LANG=C; got stdout={captured.out!r}"
    )
