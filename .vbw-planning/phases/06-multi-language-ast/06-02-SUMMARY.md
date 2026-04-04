---
phase: "06"
plan: "02"
title: "Core TreeSitterASTExtractor Adapter"
status: complete
started_at: "2026-04-04T00:00:00Z"
completed_at: "2026-04-04T01:00:00Z"
commits:
  - hash: "1dfa6d4"
    message: "test(adapters): RED -- add TreeSitterASTExtractor contract and Python/TypeScript behavioral tests"
  - hash: "cf02f9d"
    message: "test(adapters): RED -- add remaining language + error tolerance tests for TreeSitterASTExtractor"
  - hash: "bc36992"
    message: "feat(adapters): GREEN -- implement TreeSitterASTExtractor with 6-language support"
  - hash: "0996820"
    message: "feat(adapters): GREEN -- fix brace-language method signatures"
  - hash: "2f33f03"
    message: "refactor(adapters): clean up TreeSitterASTExtractor config dicts and type annotations"
tests_added: 26
tests_total_pass: 1092
pre_existing_failures:
  - test: "test_stats_prints_formatted_table"
    file: "tests/unit/cli/test_stats_command.py"
    error: "assert '1000' in formatted output -- stats formatting mismatch"
deviations: []
---

## What Was Built

- `TreeSitterASTExtractor` adapter: Single adapter handling 6 languages (Python, TypeScript, JavaScript, Go, Rust, Java) via internal dispatch.
- Per-language config dicts defining node types, signature terminators, doc-comment rules.
- Layered language detection: metadata → content heuristics → tree-sitter error-rate probing.
- Signature extraction mode: keeps signatures + decorators/annotations + doc comments, drops bodies.
- Error tolerance: >50% ERROR nodes → passthrough, >100ms timeout → passthrough, zero structures → passthrough.
- Optional import guard (`_TREE_SITTER_AVAILABLE`) for graceful degradation.
- Full contract test suite + per-language behavioral tests.

## Files Modified

- `src/token_sieve/adapters/compression/tree_sitter_ast.py` (new, 559 lines)
- `tests/unit/adapters/compression/test_tree_sitter_ast.py` (new, 732 lines)

## Verification

All 26 new tests passing. 627 total adapter tests green with zero regressions.
