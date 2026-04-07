"""Sensitive command denylist — D5c Layer 1.

Built-in set of argv-prefix patterns that identify commands which expose
secret material (credentials, keys, tokens). When a command matches, the
compress CLI skips compression entirely and passes stdout through raw.

Matching is done on the *first positional argv chain* (most-specific prefix),
not just the binary name, to avoid false positives (e.g., ``aws s3 ls`` vs
``aws sts get-caller-identity``).
"""
from __future__ import annotations

import shlex

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


def matches(cmd: str) -> bool:
    """Return True if *cmd* matches any built-in sensitive denylist prefix.

    Uses shlex.split to parse the command string into tokens, then checks
    whether any denylist entry is a prefix of that token list.

    Args:
        cmd: A shell command string (may include flags, arguments, pipes, etc.)

    Returns:
        True if the command argv starts with any denylist prefix; False otherwise.
    """
    try:
        argv = shlex.split(cmd)
    except ValueError:
        # Malformed quoting — treat as unknown, do not block
        return False

    if not argv:
        return False

    for prefix in _BUILTIN_DENYLIST:
        n = len(prefix)
        if len(argv) >= n and tuple(argv[:n]) == prefix:
            return True

    return False
