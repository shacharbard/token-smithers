"""Sensitive command denylist — D5c Layer 1.

Built-in set of argv-prefix patterns that identify commands which expose
secret material (credentials, keys, tokens). When a command matches, the
compress CLI skips compression entirely and passes stdout through raw.

Matching is done on the *first positional argv chain* (most-specific prefix),
not just the binary name, to avoid false positives (e.g., ``aws s3 ls`` vs
``aws sts get-caller-identity``).
"""
from __future__ import annotations

import os
import re
import shlex

# Regex for a leading environment-variable assignment token like ``FOO=bar``
# or ``AWS_PROFILE=prod``. POSIX allows [A-Za-z_][A-Za-z0-9_]* as the name.
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Wrapper binaries that MUST be stripped (along with their flags) before
# matching against the denylist, because they transparently exec the
# following command.
_WRAPPER_BINARIES = frozenset({"sudo", "env", "doas", "nice", "ionice"})

# Short flags that consume the next token as their VALUE for each wrapper.
# Long flags of the form --name=value are handled automatically.
_WRAPPER_VALUE_FLAGS: dict[str, frozenset[str]] = {
    "sudo": frozenset({"-u", "-U", "-g", "-G", "-h", "-p", "-r", "-t", "-C", "-D"}),
    "doas": frozenset({"-u", "-C"}),
    "env": frozenset({"-C", "-S", "-u"}),
    "nice": frozenset({"-n"}),
    "ionice": frozenset({"-c", "-n", "-p", "-P", "-u"}),
}

# Shell binaries that accept ``-c <cmdline>`` and should be matched
# recursively on the quoted argument.
_SHELL_BINARIES = frozenset({"sh", "bash", "zsh", "dash", "ksh"})

# Each entry is a tuple of argv tokens that must form a prefix of the parsed
# command argv.  Listed from most-specific to least-specific; first match wins.
# Entries are frozen so the constant is truly immutable.
#
# Rationale for each entry:
_BUILTIN_DENYLIST: frozenset[tuple[str, ...]] = frozenset({
    # AWS credential retrieval via STS
    ("aws", "sts"),
    # AWS config credential read
    ("aws", "configure", "get"),
    # GPG decryption of encrypted blobs
    ("gpg", "--decrypt"),
    # GPG private-key listing
    ("gpg", "--list-secret-keys"),
    # pass password-store retrieval
    ("pass", "show"),
    # HashiCorp Vault secret read
    ("vault", "read"),
    # Kubernetes secret retrieval
    ("kubectl", "get", "secret"),
    # 1Password CLI item retrieval
    ("op", "item", "get"),
    # GitHub CLI auth token output
    ("gh", "auth", "token"),
    # SSH agent key listing
    ("ssh-add", "-L"),
    # OpenSSL — key/cert generation, random material, etc.
    ("openssl",),
})


def _strip_leading_env_assignments(argv: list[str]) -> list[str]:
    """Drop leading ``FOO=bar`` tokens that POSIX shells treat as env vars.

    e.g. ``["AWS_PROFILE=prod", "aws", "sts"]`` → ``["aws", "sts"]``.
    """
    i = 0
    while i < len(argv) and _ENV_ASSIGN_RE.match(argv[i]):
        i += 1
    return argv[i:]


def _strip_wrapper(argv: list[str]) -> list[str]:
    """Strip leading ``sudo``/``env``/``doas`` wrapper (and its flags).

    We drop the wrapper binary and any subsequent ``-x``/``--flag`` tokens
    (and ``-x value`` style) until the first non-flag, non-assignment token,
    which is assumed to be the real command.
    """
    if not argv:
        return argv
    head = os.path.basename(argv[0])
    if head not in _WRAPPER_BINARIES:
        return argv

    rest = argv[1:]
    value_flags = _WRAPPER_VALUE_FLAGS.get(head, frozenset())
    i = 0
    # Skip flags and their values. Long flags of the form --name=value are
    # single tokens. Short flags like `-u` (sudo) consume the next token as
    # their value. Env assignments between the wrapper and the target are
    # also stripped (matches `sudo -E FOO=bar cmd` idiom).
    while i < len(rest):
        tok = rest[i]
        if tok.startswith("--"):
            i += 1
            continue
        if tok.startswith("-"):
            if tok in value_flags and i + 1 < len(rest):
                i += 2
            else:
                i += 1
            continue
        if _ENV_ASSIGN_RE.match(tok):
            i += 1
            continue
        break
    return rest[i:]


def _canonicalize_basename(argv: list[str]) -> list[str]:
    """Replace the first token with its basename so absolute paths match."""
    if not argv:
        return argv
    return [os.path.basename(argv[0]), *argv[1:]]


def matches(cmd: str) -> bool:
    """Return True if *cmd* matches any built-in sensitive denylist prefix.

    C3 fix: resistant to common evasions —
    - leading env assignments (``FOO=bar aws sts ...``)
    - ``sudo`` / ``env`` / ``doas`` wrappers
    - absolute paths (``/usr/local/bin/aws``)
    - ``bash -c '...'`` recursive wrapping
    - fail-closed on malformed quoting (was fail-open)

    Args:
        cmd: A shell command string (may include flags, arguments, pipes, etc.)

    Returns:
        True if the command argv (after canonicalization) starts with any
        denylist prefix; False otherwise.
    """
    try:
        argv = shlex.split(cmd)
    except ValueError:
        # C3 fix: fail CLOSED on malformed quoting. An attacker who can
        # confuse the parser should not get a free pass — treat as sensitive
        # and preserve raw output (the CLI's behavior on True is to skip
        # compression, which is the safe default).
        return True

    if not argv:
        return False

    # 1) Strip leading env-assignment tokens: FOO=bar aws sts ...
    argv = _strip_leading_env_assignments(argv)
    if not argv:
        return False

    # 2) Strip sudo/env/doas wrapper if present.
    argv = _strip_wrapper(argv)
    if not argv:
        return False

    # After stripping wrapper, env assignments can appear again
    # (e.g., `sudo -E FOO=bar aws ...`) — strip them one more time.
    argv = _strip_leading_env_assignments(argv)
    if not argv:
        return False

    # 3) bash -c '<cmdline>' recursion.
    head = os.path.basename(argv[0])
    if head in _SHELL_BINARIES:
        # Look for "-c <cmdline>" pattern; bash/sh may have other flags.
        i = 1
        while i < len(argv):
            if argv[i] == "-c" and i + 1 < len(argv):
                return matches(argv[i + 1])
            if argv[i].startswith("-"):
                i += 1
                continue
            break

    # 4) Canonicalize the first token to its basename so absolute paths match.
    argv = _canonicalize_basename(argv)

    for prefix in _BUILTIN_DENYLIST:
        n = len(prefix)
        if len(argv) >= n and tuple(argv[:n]) == prefix:
            return True

    return False
