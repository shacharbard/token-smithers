"""Tests for TestOutputCompressor adapter."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from token_sieve.domain.model import ContentEnvelope, ContentType

# --- Test Fixtures (inline pytest output) ---

_PYTEST_MIXED = """\
============================= test session starts ==============================
platform darwin -- Python 3.14.0, pytest-8.3.4
collected 5 items

tests/unit/test_foo.py::test_add PASSED
tests/unit/test_foo.py::test_subtract PASSED
tests/unit/test_foo.py::test_multiply FAILED
tests/unit/test_foo.py::test_divide PASSED
tests/unit/test_bar.py::test_greet PASSED

=================================== FAILURES ===================================
_____________________________ test_multiply ______________________________

    def test_multiply():
>       assert 3 * 4 == 11
E       AssertionError: assert 12 == 11

tests/unit/test_foo.py:15: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_foo.py::test_multiply - AssertionError: assert 12 == 11
============================== 4 passed, 1 failed in 0.12s =====================
"""

_PYTEST_ALL_PASS = """\
============================= test session starts ==============================
platform darwin -- Python 3.14.0, pytest-8.3.4
collected 3 items

tests/unit/test_foo.py::test_add PASSED
tests/unit/test_foo.py::test_subtract PASSED
tests/unit/test_bar.py::test_greet PASSED

============================== 3 passed in 0.05s ===============================
"""

_PYTEST_ERROR = """\
============================= test session starts ==============================
collected 4 items

tests/unit/test_foo.py::test_add PASSED
tests/unit/test_foo.py::test_setup ERROR
tests/unit/test_foo.py::test_subtract PASSED
tests/unit/test_bar.py::test_greet PASSED

=================================== ERRORS =====================================
_____________________ ERROR at setup of test_setup _____________________

    @pytest.fixture
    def db():
>       raise RuntimeError("connection refused")
E       RuntimeError: connection refused

tests/conftest.py:10: RuntimeError
=========================== short test summary info ============================
ERROR tests/unit/test_foo.py::test_setup - RuntimeError: connection refused
============================== 3 passed, 1 error in 0.08s =====================
"""

_UNITTEST_OUTPUT = """\
test_add (tests.test_math.TestMath) ... ok
test_subtract (tests.test_math.TestMath) ... ok
test_multiply (tests.test_math.TestMath) ... FAIL
test_divide (tests.test_math.TestMath) ... ok

======================================================================
FAIL: test_multiply (tests.test_math.TestMath)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "tests/test_math.py", line 12, in test_multiply
    self.assertEqual(3 * 4, 11)
AssertionError: 12 != 11

----------------------------------------------------------------------
Ran 4 tests in 0.002s

FAILED (failures=1)
"""

_REGULAR_TEXT = """\
This is just some regular text that does not look like test output.
It has multiple lines but no test patterns.
Nothing to see here, just a normal log.
"""


def _make_envelope(
    content: str,
    content_type: ContentType = ContentType.TEXT,
) -> ContentEnvelope:
    return ContentEnvelope(
        content=content,
        content_type=content_type,
        metadata=MappingProxyType({}),
    )


class TestTestOutputCompressorCanHandle:
    """Test detection of test output patterns."""

    def test_can_handle_pytest_output(self) -> None:
        from token_sieve.adapters.compression.test_output_compressor import (
            TestOutputCompressor,
        )

        compressor = TestOutputCompressor()
        envelope = _make_envelope(_PYTEST_MIXED)
        assert compressor.can_handle(envelope) is True

    def test_can_handle_rejects_non_test(self) -> None:
        from token_sieve.adapters.compression.test_output_compressor import (
            TestOutputCompressor,
        )

        compressor = TestOutputCompressor()
        envelope = _make_envelope(_REGULAR_TEXT)
        assert compressor.can_handle(envelope) is False

    def test_detects_unittest_output(self) -> None:
        from token_sieve.adapters.compression.test_output_compressor import (
            TestOutputCompressor,
        )

        compressor = TestOutputCompressor()
        envelope = _make_envelope(_UNITTEST_OUTPUT)
        assert compressor.can_handle(envelope) is True


class TestTestOutputCompressorCompress:
    """Test compression of test output."""

    def test_compress_keeps_failures(self) -> None:
        from token_sieve.adapters.compression.test_output_compressor import (
            TestOutputCompressor,
        )

        compressor = TestOutputCompressor()
        envelope = _make_envelope(_PYTEST_MIXED)
        result = compressor.compress(envelope)
        assert "test_multiply" in result.content
        assert "AssertionError" in result.content

    def test_compress_drops_passed(self) -> None:
        from token_sieve.adapters.compression.test_output_compressor import (
            TestOutputCompressor,
        )

        compressor = TestOutputCompressor()
        envelope = _make_envelope(_PYTEST_MIXED)
        result = compressor.compress(envelope)
        # Individual PASSED lines should be removed
        lines = result.content.split("\n")
        passed_lines = [l for l in lines if "PASSED" in l and "::" in l]
        assert len(passed_lines) == 0
        # But passed count should be mentioned
        assert "4" in result.content  # 4 passed

    def test_compress_preserves_summary_footer(self) -> None:
        from token_sieve.adapters.compression.test_output_compressor import (
            TestOutputCompressor,
        )

        compressor = TestOutputCompressor()
        envelope = _make_envelope(_PYTEST_MIXED)
        result = compressor.compress(envelope)
        # Summary line should be preserved
        assert "passed" in result.content.lower()
        assert "failed" in result.content.lower()

    def test_compress_all_passing(self) -> None:
        from token_sieve.adapters.compression.test_output_compressor import (
            TestOutputCompressor,
        )

        compressor = TestOutputCompressor()
        envelope = _make_envelope(_PYTEST_ALL_PASS)
        result = compressor.compress(envelope)
        # Should be very compact — just count + summary
        assert len(result.content) < len(_PYTEST_ALL_PASS)
        assert "3" in result.content  # 3 passed
        assert "passed" in result.content.lower()

    def test_compress_keeps_errors(self) -> None:
        from token_sieve.adapters.compression.test_output_compressor import (
            TestOutputCompressor,
        )

        compressor = TestOutputCompressor()
        envelope = _make_envelope(_PYTEST_ERROR)
        result = compressor.compress(envelope)
        assert "test_setup" in result.content
        assert "RuntimeError" in result.content

    def test_compress_returns_envelope(self) -> None:
        from token_sieve.adapters.compression.test_output_compressor import (
            TestOutputCompressor,
        )

        compressor = TestOutputCompressor()
        envelope = _make_envelope(_PYTEST_MIXED)
        result = compressor.compress(envelope)
        assert isinstance(result, ContentEnvelope)
        assert result.content_type == ContentType.TEXT
