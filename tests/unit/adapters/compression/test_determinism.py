"""Determinism round-trip tests for all compression adapters.

Every adapter's compress() must produce byte-identical output when called
3 times on identical input. This ensures Anthropic prompt cache hits on
tool results -- any non-determinism invalidates the cache prefix.

Tests for NullFieldElider, WhitespaceNormalizer, YamlTranscoder use
shuffled key orders to expose missing sort_keys normalization.
Tests for FileRedirect and ProgressiveDisclosure assert stable output
across calls.
"""

from __future__ import annotations

import json
import textwrap

import pytest

from token_sieve.adapters.cache.diff_state_store import DiffStateStore
from token_sieve.adapters.compression.ast_skeleton import ASTSkeletonExtractor
from token_sieve.adapters.compression.code_comment_stripper import (
    CodeCommentStripper,
)
from token_sieve.adapters.compression.error_stack_compressor import (
    ErrorStackCompressor,
)
from token_sieve.adapters.compression.file_redirect import FileRedirectStrategy
from token_sieve.adapters.compression.graph_encoder import (
    GraphAdjacencyEncoder,
)
from token_sieve.adapters.compression.key_aliasing import KeyAliasingStrategy
from token_sieve.adapters.compression.log_level_filter import LogLevelFilter
from token_sieve.adapters.compression.null_field_elider import NullFieldElider
from token_sieve.adapters.compression.passthrough import PassthroughStrategy
from token_sieve.adapters.compression.path_prefix_deduplicator import (
    PathPrefixDeduplicator,
)
from token_sieve.adapters.compression.progressive_disclosure import (
    ProgressiveDisclosureStrategy,
)
from token_sieve.adapters.compression.rle_encoder import RunLengthEncoder
from token_sieve.adapters.compression.semantic_diff import SemanticDiffStrategy
from token_sieve.adapters.compression.sentence_scorer import (
    SentenceScorer,
    _SUMY_AVAILABLE,
)
from token_sieve.adapters.compression.size_gate import SizeGate
from token_sieve.adapters.compression.smart_truncation import SmartTruncation
from token_sieve.adapters.compression.timestamp_normalizer import (
    TimestampNormalizer,
)
from token_sieve.adapters.compression.toon_compressor import ToonCompressor
from token_sieve.adapters.compression.truncation import TruncationCompressor
from token_sieve.adapters.compression.whitespace_normalizer import (
    WhitespaceNormalizer,
)
from token_sieve.adapters.compression.yaml_transcoder import YamlTranscoder
from token_sieve.domain.model import ContentEnvelope, ContentType


# ---------------------------------------------------------------------------
# Test inputs -- chosen so each adapter's can_handle() returns True
# ---------------------------------------------------------------------------

_JSON_OBJECT = json.dumps(
    {"zebra": 1, "apple": 2, "mango": None, "banana": ""},
    indent=2,
)

# Same semantic JSON with different key ordering (shuffled)
_JSON_OBJECT_SHUFFLED = json.dumps(
    {"apple": 2, "banana": "", "mango": None, "zebra": 1},
    indent=2,
)

_JSON_ARRAY = json.dumps(
    [
        {"name": "Alice", "age": 30, "city": "NYC"},
        {"name": "Bob", "age": 25, "city": "LA"},
        {"name": "Carol", "age": 35, "city": "SF"},
    ],
    indent=2,
)

_PYTHON_CODE = textwrap.dedent("""\
    # This is a comment
    def hello(name: str) -> str:
        \"\"\"Greet someone.\"\"\"
        # Another comment
        return f"Hello, {name}!"

    class Greeter:
        \"\"\"A greeter class.\"\"\"
        def greet(self) -> str:
            return hello("world")
""")

_LOG_CONTENT = textwrap.dedent("""\
    2024-01-15T10:00:00Z [DEBUG] Starting process
    2024-01-15T10:00:01Z [INFO] Loading config
    2024-01-15T10:00:02Z [DEBUG] Config loaded
    2024-01-15T10:00:03Z [WARN] Slow query detected
    2024-01-15T10:00:04Z [ERROR] Connection failed
    2024-01-15T10:00:05Z [DEBUG] Retrying
    2024-01-15T10:00:06Z [INFO] Connected
    2024-01-15T10:00:07Z [DEBUG] Sending request
""")

