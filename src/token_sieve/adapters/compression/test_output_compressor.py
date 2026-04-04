"""Test output compressor — deduplicate pytest/unittest PASSED lines.

Detects test runner output (pytest, unittest) and compresses it by
removing individual PASSED/ok lines while preserving FAILED/ERROR
details and the summary footer.

Satisfies CompressionStrategy protocol structurally.
"""

from __future__ import annotations

import dataclasses
import re

from token_sieve.adapters.compression.summary_marker import format_summary_marker
from token_sieve.domain.model import ContentEnvelope, ContentType

# --- Compiled patterns for test output detection ---

# pytest session header
_PYTEST_HEADER_RE = re.compile(r"={3,}\s*test session starts\s*={3,}")

# pytest individual test result: path::Class::method STATUS
_PYTEST_RESULT_RE = re.compile(
    r"^(.*?::.*?)\s+(PASSED|FAILED|ERROR|XFAIL|XPASS)\s*$"
)

# pytest summary footer: === N passed, M failed in X.XXs ===
_PYTEST_SUMMARY_RE = re.compile(
    r"^={3,}\s*.*(?:passed|failed|error).*\s*={3,}$"
)

# pytest short test summary info header
_PYTEST_SHORT_SUMMARY_RE = re.compile(r"^={3,}\s*short test summary info\s*={3,}$")

# pytest FAILURES/ERRORS section header
_PYTEST_SECTION_RE = re.compile(r"^={3,}\s*(FAILURES|ERRORS)\s*={3,}$")

# unittest result line: test_name (module.Class) ... ok/FAIL/ERROR
_UNITTEST_RESULT_RE = re.compile(
    r"^(\w+)\s+\(.*?\)\s+\.\.\.\s+(ok|FAIL|ERROR)\s*$"
)

# unittest summary: Ran N tests in X.XXXs
_UNITTEST_SUMMARY_RE = re.compile(r"^Ran\s+\d+\s+tests?\s+in\s+")

# unittest FAIL/OK/ERROR final line
_UNITTEST_FINAL_RE = re.compile(r"^(OK|FAILED)\s*(\(.*\))?\s*$")

# Minimum lines with test patterns to consider as test output
_MIN_TEST_LINES = 3


class TestOutputCompressor:
    """Compress test runner output by removing PASSED lines.

    Satisfies CompressionStrategy protocol structurally.
    Keeps: FAILED/ERROR details, tracebacks, summary footer.
    Removes: individual PASSED/ok lines.
    """

    def can_handle(self, envelope: ContentEnvelope) -> bool:
        """Return True when content looks like test runner output."""
        if envelope.content_type not in (ContentType.TEXT, ContentType.CLI_OUTPUT):
            return False
        content = envelope.content
        # Quick check for pytest header
        if _PYTEST_HEADER_RE.search(content):
            return True
        # Count test result pattern matches
        lines = content.split("\n")
        test_line_count = sum(
            1
            for line in lines
            if _PYTEST_RESULT_RE.match(line.strip())
            or _UNITTEST_RESULT_RE.match(line.strip())
        )
        return test_line_count >= _MIN_TEST_LINES

    def compress(self, envelope: ContentEnvelope) -> ContentEnvelope:
        """Compress test output: drop PASSED lines, keep failures + summary."""
        content = envelope.content
        lines = content.split("\n")

        if _PYTEST_HEADER_RE.search(content):
            compressed = self._compress_pytest(lines)
        else:
            compressed = self._compress_unittest(lines)

        return dataclasses.replace(envelope, content=compressed)

    def _compress_pytest(self, lines: list[str]) -> str:
        """Compress pytest-style output."""
        passed_count = 0
        kept_lines: list[str] = []
        in_failure_section = False
        in_short_summary = False

        for line in lines:
            stripped = line.strip()

            # Track section transitions
            if _PYTEST_SECTION_RE.match(stripped):
                in_failure_section = True
                in_short_summary = False
                kept_lines.append(line)
                continue

            if _PYTEST_SHORT_SUMMARY_RE.match(stripped):
                in_short_summary = True
                in_failure_section = False
                kept_lines.append(line)
                continue

            # Summary footer — always keep
            if _PYTEST_SUMMARY_RE.match(stripped):
                in_failure_section = False
                in_short_summary = False
                kept_lines.append(line)
                continue

            # Inside failure/error section — keep everything
            if in_failure_section or in_short_summary:
                kept_lines.append(line)
                continue

            # Individual test result lines
            m = _PYTEST_RESULT_RE.match(stripped)
            if m:
                status = m.group(2)
                if status == "PASSED":
                    passed_count += 1
                    continue  # Drop PASSED lines
                else:
                    kept_lines.append(line)
                    continue

            # Skip session header and collection info for all-pass
            if _PYTEST_HEADER_RE.match(stripped):
                continue
            if stripped.startswith("platform ") or stripped.startswith("collected "):
                continue

            # Keep blank lines only if they're in a meaningful section
            if not stripped and not in_failure_section:
                continue

            kept_lines.append(line)

        # Prepend passed count summary
        result_parts: list[str] = []
        if passed_count > 0:
            result_parts.append(f"{passed_count} tests passed.")
        if kept_lines:
            # Remove leading blank lines
            while kept_lines and not kept_lines[0].strip():
                kept_lines.pop(0)
            result_parts.append("\n".join(kept_lines))

        original_count = len(lines)
        kept_count = len(kept_lines) + (1 if passed_count > 0 else 0)
        marker = format_summary_marker(
            adapter_name="TestOutputCompressor",
            original_count=original_count,
            kept_count=kept_count,
            kept_types="FAILED+ERROR",
        )
        result_parts.append(marker)

        return "\n".join(result_parts)

    def _compress_unittest(self, lines: list[str]) -> str:
        """Compress unittest-style output."""
        passed_count = 0
        kept_lines: list[str] = []
        in_failure_block = False

        for line in lines:
            stripped = line.strip()

            # unittest result lines
            m = _UNITTEST_RESULT_RE.match(stripped)
            if m:
                status = m.group(2)
                if status == "ok":
                    passed_count += 1
                    continue  # Drop ok lines
                else:
                    kept_lines.append(line)
                    continue

            # Track failure blocks (between dashed lines)
            if stripped.startswith("FAIL:") or stripped.startswith("ERROR:"):
                in_failure_block = True
                kept_lines.append(line)
                continue

            if re.match(r"^-{20,}$", stripped):
                if in_failure_block:
                    kept_lines.append(line)
                continue

            # Summary and final lines — always keep
            if _UNITTEST_SUMMARY_RE.match(stripped) or _UNITTEST_FINAL_RE.match(stripped):
                in_failure_block = False
                kept_lines.append(line)
                continue

            # Inside failure block — keep everything
            if in_failure_block:
                kept_lines.append(line)
                continue

            # Separator lines between sections
            if re.match(r"^={20,}$", stripped):
                kept_lines.append(line)
                continue

        # Build result
        result_parts: list[str] = []
        if passed_count > 0:
            result_parts.append(f"{passed_count} tests passed.")
        if kept_lines:
            while kept_lines and not kept_lines[0].strip():
                kept_lines.pop(0)
            result_parts.append("\n".join(kept_lines))

        original_count = len(lines)
        kept_count = len(kept_lines) + (1 if passed_count > 0 else 0)
        marker = format_summary_marker(
            adapter_name="TestOutputCompressor",
            original_count=original_count,
            kept_count=kept_count,
            kept_types="FAILED+ERROR",
        )
        result_parts.append(marker)

        return "\n".join(result_parts)
