"""RED tests for M2 — stderr merge allowlist first-word evasion.

The current code compares shlex.split(cmd)[0] literally against the
allowlist {"cargo", "docker", "webpack"}. Bypassed by:
  - KEY=val prefixes: `FOO=bar cargo build`
  - `env` wrapper: `env RUST_LOG=debug cargo build`
  - `sudo` wrapper: `sudo docker ps`
  - absolute paths: `/usr/local/bin/cargo build`
  - relative paths from node_modules: `./node_modules/.bin/webpack`

Fix: strip leading KEY=val / env / sudo tokens, then take os.path.basename
of the first remaining token, then compare against the allowlist.
"""
from __future__ import annotations

import shlex

import pytest

from token_sieve.cli import compress as compress_mod
from token_sieve.cli.compress import run as run_compress


@pytest.fixture(autouse=True)
def _no_bypass_store(monkeypatch):
    monkeypatch.setattr(compress_mod, "_get_bypass_store", lambda: None)


def _patch_shlex_to_return(monkeypatch, tokens: list[str]) -> None:
    """Force shlex.split to return a specific token list, regardless of input."""
    original = shlex.split

    def fake(cmd, *args, **kwargs):
        # Only override the _run_impl first-word determination call, not
        # the hook / test internals. Easiest: override for all calls
        # during the test since test commands use `bash -c '...'`.
        result = original(cmd, *args, **kwargs)
        if result and result[0] == "bash":
            return tokens
        return result

    monkeypatch.setattr(shlex, "split", fake)


class TestAllowlistNormalization:
    """M2: first-word normalization strips prefixes and resolves basenames."""

    def test_env_prefix_still_triggers_allowlist(self, monkeypatch, capsys):
        """`env RUST_LOG=debug cargo build` must merge stderr like `cargo`."""
        _patch_shlex_to_return(
            monkeypatch, ["env", "RUST_LOG=debug", "cargo", "build"]
        )
        monkeypatch.setenv(
            "TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo CARGO_ERR >&2'"
        )

        run_compress([])
        captured = capsys.readouterr()
        # Stderr should be EMPTY (merged into stdout) under the fix.
        assert "CARGO_ERR" not in captured.err, (
            f"env-prefixed cargo should merge stderr; got err={captured.err!r}"
        )

    def test_key_val_prefix_still_triggers_allowlist(self, monkeypatch, capsys):
        """`FOO=bar cargo build` must merge stderr like `cargo`."""
        _patch_shlex_to_return(monkeypatch, ["FOO=bar", "cargo", "build"])
        monkeypatch.setenv(
            "TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo CARGO_ERR >&2'"
        )

        run_compress([])
        captured = capsys.readouterr()
        assert "CARGO_ERR" not in captured.err, (
            f"KEY=val-prefixed cargo should merge stderr; got err={captured.err!r}"
        )

    def test_sudo_prefix_still_triggers_allowlist(self, monkeypatch, capsys):
        """`sudo docker ps` must merge stderr like `docker`."""
        _patch_shlex_to_return(monkeypatch, ["sudo", "docker", "ps"])
        monkeypatch.setenv(
            "TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo DOCKER_ERR >&2'"
        )

        run_compress([])
        captured = capsys.readouterr()
        assert "DOCKER_ERR" not in captured.err, (
            f"sudo-prefixed docker should merge stderr; got err={captured.err!r}"
        )

    def test_absolute_path_still_triggers_allowlist(self, monkeypatch, capsys):
        """`/usr/local/bin/cargo build` must merge stderr like `cargo`."""
        _patch_shlex_to_return(monkeypatch, ["/usr/local/bin/cargo", "build"])
        monkeypatch.setenv(
            "TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo CARGO_ERR >&2'"
        )

        run_compress([])
        captured = capsys.readouterr()
        assert "CARGO_ERR" not in captured.err, (
            f"absolute-path cargo should merge stderr; got err={captured.err!r}"
        )

    def test_relative_node_modules_still_triggers_allowlist(
        self, monkeypatch, capsys
    ):
        """`./node_modules/.bin/webpack build` must merge like `webpack`."""
        _patch_shlex_to_return(
            monkeypatch, ["./node_modules/.bin/webpack", "build"]
        )
        monkeypatch.setenv(
            "TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo WEBPACK_ERR >&2'"
        )

        run_compress([])
        captured = capsys.readouterr()
        assert "WEBPACK_ERR" not in captured.err, (
            f"relative-path webpack should merge stderr; got err={captured.err!r}"
        )

    def test_sudo_env_chain_still_triggers_allowlist(self, monkeypatch, capsys):
        """`sudo env FOO=bar cargo build` must merge stderr like `cargo`."""
        _patch_shlex_to_return(
            monkeypatch, ["sudo", "env", "FOO=bar", "cargo", "build"]
        )
        monkeypatch.setenv(
            "TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo CARGO_ERR >&2'"
        )

        run_compress([])
        captured = capsys.readouterr()
        assert "CARGO_ERR" not in captured.err

    def test_mycargo_still_not_in_allowlist(self, monkeypatch, capsys):
        """Non-allowlisted binary (mycargo) must still pass stderr through raw."""
        _patch_shlex_to_return(monkeypatch, ["mycargo", "build"])
        monkeypatch.setenv(
            "TSIEV_WRAP_CMD", "bash -c 'echo OUT; echo MY_ERR >&2'"
        )

        run_compress([])
        captured = capsys.readouterr()
        assert "MY_ERR" in captured.err, (
            f"mycargo must not match allowlist; got err={captured.err!r}"
        )