_ERROR_STACK = textwrap.dedent("""\
    Traceback (most recent call last):
      File "/app/main.py", line 10, in <module>
        result = process()
      File "/app/process.py", line 20, in process
        return compute()
      File "/app/compute.py", line 30, in compute
        raise ValueError("bad value")
    ValueError: bad value

    Traceback (most recent call last):
      File "/app/main.py", line 10, in <module>
        result = process()
      File "/app/process.py", line 20, in process
        return compute()
      File "/app/compute.py", line 30, in compute
        raise ValueError("bad value")
    ValueError: bad value
""")

_PATHS_CONTENT = textwrap.dedent("""\
    /usr/local/lib/python3.12/site-packages/foo/bar.py
    /usr/local/lib/python3.12/site-packages/foo/baz.py
    /usr/local/lib/python3.12/site-packages/foo/qux.py
""")

_TIMESTAMPS_CONTENT = textwrap.dedent("""\
    2024-01-15T10:00:00.000Z Request started
    2024-01-15T10:00:01.500Z Processing
    2024-01-15T10:00:03.200Z Complete
""")

_RLE_CONTENT = textwrap.dedent("""\
    INFO: Starting
    INFO: Starting
    INFO: Starting
    INFO: Starting
    INFO: Starting
    WARN: Something
    ERROR: Failed
    ERROR: Failed
    ERROR: Failed
""")

_GRAPH_CONTENT = json.dumps(
    {
        "nodes": ["A", "B", "C"],
        "edges": [["A", "B"], ["B", "C"], ["A", "C"]],
    }
)

# Long prose for SentenceScorer (needs 100+ words, 5+ sentences)
_PROSE_CONTENT = (
    "The quick brown fox jumps over the lazy dog. "
    "This sentence contains enough words to pass the minimum threshold. "
    "Natural language processing is a subfield of computer science. "
    "Machine learning models can extract key sentences from documents. "
    "TextRank is an unsupervised algorithm for extractive summarization. "
    "It builds a graph of sentences and ranks them by importance. "
    "The algorithm converges to a stable ranking after several iterations. "
    "Extractive summarization preserves the original wording of sentences. "
    "This is useful when accuracy and faithfulness are important. "
    "The final output contains only the most informative sentences. "
    "Redundant information is naturally filtered out by the ranking process. "
    "This approach works well for technical documentation and reports. "
) * 2  # Double to ensure enough content

# Large content for FileRedirect and ProgressiveDisclosure (needs >10k tokens)
_LARGE_CONTENT = "x" * 50000


# ---------------------------------------------------------------------------
# Adapter factory functions
# ---------------------------------------------------------------------------


def _make_passthrough():
    return PassthroughStrategy()


def _make_whitespace_normalizer():
    return WhitespaceNormalizer()


def _make_null_field_elider():
    return NullFieldElider()


def _make_toon_compressor():
    return ToonCompressor()


def _make_yaml_transcoder():
    return YamlTranscoder()


def _make_rle_encoder():
    return RunLengthEncoder()


def _make_log_level_filter():
    return LogLevelFilter(enabled=True)


def _make_error_stack_compressor():
    return ErrorStackCompressor(enabled=True)


def _make_code_comment_stripper():
    return CodeCommentStripper(enabled=True)


def _make_path_prefix_dedup():
    return PathPrefixDeduplicator()


def _make_timestamp_normalizer():
    return TimestampNormalizer()


def _make_smart_truncation():
    return SmartTruncation(head_lines=3, tail_lines=2)


def _make_truncation():
    return TruncationCompressor(max_tokens=100)


def _make_size_gate():
    return SizeGate(threshold=999999)


def _make_key_aliasing():
    return KeyAliasingStrategy(min_occurrences=1, min_key_length=3)


def _make_ast_skeleton():
    return ASTSkeletonExtractor()


def _make_graph_encoder():
    return GraphAdjacencyEncoder()


def _make_sentence_scorer():
    return SentenceScorer(sentence_count=3)


def _make_semantic_diff():
    store = DiffStateStore()
    return SemanticDiffStrategy(store)


def _make_file_redirect(tmp_path):
    return FileRedirectStrategy(threshold_tokens=1, output_dir=str(tmp_path))


