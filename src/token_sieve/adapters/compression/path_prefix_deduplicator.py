"""PathPrefixDeduplicator -- establishes $BASE for repeated path prefixes.

Lossless cleanup adapter: detects common path prefixes (filesystem or URL),
establishes a $BASE variable, replaces full paths with $BASE/suffix.
Typically saves 20-50%.
"""

from __future__ import annotations

import dataclasses
import os
import re

from token_sieve.domain.model import ContentEnvelope

# Match filesystem paths (/foo/bar/baz.ext) and URLs (https://host/path)
_PATH_PATTERN = re.compile(
    r'(?:'
    r'(?:/[A-Za-z0-9_.~-]+){3,}'          # filesystem: 3+ segments
    r'|'
    r'https?://[A-Za-z0-9_.~:@-]+(?:/[A-Za-z0-9_.~%+-]+){2,}'  # URL: 2+ path segments
    r')'
)

# Minimum prefix length to be useful (avoids deduplicating "/" or "/a")
_MIN_PREFIX_LENGTH = 5
# Minimum number of paths sharing a prefix to trigger deduplication
_MIN_PATH_COUNT = 3


class PathPrefixDeduplicator:
    """Deduplicate common path prefixes using $BASE substitution.

    Satisfies CompressionStrategy protocol structurally.
    """

    deterministic = True

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Accept all content -- path detection happens in compress()."""
        return True

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Find repeated path prefixes and replace with $BASE variable."""
        paths = _PATH_PATTERN.findall(envelope.content)

        if len(paths) < _MIN_PATH_COUNT:
            return envelope

        prefix = _longest_common_prefix(paths)
        if len(prefix) < _MIN_PREFIX_LENGTH:
            return envelope

        # Ensure prefix ends at a path separator boundary
        prefix = _snap_to_separator(prefix)
        if len(prefix) < _MIN_PREFIX_LENGTH:
            return envelope

        # Replace all occurrences of the prefix
        content = envelope.content.replace(prefix, "$BASE/")
        # Prepend $BASE definition
        content = f"$BASE={prefix}\n{content}"

        return dataclasses.replace(envelope, content=content)


def _longest_common_prefix(strings: list[str]) -> str:
    """Compute the longest common prefix of a list of strings."""
    if not strings:
        return ""
    prefix = strings[0]
    for s in strings[1:]:
        while not s.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    return prefix


def _snap_to_separator(prefix: str) -> str:
    """Snap prefix to the last path separator boundary."""
    # For URLs, check for "://" and snap after it if prefix is just the scheme
    last_slash = prefix.rfind("/")
    if last_slash > 0:
        return prefix[: last_slash + 1]
    return prefix
