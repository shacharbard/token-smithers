---
phase: "06"
plan: "03"
title: "Registration, Migration, and Integration"
status: complete
started_at: "2026-04-04T01:00:00Z"
completed_at: "2026-04-04T02:00:00Z"
commits:
  - hash: "81e141b"
    message: "test(server): RED -- add Phase 06 registry and default config tests"
  - hash: "bb6a85a"
    message: "test(config+adapters): RED -- add validator and determinism tests for tree-sitter"
  - hash: "b23ee56"
    message: "feat(config): GREEN -- triple-change registration + ast_skeleton deprecation"
tests_added: 21
tests_total_pass: 1136
pre_existing_failures:
  - test: "test_stats_prints_formatted_table"
    file: "tests/unit/cli/test_stats_command.py"
    error: "assert '1000' in formatted output -- stats formatting mismatch"
deviations: []
---

## What Was Built

- Triple-change registration: `tree_sitter_ast` and `json_code_unwrapper` added to `_ADAPTER_REGISTRY`, `CONTENT_SPECIFIC`, and `_default_adapters()`.
- `ast_skeleton` registry alias remapped to `TreeSitterASTExtractor` with `DeprecationWarning`.
- Default adapter ordering: `json_code_unwrapper` before `tree_sitter_ast` (unwrap JSON first, then extract AST).
- Determinism tests for tree-sitter across Python, TypeScript, and Go.
- `TestValidatorMatchesRegistry` continues to pass (consistency enforced).

## Files Modified

- `src/token_sieve/server/proxy.py` (modified, +20 lines)
- `src/token_sieve/config/validator.py` (modified, +2 lines)
- `src/token_sieve/config/schema.py` (modified, +2 lines)
- `tests/unit/server/test_proxy_phase06_hooks.py` (new, 95 lines)
- `tests/unit/config/test_validator.py` (modified, +26 lines)
- `tests/unit/adapters/compression/test_determinism.py` (modified, +132 lines)

## Verification

All 1136 tests green (1 pre-existing failure excluded). Coverage: 85.71%. Full integration verified — pipeline processes code through new adapters correctly.