def _make_progressive_disclosure(tmp_path):
    return ProgressiveDisclosureStrategy(
        threshold_tokens=1, output_dir=str(tmp_path)
    )


# ---------------------------------------------------------------------------
# Parametrized determinism tests -- identical input, 3 calls
# ---------------------------------------------------------------------------

# Adapters that should be fully deterministic on identical bytes
_DETERMINISTIC_ADAPTERS = [
    pytest.param(
        _make_passthrough,
        ContentEnvelope(content="hello world", content_type=ContentType.TEXT),
        id="PassthroughStrategy",
    ),
    pytest.param(
        _make_whitespace_normalizer,
        ContentEnvelope(content=_JSON_OBJECT, content_type=ContentType.JSON),
        id="WhitespaceNormalizer",
    ),
    pytest.param(
        _make_null_field_elider,
        ContentEnvelope(content=_JSON_OBJECT, content_type=ContentType.JSON),
        id="NullFieldElider",
    ),
    pytest.param(
        _make_toon_compressor,
        ContentEnvelope(content=_JSON_ARRAY, content_type=ContentType.JSON),
        id="ToonCompressor",
    ),
    pytest.param(
        _make_yaml_transcoder,
        ContentEnvelope(content=_JSON_OBJECT, content_type=ContentType.JSON),
        id="YamlTranscoder",
    ),
    pytest.param(
        _make_rle_encoder,
        ContentEnvelope(content=_RLE_CONTENT, content_type=ContentType.TEXT),
        id="RunLengthEncoder",
    ),
    pytest.param(
        _make_log_level_filter,
        ContentEnvelope(content=_LOG_CONTENT, content_type=ContentType.TEXT),
        id="LogLevelFilter",
    ),
    pytest.param(
        _make_error_stack_compressor,
        ContentEnvelope(content=_ERROR_STACK, content_type=ContentType.TEXT),
        id="ErrorStackCompressor",
    ),
    pytest.param(
        _make_code_comment_stripper,
        ContentEnvelope(content=_PYTHON_CODE, content_type=ContentType.CODE),
        id="CodeCommentStripper",
    ),
    pytest.param(
        _make_path_prefix_dedup,
        ContentEnvelope(content=_PATHS_CONTENT, content_type=ContentType.TEXT),
        id="PathPrefixDeduplicator",
    ),
    pytest.param(
        _make_timestamp_normalizer,
        ContentEnvelope(
            content=_TIMESTAMPS_CONTENT, content_type=ContentType.TEXT
        ),
        id="TimestampNormalizer",
    ),
    pytest.param(
        _make_smart_truncation,
        ContentEnvelope(content=_LOG_CONTENT, content_type=ContentType.TEXT),
        id="SmartTruncation",
    ),
    pytest.param(
        _make_truncation,
        ContentEnvelope(content=_LARGE_CONTENT, content_type=ContentType.TEXT),
        id="TruncationCompressor",
    ),
    pytest.param(
        _make_size_gate,
        ContentEnvelope(content="small", content_type=ContentType.TEXT),
        id="SizeGate",
    ),
    pytest.param(
        _make_key_aliasing,
        ContentEnvelope(content=_JSON_ARRAY, content_type=ContentType.JSON),
        id="KeyAliasingStrategy",
    ),
    pytest.param(
        _make_ast_skeleton,
        ContentEnvelope(content=_PYTHON_CODE, content_type=ContentType.CODE),
        id="ASTSkeletonExtractor",
    ),
    pytest.param(
        _make_graph_encoder,
        ContentEnvelope(content=_GRAPH_CONTENT, content_type=ContentType.JSON),
        id="GraphAdjacencyEncoder",
    ),
]


class TestDeterminismRoundTrip:
    """compress(x) called 3 times must produce byte-identical output."""

    @pytest.mark.parametrize("factory,envelope", _DETERMINISTIC_ADAPTERS)
    def test_identical_input_produces_identical_output(
        self, factory, envelope
    ):
        """3 consecutive calls on same input yield same output."""
        adapter = factory()
        results = [adapter.compress(envelope).content for _ in range(3)]
        assert results[0] == results[1] == results[2], (
            f"Non-deterministic output detected across 3 calls"
        )

    def test_semantic_diff_deterministic_for_same_state(self):
        """SemanticDiff returns same output for identical state (first call)."""
        adapter = _make_semantic_diff()
        envelope = ContentEnvelope(
            content="test content",
            content_type=ContentType.TEXT,
            metadata={"source_tool": "test", "source_args": "{}"},
        )
        # First call stores and returns as-is -- deterministic
        r1 = adapter.compress(envelope).content

        # Make a fresh adapter+store for identical first-call scenario
        adapter2 = _make_semantic_diff()
        r2 = adapter2.compress(envelope).content

        assert r1 == r2


