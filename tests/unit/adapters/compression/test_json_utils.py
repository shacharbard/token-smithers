"""Tests for shared JSON parsing utilities."""
from __future__ import annotations

import pytest

from token_sieve.adapters.compression._json_utils import JSON_START_RE, try_parse_json


class TestTryParseJson:
    """try_parse_json returns parsed data or None on failure."""

    def test_valid_object(self):
        result = try_parse_json('{"a": 1}')
        assert result == {"a": 1}

    def test_valid_array(self):
        result = try_parse_json('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_valid_string(self):
        result = try_parse_json('"hello"')
        assert result == "hello"

    def test_valid_number(self):
        result = try_parse_json("42")
        assert result == 42

    def test_invalid_json_returns_none(self):
        assert try_parse_json("not json") is None

    def test_empty_string_returns_none(self):
        assert try_parse_json("") is None

    def test_none_input_returns_none(self):
        # TypeError case
        assert try_parse_json(None) is None  # type: ignore[arg-type]

    def test_truncated_json_returns_none(self):
        assert try_parse_json('{"a":') is None

    def test_catches_value_error(self):
        """ValueError should be caught alongside JSONDecodeError."""
        assert try_parse_json("{bad}") is None


class TestJsonStartRe:
    """JSON_START_RE detects lines starting with [ or {."""

    def test_matches_object_start(self):
        assert JSON_START_RE.match('{"key": "val"}')

    def test_matches_array_start(self):
        assert JSON_START_RE.match("[1, 2, 3]")

    def test_matches_with_leading_whitespace(self):
        assert JSON_START_RE.match("  {}")
        assert JSON_START_RE.match("\t[]")

    def test_no_match_plain_text(self):
        assert JSON_START_RE.match("hello world") is None

    def test_no_match_number(self):
        assert JSON_START_RE.match("42") is None


class TestAdaptersUseSharedUtils:
    """Adapters that were refactored should import from _json_utils."""

    def test_yaml_transcoder_uses_shared_parse(self):
        """YamlTranscoder should use try_parse_json from _json_utils."""
        from token_sieve.adapters.compression import yaml_transcoder

        # Should not have its own _try_parse_json as a method anymore;
        # the class should delegate to the shared module function
        assert not hasattr(yaml_transcoder.YamlTranscoder, "_try_parse_json")

    def test_key_aliasing_no_local_json_start_re(self):
        """key_aliasing module should not define its own _JSON_START_RE."""
        import token_sieve.adapters.compression.key_aliasing as mod

        # The module-level _JSON_START_RE should be the shared one
        assert mod._JSON_START_RE is JSON_START_RE

    def test_graph_encoder_no_local_json_start_re(self):
        """graph_encoder module should not define its own _JSON_START_RE."""
        import token_sieve.adapters.compression.graph_encoder as mod

        assert mod._JSON_START_RE is JSON_START_RE
