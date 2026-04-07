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


def test_lc_all_c_set_for_internal_formatting(monkeypatch, tmp_path) -> None:
    """After compress.run() is invoked, the Python locale is C."""
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    # We don't actually need to run the wrapped command — we only need to
    # verify the locale-setup helper executes when run() is invoked. Use a
    # cheap, deterministic command.
    monkeypatch.setenv("TSIEV_WRAP_CMD", "true")

    # Reset locale to something non-C so we can detect that run() switches it.
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass

    compress_cli.run([])

    current = locale.setlocale(locale.LC_ALL)
    assert current in ("C", "POSIX"), (
        f"Expected CLI internals to switch to C locale; got {current!r}"
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
