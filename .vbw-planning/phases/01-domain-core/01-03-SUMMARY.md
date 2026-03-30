---
phase: 1
plan: 3
title: "CLI Test Harness & Zero-Dependency Enforcement"
status: complete
tasks_completed: 4
tasks_total: 4
commits:
  - hash: e5bd7f7
    task: 1
    message: "test(01-03): CLI test harness RED phase with failing tests"
  - hash: e04543b
    task: 2
    message: "feat(01-03): CLI main implementation with stdin/file piping and savings report"
  - hash: 45668e5
    task: 3
    message: "test(01-03): zero-dependency enforcement for domain core"
  - hash: 480ebb4
    task: 4
    message: "refactor(01-03): CLI integration tests, subprocess piping, and __main__.py"
deviations: []
---

## What Was Built

- CLI adapter (`cli/main.py`) that pipes text through CompressionPipeline: reads stdin or file arg, outputs compressed text to stdout, reports token savings (original/compressed/ratio) to stderr
- `__main__.py` enabling `python -m token_sieve` invocation
- `[project.scripts]` entry point: `token-sieve` console script
- Zero-dependency enforcement tests: subprocess import with stripped sys.path + source-level import analysis against `sys.stdlib_module_names`
- PassthroughStrategy and CharEstimateCounter in CLI module for Phase 1 wiring
- 8 CLI tests (unit + integration + subprocess) and 2 zero-dep tests

## Files Modified

- `src/token_sieve/cli/__init__.py` -- created, module marker
- `src/token_sieve/cli/main.py` -- created, CLI entry point with main(), run(), create_pipeline()
- `src/token_sieve/__main__.py` -- created, python -m token_sieve support
- `pyproject.toml` -- added [project.scripts] token-sieve entry
- `tests/unit/cli/__init__.py` -- created, test module marker
- `tests/unit/cli/test_main.py` -- created, 8 tests covering stdin/file/error/integration
- `tests/unit/domain/test_zero_deps.py` -- created, 2 zero-dependency enforcement tests
