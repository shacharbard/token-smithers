---
phase: "06"
plan: "01"
title: "Dependencies Setup + JSON Content Unwrapper"
status: complete
started_at: "2026-04-04T00:00:00Z"
completed_at: "2026-04-04T01:00:00Z"
commits:
  - hash: "8a55638"
    message: "feat(06-01-P01): add [ast] optional extra with tree-sitter grammars"
  - hash: "0f8c30a"
    message: "test(06-01-P02+P03): RED -- add JsonCodeUnwrapper contract and behavioral tests"
  - hash: "b56ade3"
    message: "feat(06-01-P04): GREEN -- implement JsonCodeUnwrapper adapter"
  - hash: "4eb8d20"
    message: "refactor(06-01-P05): add kwargs constructor for AdapterConfig compatibility"
tests_added: 27
tests_total_pass: 1092
pre_existing_failures:
  - test: "test_stats_prints_formatted_table"
    file: "tests/unit/cli/test_stats_command.py"
    error: "assert '1000' in formatted output -- stats formatting mismatch"
deviations: []
---

## What Was Built

- `pyproject.toml`: Added `[ast]` optional extra with tree-sitter>=0.23.0 and 6 grammar packages. Added to `dev` extra. Added `[all]` meta-extra.
- `JsonCodeUnwrapper` adapter: Extracts code from JSON tool results with known field names (source, content, code, output, body) when value >500 chars with code signals.
- Full contract test suite inheriting from `CompressionStrategyContract`.
- Smoke test for tree-sitter package imports.

## Files Modified

- `pyproject.toml`
- `src/token_sieve/adapters/compression/json_code_unwrapper.py` (new)
- `tests/unit/adapters/compression/test_json_code_unwrapper.py` (new)
- `tests/unit/test_ast_extra_smoke.py` (new)

## Verification

All 27 new tests passing. 1092 total tests green (1 pre-existing failure unrelated to this work).
