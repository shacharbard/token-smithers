---
phase: 1
plan: 2
title: "Domain Services: Pipeline, Session, Counters, Metrics"
status: complete
tasks_total: 5
tasks_completed: 5
tasks_failed: 0
test_count: 83
coverage: 100
deviations: []
commits:
  - hash: "e08519d"
    task: 1
    message: "feat(01-02): CompressionPipeline service with content-routed strategy chains"
  - hash: "6c2cf75"
    task: 2
    message: "feat(01-02): CharEstimateCounter with chars/4 token estimation"
  - hash: "d1499e7"
    task: 3
    message: "feat(01-02): InMemorySessionRepo and SessionContext entity"
  - hash: "d8b52a7"
    task: 4
    message: "feat(01-02): InMemoryMetricsCollector with event recording and summaries"
  - hash: "1684051"
    task: 5
    message: "refactor(01-02): domain public API exports and pipeline integration test"
---

## What Was Built

- CompressionPipeline: content-routed strategy chain with dict[ContentType, list[Strategy]] routing, process() returns (ContentEnvelope, list[CompressionEvent]) tuple
- CharEstimateCounter: zero-dep TokenCounter implementation using chars//4 formula (min 1 for non-empty)
- SessionContext entity: mutable dataclass with seen_hashes set and add_result_hash() dedup method
- InMemorySessionRepo: dict-backed SessionRepository with get/save roundtrip
- InMemoryMetricsCollector: list-backed MetricsCollector with session_summary() totals and strategy_breakdown() grouping
- domain/__init__.py public API exports: ContentEnvelope, ContentType, CompressionPipeline, CompressionEvent, TokenBudget, CompressedResult, CharEstimateCounter
- Pipeline integration test with real CharEstimateCounter validating end-to-end token counting

## Files Modified

- `src/token_sieve/domain/pipeline.py` -- CompressionPipeline with register() and process()
- `src/token_sieve/domain/counters.py` -- CharEstimateCounter implementing TokenCounter Protocol
- `src/token_sieve/domain/session.py` -- SessionContext entity, InMemorySessionRepo
- `src/token_sieve/domain/metrics.py` -- InMemoryMetricsCollector with record/summary/breakdown
- `src/token_sieve/domain/__init__.py` -- public API exports
- `tests/unit/domain/test_pipeline.py` -- 8 tests: routing, chaining, events, skipping, integration
- `tests/unit/domain/test_counters.py` -- 12 tests: formula validation, protocol check, parametrized
- `tests/unit/domain/test_session.py` -- 9 tests: context entity, repo CRUD, protocol compliance
- `tests/unit/domain/test_metrics.py` -- 6 tests: recording, summaries, breakdowns, empty state
