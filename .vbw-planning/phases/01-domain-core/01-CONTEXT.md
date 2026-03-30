# Phase 1: Domain Core — Context

Gathered: 2026-03-30
Calibration: architect

## Phase Boundary
Define domain interfaces, value objects, entities, and the CompressionPipeline service. Include CLI test harness for verification. Pure Python, zero external dependencies. This phase produces the inner layer of the Hexagonal Architecture — all subsequent phases wrap around it.

## Decisions

### Compression Interface Typing
- **ContentEnvelope** as the compression boundary type (not raw ToolResult)
- ContentEnvelope is a thin value object: `content: str`, `content_type: ContentType`, `metadata: dict[str, Any]`
- Acts as the anti-corruption layer between the MCP/tool domain and the compression domain
- Strategies never see ToolResult, SessionContext, or other infrastructure concepts
- Enables reuse beyond MCP — any content source can create an envelope

### Pipeline Composition Model
- **Content-routed pipeline** — different strategy chains per ContentType
- Routes: `dict[ContentType, list[PipelineStep]]` with a default/fallback route
- Phase 1 implements 1-2 routes (default + one specific type)
- Each route is a small, independently testable chain
- ContentEnvelope.content_type drives the routing — natural extension of the envelope decision

### Token Counting
- **Dual mode** — CharEstimateCounter as zero-dep default, TokenCounter Protocol for injection
- Domain core ships with `CharEstimateCounter` (~chars/4, ~75% accurate)
- Phase 2 injects `TiktokenCounter` for production accuracy (~99%)
- TokenBudget accepts optional `TokenCounter` — falls back to char estimate
- Tests use the built-in estimate by default (no mocking needed for most tests)

### Session State Persistence
- **Repository Protocol** — `SessionRepository` interface with get/save operations
- Phase 1: `InMemorySessionRepo` (20 lines, works for testing)
- Phase 2: `SQLiteSessionRepo` (data survives restarts, enables Phase 3 learning)
- Consistent with Hexagonal Architecture — persistence is an adapter, not a domain concern
- Event-sourcing can be added later inside the repository implementation if Phase 4 needs it

### Compression Observability
- **CompressionEvent as first-class domain value object**
- Every pipeline step emits: strategy, content_type, before_tokens, after_tokens, duration_ms, timestamp
- CompressedResult carries `events: list[CompressionEvent]`
- Phase 4 dashboard and self-tuning read events directly — no retrofit needed
- VBW/plugin integration: events are the data source for external metrics queries

### Plugin Integration (VBW, GSD, etc.)
- **MetricsCollector Protocol** added to domain core
- `record(event)`, `session_summary()`, `strategy_breakdown()`
- Phase 1: `InMemoryMetricsCollector`
- Phase 2: exposed as MCP resources for any plugin to query
- Token-sieve is transparent to plugins — sits below the plugin layer as an MCP proxy
- Tool names must not clash with backend MCP servers (namespace decision deferred to Phase 2)

### Open (Claude's discretion)
- Exact ContentType enum values (CODE, DOC, CLI_OUTPUT, JSON, UNKNOWN — can evolve)
- PipelineStep interface details (sync vs async — start sync, async in Phase 2 if needed)
- CLI test harness UX (stdin pipe vs file argument vs both)

## Deferred Ideas
- Event-sourcing inside SessionRepository (evaluate in Phase 4 if needed)
- MCP resource naming scheme for metrics (Phase 2 decision)
- Tool namespace strategy — transparent proxy vs own namespace (Phase 2 decision)
- VBW statusline integration specifics (Phase 2-4)
