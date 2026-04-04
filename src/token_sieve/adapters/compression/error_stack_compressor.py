"""ErrorStackCompressor -- lossy compression adapter for error stacks.

Deduplicates stack frames, strips library/framework internals,
extracts root cause lines, and appends a summary marker.

Off by default (lossy). Requires explicit ``enabled=True`` opt-in.
"""

from __future__ import annotations

import dataclasses
import re

from token_sieve.adapters.compression.summary_marker import format_summary_marker
from token_sieve.domain.model import ContentEnvelope

# Library path fragments to strip from stack traces
_LIBRARY_MARKERS = (
    "site-packages",
    ".venv",
    "venv/",
    "node_modules",
    ".tox/",
    "/usr/lib/python",
    "/usr/local/lib/python",
)

# Python traceback signals
_PY_TB_START = "Traceback (most recent call last):"
_PY_FILE_RE = re.compile(r'^\s+File "(.+)", line \d+', re.MULTILINE)
_PY_CODE_LINE_RE = re.compile(r"^\s+\S")  # indented code line after File

# JS/TS stack trace signals
_JS_AT_RE = re.compile(r"^\s+at\s+", re.MULTILINE)
_JS_ERROR_RE = re.compile(
    r"^(\w*Error|TypeError|RangeError|SyntaxError|ReferenceError):",
    re.MULTILINE,
)

_MIN_TRACEBACK_SIGNALS = 3  # Decision 11: conservative multi-signal detection


class ErrorStackCompressor:
    """Compress error stack traces by deduplication and library stripping.

    Satisfies CompressionStrategy protocol structurally.
    Lossy adapter: off by default, opt-in via ``enabled=True``.
    """

    def __init__(self, *, enabled: bool = False) -> None:
        self._enabled = enabled

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Return True only if enabled AND content contains stack traces.

        Conservative detection (Decision 11): requires 3+ traceback
        signal lines (Traceback header, File lines, at lines, Error: lines).
        """
        if not self._enabled:
            return False
        content = envelope.content
        signals = 0
        if _PY_TB_START in content:
            signals += 1
        signals += len(_PY_FILE_RE.findall(content))
        signals += len(_JS_AT_RE.findall(content))
        if _JS_ERROR_RE.search(content):
            signals += 1
        return signals >= _MIN_TRACEBACK_SIGNALS

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Compress stack traces: strip library frames, deduplicate, extract root cause."""
        content = envelope.content
        original_lines = content.split("\n")
        original_count = len(original_lines)

        # Try Python traceback compression
        if _PY_TB_START in content:
            compressed = self._compress_python_tracebacks(content)
        else:
            compressed = self._compress_js_stack(content)

        compressed_lines = compressed.strip().split("\n")
        kept_count = len(compressed_lines)

        marker = format_summary_marker(
            adapter_name="ErrorStackCompressor",
            original_count=original_count,
            kept_count=kept_count,
        )
        final_content = compressed.strip() + "\n" + marker

        return dataclasses.replace(envelope, content=final_content)

    def _compress_python_tracebacks(self, content: str) -> str:
        """Compress Python tracebacks: strip library frames, deduplicate."""
        # Split into individual tracebacks
        tracebacks = self._split_python_tracebacks(content)

        if not tracebacks:
            return content

        # Deduplicate identical tracebacks
        unique_tbs: list[tuple[str, int]] = []  # (compressed_tb, count)
        for tb in tracebacks:
            compressed_tb = self._strip_library_frames_python(tb)
            # Check if identical to last unique
            if unique_tbs and self._tb_signature(unique_tbs[-1][0]) == self._tb_signature(compressed_tb):
                unique_tbs[-1] = (unique_tbs[-1][0], unique_tbs[-1][1] + 1)
            else:
                unique_tbs.append((compressed_tb, 1))

        # Reassemble
        parts: list[str] = []
        for tb, count in unique_tbs:
            if count > 1:
                parts.append(f"{tb}\n  [repeated {count} times]")
            else:
                parts.append(tb)

        return "\n\n".join(parts)

    def _split_python_tracebacks(self, content: str) -> list[str]:
        """Split content into individual Python tracebacks."""
        tracebacks: list[str] = []
        current: list[str] = []
        in_traceback = False

        for line in content.split("\n"):
            if line.strip() == _PY_TB_START:
                if current and in_traceback:
                    tracebacks.append("\n".join(current))
                current = [line]
                in_traceback = True
            elif in_traceback:
                current.append(line)
                # Exception line (not indented, not empty) ends the traceback
                if line.strip() and not line.startswith(" ") and line != _PY_TB_START:
                    tracebacks.append("\n".join(current))
                    current = []
                    in_traceback = False
            else:
                # Non-traceback content
                if current:
                    current.append(line)

        if current and in_traceback:
            tracebacks.append("\n".join(current))

        return tracebacks

    def _strip_library_frames_python(self, traceback: str) -> str:
        """Remove library/framework frames from a single Python traceback."""
        lines = traceback.split("\n")
        result: list[str] = []
        skip_next_code_line = False
        stripped_count = 0

        for line in lines:
            file_match = _PY_FILE_RE.match(line)
            if file_match:
                filepath = file_match.group(1)
                if self._is_library_path(filepath):
                    skip_next_code_line = True
                    stripped_count += 1
                    continue
                else:
                    skip_next_code_line = False
                    result.append(line)
            elif skip_next_code_line and _PY_CODE_LINE_RE.match(line):
                # This is the code line following a library File line
                skip_next_code_line = False
                stripped_count += 1
                continue
            else:
                skip_next_code_line = False
                result.append(line)

        if stripped_count > 0:
            # Insert note about stripped frames
            # Find the position after "Traceback" header
            insert_pos = 1 if len(result) > 1 else len(result)
            result.insert(insert_pos, f"  ... [{stripped_count} library frames stripped]")

        return "\n".join(result)

    def _compress_js_stack(self, content: str) -> str:
        """Compress JavaScript/TypeScript stack traces."""
        lines = content.split("\n")
        result: list[str] = []
        stripped_count = 0

        for line in lines:
            if _JS_AT_RE.match(line):
                # Check if it's a library frame
                if any(marker in line for marker in _LIBRARY_MARKERS):
                    stripped_count += 1
                    continue
            result.append(line)

        if stripped_count > 0:
            result.append(f"  ... [{stripped_count} library frames stripped]")

        return "\n".join(result)

    def _tb_signature(self, tb: str) -> str:
        """Create a normalized signature for traceback deduplication."""
        # Remove timestamps and line numbers for comparison
        lines = tb.split("\n")
        sig_lines: list[str] = []
        for line in lines:
            # Skip the "stripped" annotation
            if "library frames stripped" in line:
                continue
            sig_lines.append(line.strip())
        return "\n".join(sig_lines)

    @staticmethod
    def _is_library_path(filepath: str) -> bool:
        """Check if a file path belongs to a library/framework."""
        return any(marker in filepath for marker in _LIBRARY_MARKERS)
