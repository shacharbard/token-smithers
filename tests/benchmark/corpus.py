"""Fixed benchmark corpus for reproducible compression measurements.

Inspired by DietMCP's 135-tool corpus approach. Contains realistic tool
results covering diverse content types to measure compression effectiveness.
"""

from __future__ import annotations

from token_sieve.domain.model import ContentEnvelope, ContentType

# --- Raw corpus data: tool_name -> (content, content_type) ---

_JSON_FILE_LISTING = """\
[
  {"name": "src/main.py", "size": 4523, "modified": "2026-03-15T10:30:00Z", "type": "file"},
  {"name": "src/utils.py", "size": 2100, "modified": "2026-03-15T10:30:00Z", "type": "file"},
  {"name": "src/config.py", "size": 890, "modified": "2026-03-14T08:00:00Z", "type": "file"},
  {"name": "src/models/user.py", "size": 1500, "modified": "2026-03-14T08:00:00Z", "type": "file"},
  {"name": "src/models/order.py", "size": 2300, "modified": "2026-03-14T08:00:00Z", "type": "file"},
  {"name": "src/models/__init__.py", "size": 45, "modified": "2026-03-13T12:00:00Z", "type": "file"},
  {"name": "tests/test_main.py", "size": 3200, "modified": "2026-03-15T10:30:00Z", "type": "file"},
  {"name": "tests/test_utils.py", "size": 1800, "modified": "2026-03-15T10:30:00Z", "type": "file"},
  {"name": "tests/__init__.py", "size": 0, "modified": "2026-03-12T09:00:00Z", "type": "file"},
  {"name": "README.md", "size": 5600, "modified": "2026-03-10T14:00:00Z", "type": "file"}
]"""

_SEARCH_RESULTS_WITH_PATHS = """\
/Users/dev/project/src/token_sieve/domain/model.py:28: class ContentEnvelope:
/Users/dev/project/src/token_sieve/domain/model.py:64: class CompressionEvent:
/Users/dev/project/src/token_sieve/domain/model.py:84: class TokenBudget:
/Users/dev/project/src/token_sieve/domain/pipeline.py:21: class CompressionPipeline:
/Users/dev/project/src/token_sieve/adapters/compression/whitespace_normalizer.py:16: class WhitespaceNormalizer:
/Users/dev/project/src/token_sieve/adapters/compression/null_field_elider.py:20: class NullFieldElider:
/Users/dev/project/src/token_sieve/adapters/compression/path_prefix_deduplicator.py:31: class PathPrefixDeduplicator:
/Users/dev/project/src/token_sieve/adapters/compression/toon_compressor.py:20: class ToonCompressor:
/Users/dev/project/tests/unit/domain/test_model.py:15: class TestContentEnvelope:
/Users/dev/project/tests/unit/domain/test_pipeline.py:96: class TestCompressionPipeline:"""

_LOG_OUTPUT = """\
2026-03-15T10:30:00.123Z INFO  [main] Starting application v2.1.0
2026-03-15T10:30:00.125Z DEBUG [config] Loading configuration from /etc/app/config.yaml
2026-03-15T10:30:00.130Z DEBUG [config] Backend transport: stdio
2026-03-15T10:30:00.131Z DEBUG [config] Compression enabled: true
2026-03-15T10:30:00.135Z INFO  [server] Listening on port 8080
2026-03-15T10:30:01.200Z DEBUG [handler] Received request: GET /health
2026-03-15T10:30:01.201Z DEBUG [handler] Response: 200 OK (1ms)
2026-03-15T10:30:02.500Z INFO  [handler] Received request: POST /api/compress
2026-03-15T10:30:02.510Z DEBUG [pipeline] Running WhitespaceNormalizer
2026-03-15T10:30:02.512Z DEBUG [pipeline] Running NullFieldElider
2026-03-15T10:30:02.515Z DEBUG [pipeline] Running ToonCompressor
2026-03-15T10:30:02.520Z INFO  [handler] Compression complete: 45% reduction
2026-03-15T10:30:02.521Z DEBUG [handler] Response: 200 OK (21ms)
2026-03-15T10:30:05.000Z WARN  [monitor] Memory usage at 75%
2026-03-15T10:30:10.000Z DEBUG [handler] Received request: GET /health
2026-03-15T10:30:10.001Z DEBUG [handler] Response: 200 OK (1ms)"""

_PYTHON_TRACEBACK = """\
Traceback (most recent call last):
  File "/Users/dev/project/src/main.py", line 45, in main
    result = process_request(request)
  File "/Users/dev/project/src/handler.py", line 82, in process_request
    data = validate_input(request.body)
  File "/Users/dev/project/src/validation.py", line 23, in validate_input
    schema.validate(data)
  File "/Users/dev/.pyenv/versions/3.12.0/lib/python3.12/site-packages/jsonschema/validators.py", line 301, in validate
    raise error
  File "/Users/dev/.pyenv/versions/3.12.0/lib/python3.12/site-packages/jsonschema/validators.py", line 245, in iter_errors
    yield error
  File "/Users/dev/.pyenv/versions/3.12.0/lib/python3.12/site-packages/jsonschema/_validators.py", line 72, in required
    yield ValidationError(f"{property!r} is a required property")
jsonschema.exceptions.ValidationError: 'name' is a required property

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/dev/project/src/handler.py", line 85, in process_request
    raise HTTPError(400, str(e))
  File "/Users/dev/.pyenv/versions/3.12.0/lib/python3.12/site-packages/werkzeug/exceptions.py", line 203, in __init__
    super().__init__(description)
werkzeug.exceptions.BadRequest: 400 Bad Request: 'name' is a required property"""

