"""Tests for ErrorStackCompressor adapter.

Inherits CompressionStrategyContract for protocol compliance.
ErrorStackCompressor is a lossy adapter: off by default, opt-in via enabled=True.
"""

from __future__ import annotations

import pytest

from tests.unit.adapters.conftest import CompressionStrategyContract
from token_sieve.adapters.compression.error_stack_compressor import (
    ErrorStackCompressor,
)
from token_sieve.domain.model import ContentType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def strategy():
    """Provide enabled ErrorStackCompressor for contract tests."""
    return ErrorStackCompressor(enabled=True)


@pytest.fixture()
def disabled_strategy():
    """ErrorStackCompressor with default (disabled) state."""
    return ErrorStackCompressor()


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestErrorStackCompressorContract(CompressionStrategyContract):
    """ErrorStackCompressor must satisfy the CompressionStrategy contract."""


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

PYTHON_TRACEBACK = """\
Traceback (most recent call last):
  File "/app/main.py", line 42, in run
    result = process_request(data)
  File "/app/handlers.py", line 88, in process_request
    validated = validate(data)
  File "/usr/lib/python3.12/site-packages/pydantic/main.py", line 150, in validate
    return cls.model_validate(data)
  File "/usr/lib/python3.12/site-packages/pydantic/_internal/_validate.py", line 75, in _validate
    raise ValidationError(errors)
  File "/home/user/.venv/lib/python3.12/site-packages/pydantic/error_wrappers.py", line 40, in __init__
    super().__init__(message)
  File "/app/handlers.py", line 92, in process_request
    db.save(validated)
  File "/app/db.py", line 15, in save
    cursor.execute(sql, params)
psycopg2.OperationalError: connection refused to host "db-primary", port 5432
""".strip()

PYTHON_DUPLICATE_TRACEBACKS = """\
Traceback (most recent call last):
  File "/app/main.py", line 42, in run
    result = process_request(data)
  File "/app/handlers.py", line 88, in process_request
    validated = validate(data)
  File "/app/db.py", line 15, in save
    cursor.execute(sql, params)
psycopg2.OperationalError: connection refused

Traceback (most recent call last):
  File "/app/main.py", line 42, in run
    result = process_request(data)
  File "/app/handlers.py", line 88, in process_request
    validated = validate(data)
  File "/app/db.py", line 15, in save
    cursor.execute(sql, params)
psycopg2.OperationalError: connection refused

Traceback (most recent call last):
  File "/app/main.py", line 42, in run
    result = process_request(data)
  File "/app/handlers.py", line 88, in process_request
    validated = validate(data)
  File "/app/db.py", line 15, in save
    cursor.execute(sql, params)
psycopg2.OperationalError: connection refused
""".strip()

JS_STACK_TRACE = """\
Error: ECONNREFUSED 127.0.0.1:5432
    at TCPConnectWrap.afterConnect [as oncomplete] (node:net:1495:16)
    at node_modules/pg/lib/connection.js:73:9
    at node_modules/pg/lib/client.js:132:19
    at Object.connect (/app/src/db.ts:42:5)
    at processRequest (/app/src/handlers.ts:88:12)
    at main (/app/src/index.ts:15:3)
""".strip()

NON_TRACEBACK_CONTENT = """\
def hello():
    print("Hello, world!")
    return 42

class Foo:
    pass

# This is just regular code, not a traceback.
""".strip()

SHORT_ERROR = """\
Error: something broke
    at main (/app/index.js:10:3)
""".strip()


# ---------------------------------------------------------------------------
# Specific tests
# ---------------------------------------------------------------------------