class TestSortKeysNormalization:
    """Adapters must produce identical output for JSON with shuffled keys."""

    def test_null_field_elider_shuffled_keys(self):
        """NullFieldElider output must be identical regardless of key order."""
        adapter = NullFieldElider()
        env_a = ContentEnvelope(
            content=_JSON_OBJECT, content_type=ContentType.JSON
        )
        env_b = ContentEnvelope(
            content=_JSON_OBJECT_SHUFFLED, content_type=ContentType.JSON
        )
        result_a = adapter.compress(env_a).content
        result_b = adapter.compress(env_b).content
        assert result_a == result_b, (
            f"NullFieldElider is not key-order-normalized:\n"
            f"  input A -> {result_a}\n"
            f"  input B -> {result_b}"
        )

    def test_whitespace_normalizer_shuffled_keys(self):
        """WhitespaceNormalizer output must be identical regardless of key order."""
        adapter = WhitespaceNormalizer()
        env_a = ContentEnvelope(
            content=_JSON_OBJECT, content_type=ContentType.JSON
        )
        env_b = ContentEnvelope(
            content=_JSON_OBJECT_SHUFFLED, content_type=ContentType.JSON
        )
        result_a = adapter.compress(env_a).content
        result_b = adapter.compress(env_b).content
        assert result_a == result_b, (
            f"WhitespaceNormalizer is not key-order-normalized:\n"
            f"  input A -> {result_a}\n"
            f"  input B -> {result_b}"
        )

    def test_yaml_transcoder_shuffled_keys(self):
        """YamlTranscoder output must be identical regardless of key order."""
        adapter = YamlTranscoder()
        env_a = ContentEnvelope(
            content=_JSON_OBJECT, content_type=ContentType.JSON
        )
        env_b = ContentEnvelope(
            content=_JSON_OBJECT_SHUFFLED, content_type=ContentType.JSON
        )
        result_a = adapter.compress(env_a).content
        result_b = adapter.compress(env_b).content
        assert result_a == result_b, (
            f"YamlTranscoder is not key-order-normalized:\n"
            f"  input A -> {result_a}\n"
            f"  input B -> {result_b}"
        )


class TestTempfileDeterminism:
    """FileRedirect and ProgressiveDisclosure must produce stable output."""

    def test_file_redirect_stable_output(self, tmp_path):
        """FileRedirect must produce identical output for identical content."""
        envelope = ContentEnvelope(
            content=_LARGE_CONTENT, content_type=ContentType.TEXT
        )
        results = []
        for _ in range(3):
            adapter = _make_file_redirect(tmp_path)
            result = adapter.compress(envelope).content
            results.append(result)
            adapter.cleanup()

        assert results[0] == results[1] == results[2], (
            f"FileRedirect output varies across calls:\n"
            f"  call 1: {results[0][:80]}...\n"
            f"  call 2: {results[1][:80]}...\n"
            f"  call 3: {results[2][:80]}..."
        )
        # Verify deterministic content-hash-based path
        assert "token-sieve-" in results[0]

    def test_progressive_disclosure_stable_output(self, tmp_path):
        """ProgressiveDisclosure must produce identical output for identical content."""
        envelope = ContentEnvelope(
            content=_LARGE_CONTENT, content_type=ContentType.TEXT
        )
        results = []
        for _ in range(3):
            adapter = _make_progressive_disclosure(tmp_path)
            result = adapter.compress(envelope).content
            results.append(result)
            adapter.cleanup()

        assert results[0] == results[1] == results[2], (
            f"ProgressiveDisclosure output varies across calls:\n"
            f"  call 1: {results[0][:80]}...\n"
            f"  call 2: {results[1][:80]}...\n"
            f"  call 3: {results[2][:80]}..."
        )
        # Verify deterministic content-hash-based path
        assert "token-sieve-prog-" in results[0]