_CODE_WITH_COMMENTS = '''\
"""Module for handling user authentication.

This module provides the core authentication logic including
token generation, validation, and refresh mechanisms.
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

# Default token expiry is 24 hours
DEFAULT_TOKEN_EXPIRY = timedelta(hours=24)

# Maximum number of active sessions per user
MAX_SESSIONS = 5


class AuthenticationError(Exception):
    """Raised when authentication fails."""
    pass  # Simple marker exception


class TokenManager:
    """Manages authentication tokens.

    Handles creation, validation, and refresh of JWT-like tokens.
    Uses HMAC-SHA256 for signing.
    """

    def __init__(self, secret: str, expiry: timedelta = DEFAULT_TOKEN_EXPIRY):
        # Store the signing secret
        self._secret = secret
        # Token lifetime
        self._expiry = expiry
        # Active tokens: token_hash -> (user_id, expiry_time)
        self._tokens: dict[str, tuple[str, datetime]] = {}

    def create_token(self, user_id: str) -> str:
        """Create a new authentication token for the user.

        Args:
            user_id: The unique identifier for the user.

        Returns:
            A signed token string.
        """
        # Generate random token
        raw = secrets.token_urlsafe(32)
        # Sign it
        signature = hashlib.hmac_new(
            self._secret.encode(), raw.encode(), hashlib.sha256
        ).hexdigest()
        token = f"{raw}.{signature}"
        # Store hash -> metadata
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        self._tokens[token_hash] = (user_id, datetime.utcnow() + self._expiry)
        return token

    def validate_token(self, token: str) -> Optional[str]:
        """Validate a token and return the user_id if valid.

        Returns None if token is invalid or expired.
        """
        # Check if token exists
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        entry = self._tokens.get(token_hash)
        if entry is None:
            return None
        user_id, expiry = entry
        # Check expiry
        if datetime.utcnow() > expiry:
            # Clean up expired token
            del self._tokens[token_hash]
            return None
        return user_id
'''

_DOCUMENTATION_PROSE = """\
# Token Sieve Architecture

Token Sieve is an MCP compression gateway that reduces token usage by intercepting \
and compressing tool results between Claude Code and backend MCP servers. The system \
operates as a transparent proxy, applying content-aware compression strategies to \
minimize token consumption without losing semantic information.

## Design Principles

The architecture follows hexagonal (ports and adapters) design with domain-driven \
boundaries. The core domain defines Protocol interfaces that adapters implement \
through structural subtyping. This ensures the compression logic remains independent \
of transport mechanisms and specific MCP implementations.

### Content Routing

Content entering the pipeline is wrapped in a ContentEnvelope that carries both the \
raw content and its detected ContentType. The pipeline routes envelopes through \
type-specific strategy chains. Each strategy can inspect the envelope, decide \
whether it can handle the content type, and produce a compressed version.

### Adapter Ordering

Adapters execute in a carefully chosen order. Cleanup adapters (whitespace \
normalization, null field elision, path deduplication) run first as they are \
lossless and reduce noise for downstream adapters. Content-specific lossy adapters \
(log filtering, error stack compression) run next. Format transforms (TOON \
encoding, YAML transcoding) follow. Smart truncation serves as the final safety \
net to ensure output fits within token budgets.

## Performance Characteristics

The compression pipeline is designed for low latency. Individual adapter operations \
target sub-millisecond processing times. The full pipeline typically completes in \
under 10ms for content up to 50,000 characters. Memory usage scales linearly with \
content size, with no persistent state between requests beyond session-scoped \
deduplication caches."""

# --- Assembled corpus ---

BENCHMARK_CORPUS: dict[str, ContentEnvelope] = {
    "list_directory": ContentEnvelope(
        content=_JSON_FILE_LISTING,
        content_type=ContentType.JSON,
        metadata={"tool_name": "list_directory"},
    ),
    "search_files": ContentEnvelope(
        content=_SEARCH_RESULTS_WITH_PATHS,
        content_type=ContentType.TEXT,
        metadata={"tool_name": "search_files"},
    ),
    "read_logs": ContentEnvelope(
        content=_LOG_OUTPUT,
        content_type=ContentType.TEXT,
        metadata={"tool_name": "read_logs"},
    ),
    "run_tests": ContentEnvelope(
        content=_PYTHON_TRACEBACK,
        content_type=ContentType.TEXT,
        metadata={"tool_name": "run_tests"},
    ),
    "read_file_code": ContentEnvelope(
        content=_CODE_WITH_COMMENTS,
        content_type=ContentType.CODE,
        metadata={"tool_name": "read_file", "language": "python"},
    ),
    "read_file_docs": ContentEnvelope(
        content=_DOCUMENTATION_PROSE,
        content_type=ContentType.TEXT,
        metadata={"tool_name": "read_file"},
    ),
}