class TestErrorStackCompressorSpecific:
    """ErrorStackCompressor-specific behavioral tests."""

    def test_python_traceback_library_frames_stripped(self, strategy, make_envelope):
        """Library frames (site-packages, venv) are stripped from Python tracebacks."""
        envelope = make_envelope(content=PYTHON_TRACEBACK)
        result = strategy.compress(envelope)
        assert "site-packages" not in result.content
        assert ".venv" not in result.content

    def test_python_traceback_root_cause_preserved(self, strategy, make_envelope):
        """Root cause line (final exception) is always preserved."""
        envelope = make_envelope(content=PYTHON_TRACEBACK)
        result = strategy.compress(envelope)
        assert "psycopg2.OperationalError" in result.content

    def test_python_traceback_app_frames_preserved(self, strategy, make_envelope):
        """Application frames (/app/) are preserved."""
        envelope = make_envelope(content=PYTHON_TRACEBACK)
        result = strategy.compress(envelope)
        assert "/app/main.py" in result.content
        assert "/app/db.py" in result.content

    def test_duplicate_tracebacks_compressed(self, strategy, make_envelope):
        """Multiple identical tracebacks compressed to one with count."""
        envelope = make_envelope(content=PYTHON_DUPLICATE_TRACEBACKS)
        result = strategy.compress(envelope)
        # Should mention the count or be significantly shorter
        original_tb_count = PYTHON_DUPLICATE_TRACEBACKS.count("Traceback (most recent")
        assert original_tb_count == 3
        result_tb_count = result.content.count("Traceback (most recent")
        assert result_tb_count < original_tb_count

    def test_js_stack_trace_handled(self, strategy, make_envelope):
        """JavaScript stack traces are detected and compressed."""
        envelope = make_envelope(content=JS_STACK_TRACE)
        assert strategy.can_handle(envelope) is True
        result = strategy.compress(envelope)
        # node_modules frames should be stripped
        assert "node_modules" not in result.content
        # Root cause preserved
        assert "ECONNREFUSED" in result.content

    def test_summary_marker_appended(self, strategy, make_envelope):
        """Summary marker is appended showing frames removed."""
        envelope = make_envelope(content=PYTHON_TRACEBACK)
        result = strategy.compress(envelope)
        assert "[token-sieve:" in result.content
        assert "ErrorStackCompressor" in result.content

    def test_non_traceback_not_handled(self, strategy, make_envelope):
        """Non-traceback content -> can_handle returns False."""
        envelope = make_envelope(content=NON_TRACEBACK_CONTENT)
        assert strategy.can_handle(envelope) is False

    def test_disabled_by_default(self, make_envelope):
        """Default ErrorStackCompressor has enabled=False -> can_handle False."""
        s = ErrorStackCompressor()
        envelope = make_envelope(content=PYTHON_TRACEBACK)
        assert s.can_handle(envelope) is False

    def test_enabled_false_explicit(self, disabled_strategy, make_envelope):
        """enabled=False -> always returns can_handle False."""
        envelope = make_envelope(content=PYTHON_TRACEBACK)
        assert disabled_strategy.can_handle(envelope) is False

    def test_preserves_content_type(self, strategy, make_envelope):
        """Content type is preserved after compression."""
        envelope = make_envelope(
            content=PYTHON_TRACEBACK, content_type=ContentType.CLI_OUTPUT
        )
        result = strategy.compress(envelope)
        assert result.content_type == ContentType.CLI_OUTPUT

    def test_can_handle_true_for_python_traceback(self, strategy, make_envelope):
        """Python traceback -> can_handle True."""
        envelope = make_envelope(content=PYTHON_TRACEBACK)
        assert strategy.can_handle(envelope) is True

    def test_short_error_not_handled(self, strategy, make_envelope):
        """Very short error (< 3 traceback signals) -> can_handle False."""
        envelope = make_envelope(content=SHORT_ERROR)
        assert strategy.can_handle(envelope) is False

    def test_significant_compression(self, strategy, make_envelope):
        """Traceback with library frames achieves significant compression."""
        envelope = make_envelope(content=PYTHON_TRACEBACK)
        result = strategy.compress(envelope)
        assert len(result.content) < len(envelope.content)
