"""Tests for D4d: LC_ALL=C scope is surgical (CLI internals only).

The CLI's own Python formatting must use the C locale so that any number
or date formatting that ends up in compressed output is locale-stable.
But the **wrapped user subprocess** must still see the user's original
LANG/LC_ALL — otherwise the user's command would behave differently when
run under token-sieve vs natively.
"""

from __future__ import annotations

import locale
import os

from token_sieve.cli import compress as compress_cli


def test_lc_all_c_set_for_internal_formatting(monkeypatch) -> None:
    """During compress.run(), the Python locale is C.

    We monkeypatch the inner _run_impl so we can observe the active
    locale at the moment the body would execute. After run() returns,
    the prior locale must be restored to avoid polluting other tests.
    """
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.setenv("TSIEV_WRAP_CMD", "true")

    captured: dict[str, str | None] = {}

    def fake_impl(argv):
        captured["during"] = locale.setlocale(locale.LC_ALL)
        return 0

    monkeypatch.setattr(compress_cli, "_run_impl", fake_impl)

    # Try to set a non-C locale before invocation so we can detect the switch.
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    before = locale.setlocale(locale.LC_ALL)

    compress_cli.run([])

    assert captured["during"] in ("C", "POSIX"), (
        f"Expected CLI internals to switch to C locale during run(); "
        f"got {captured['during']!r}"
    )

    # And the prior locale must be restored after run() returns so other
    # in-process callers (e.g., the rest of the pytest session) are not
    # stuck with the C locale and its ASCII default file encoding.
    after = locale.setlocale(locale.LC_ALL)
    assert after == before, (
        f"compress.run() must restore prior locale; before={before!r} after={after!r}"
    )


def test_user_command_locale_NOT_overridden(
    monkeypatch, tmp_path, capsys
) -> None:
    """The wrapped subprocess must inherit the user's original LANG, not C.

    We invoke a sub-shell that prints its $LANG. The compressed stdout
    should contain the user's original LANG value, not 'C'.
    """
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.setenv("TSIEV_WRAP_CMD", 'printf "%s" "$LANG"')

    compress_cli.run([])

    captured = capsys.readouterr()
    # Subprocess saw the user's original LANG, not C.
    assert "de_DE.UTF-8" in captured.out, (
        f"Wrapped subprocess should see user's LANG; got stdout={captured.out!r}"
    )
    assert captured.out.strip() != "C", (
        "Wrapped subprocess must NOT see LANG=C — locale scope leaked"
    )
