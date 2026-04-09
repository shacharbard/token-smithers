---
updated: 2026-04-09
gathered: 2026-04-09
phase: 10
phase_slug: session-intelligence
mode: architect
---

# Phase 10 — Session Intelligence: Discuss

## Goal

Reduce tokens in long Claude Code sessions by 30–70% via conversation-aware compression, tiered cache coherence, structural session-context tracking, intent inference, and enhanced cross-session learning. Target: 30–50% in typical sessions, up to 70% for iterative debugging workflows. Pay off the Phase 3 fuzzy-cache debt and the Phase 9 non-determinism residue along the way.

## Why This Phase Exists

Phase 9 shipped output compression for built-in tools, lifting tool-traffic coverage from ~20–30% to ~60–70% and proving the PreToolUse hook layer can host load-bearing compression logic without breaking Claude workflows. But Phase 9 gains are *per-call*. In long sessions the bigger opportunity is *cross-call*: the same files get read repeatedly with slight variations, agents re-derive context across modes, the reranker invalidates prompt caches on every `list_tools`, and the cache has been running with fuzzy matching disabled since Phase 3 due to a 30% false-hit rate.

Phase 10 turns token-sieve from a stateless compressor into a session-aware intelligence layer. The thesis: compress *what Claude already knows*, not just each payload in isolation.

A third-scout research pass this session also surfaced a dependency decision: most Claude Code users will not have jCodeMunch or GitNexus installed. The cache coherence and structural session-context features must work with **zero external code-intelligence dependencies** as the baseline. This phase therefore introduces token-sieve's *own* imports-graph layer built on the Phase 6 tree-sitter infrastructure.

## Gray Areas — Resolved Before Plan

Five gray areas were discussed. All five resolved. Decisions below; full reasoning in §Discussion Log.

### GA1 — Scope framing & hygiene bundle
**Decision:** **Maximal scope.** Ship 5 ROADMAP deliverables + Phase 9 hygiene warm-up (4 items) + `compress.py` threading refactors (`_run_async` / `_run_async_bool` cleanup + sync/async removal).

### GA5 — PostToolUse hook gap
**Decision:** **Metrics-only PostToolUse hook** (matcher `*`, writes tool-call outcomes to Phase 3 learning store). Not output rewriting. ~1–2 days of work. Full CLI-wrapper-based output rewriting stays deferred to Phase 11+.

### GA2 — Cache coherence strategy
**Decision:** **All three tiers + parameter-aware keys.** Tier 1 content-hash manifest (universal, zero deps), Tier 2 imports-graph via token-sieve's own tree-sitter (Phase 6 infrastructure), Tier 3 optional jCodeMunch/GitNexus plugin oracle interface, plus parameter-aware cache keys for non-file-scoped tools.

### GA4 — Session context tracking substrate
**Decision:** **MinHash + imports-graph cluster tags.** Primary substrate is MinHash for content similarity; secondary signal is connected-component ID from the Tier 2 imports graph. Bloom filter rejected (exact-match only, too weak for rephrased/partial content).

### GA3 — Intent-aware compression shape
**Decision:** **Rule-based n-gram pattern matching + cluster-tag secondary signal.** Hand-authored tool-call n-gram rules detect modes (research / debugging / exploration / refactor / test-fix) and produce budget multipliers that modify existing adapter budgets. Cluster tags from GA4 feed in as a secondary signal. Statistical classifier and LLM inference both rejected — determinism bias and corpus-availability issues.

## Out of Scope for This Phase

The following surfaced during discussion or research and are explicitly *not* part of Phase 10. Log them in backlog rather than stretching the phase:

- **Full PostToolUse output rewriting via CLI wrapper pattern** (Phase 11+; the `project_output_compression_strategy.md` track; architectural pivot with its own adversarial review)
- **Adapter audit coverage gap** — 10 of 28 adapters skip the envelope audit (Phase 9 backlog). Fits a dedicated audit cleanup pass, not Session Intelligence.
- **VBW plugin bugs** — commit-format hook false positive on double-`-m`, worktree isolation gitignore bug. Upstream, not our code.
- **Statistical intent classifier** — deferred until the rule-based baseline has produced a labeled training corpus.
- **LLM-based intent inference** — architecturally wrong for a compression proxy (non-determinism, cost, flakiness).
- **GitNexus runtime integration** — the hook collision audit resolved composition works today (GitNexus only emits `additionalContext`), but FM-3 empirical validation (Step 5 in `.vbw-planning/RESEARCH-gitnexus-vs-jmunch.md` §11.7) should precede any runtime dependency. Not blocking Phase 10; Tier 3 plugin interface can be implemented against a stub.
- **Extracting the imports-graph as a standalone MCP server** (`timporsmunch`?) — bonus idea from the cache-coherence discussion. Worth considering post-Phase-10 as a community contribution.

## Deferred Ideas (captured for post-Phase-10 consideration)

- **Publishing "tiered cache coherence" as a research contribution** — novel in the MCP space; worth a blog post or paper after Phase 10 ships and generates benchmark numbers.
- **Leiden community detection on the imports graph** — GitNexus research Idea 2. Not shipping in Phase 10 (imports-graph connected components are a simpler proxy). Could be added as a richer clustering layer in a later phase if the connected-component signal proves too coarse.
- **Auto-grooming `~/.claude/CLAUDE.md` via `audit_agent_config`** — GitNexus research Idea 7. Meta-dogfooding win; schedule as CI cron post-Phase-10.
- **Dual-MCP intelligent router** — GitNexus research Idea 4. Must be implemented at the MCP tool layer (Phase 4 schema virtualization extension), not the hook layer, per hook-collision audit §11.11. Candidate for Phase 11 or 12.

## Planner Execution Constraints (user-directed, 2026-04-09)

These constraints override the project's default wave execution strategy for Phase 10. Decision made after discussion, driven by the phase's risk profile (`compress.py` refactor touching core compression paths + long critical-path chain Tier 2 → session context → intent).

### Wave execution: strictly sequential
- **No parallel waves.** Each wave runs to completion before the next begins.
- Phase 7/8/9 used parallel waves with worktree isolation as a throughput optimization. Phase 10 explicitly trades throughput for risk reduction.
- Rationale: Phase 10 has a long critical-path dependency chain and a load-bearing `compress.py` refactor. A parallel wave failing mid-way through would force a merge-conflict cleanup on top of an already-large phase envelope. Sequential execution makes each wave's failure mode independent and easy to unwind.

### Worktree isolation: mandatory per wave
- **Every wave runs in its own dedicated git worktree** — even though they are sequential, not parallel.
- Worktree is created at wave start, merged into `main` at wave end, removed after merge.
- Each wave starts from a clean, verified `main` HEAD.
- Rationale: isolates WIP from the main working tree, lets the user inspect main during wave execution without interference, and matches `feedback_worktree_isolation.md` guidance.
- **Carry Phase 9 wave 5 lesson forward** (`project_phase09_gotchas.md`): worktree isolation does not reliably copy gitignored files including `.vbw-planning/`. Dev agents must either (a) explicitly copy the planning directory into the worktree at spawn time, or (b) run non-isolated against the existing worktree path if the planning copy fails. The Dev spawn procedure should include a worktree-planning-copy preflight check.

### TDD: strict RED → GREEN → REFACTOR, no exceptions
- **Every production code change must have a failing test first.** No exceptions for "trivial" changes.
- Follow existing `feedback_tdd_enforcement.md` and `feedback_tdd_commit_separation.md`:
  - RED commit lands separately from GREEN commit (Dev agents commit the failing test before writing production code)
  - Confirm each new test fails for the *right reason* before writing the fix (not a setup error)
  - REFACTOR phase is optional but must keep tests green
- **Monitor dev agents in real time** per `feedback_monitor_agents.md` — do not fire-and-forget. The orchestrator watches for TDD violations and intervenes immediately.
- **Contract tests for every new Protocol** per `feedback_tdd_enforcement.md` — this matters especially for the Tier 3 `BlastRadiusOracle` Protocol and the intent-mode budget-modulation interface.

### Post-merge hygiene per wave
Per `feedback_editable_install_pollution.md`, after every wave merge:
1. `pip install -e .` from project root
2. Verify import path (`python -c "import token_sieve; print(token_sieve.__file__)"` resolves to the working tree, not stale site-packages)
3. Run full pytest suite green before starting the next wave
4. Only then begin the next wave's worktree

### Checkpoint before compress.py refactor wave
The `compress.py` refactor wave is the single highest-risk wave in this phase. Before starting it:
- All prior waves merged and green on main
- Full test suite green (all 1627+ tests)
- A `compress.py`-focused regression guard: a dedicated test file that exercises the current threading workarounds (`_run_async`, `_run_async_bool`) end-to-end, verifying behavior, *before* the refactor begins. This test must stay green through the refactor.
- No other work in flight during this wave

## Discussion Log

### D1 — GA1 Scope framing & hygiene bundle

**Question:** Pure ROADMAP deliverables only, or bundle with Phase 9 hygiene and `compress.py` refactors?

**Recommendation:** ROADMAP + 4-item hygiene warm-up wave (2 DEVN-05 test failures + 2 non-determinism fixes).

**User decision:** Maximal scope — ROADMAP + hygiene warm-up + `compress.py` threading refactors (`_run_async` / `_run_async_bool` cleanup, sync/async removal).

**Rationale:** Addresses more debt in one phase rather than spinning up a dedicated cleanup phase later. Accepts the risk of a larger phase envelope and more complex wave sequencing.

**Planner guidance (downstream implication):**
- Wave structure **must quarantine** the `compress.py` refactor from Session Intelligence features. `compress.py` is load-bearing for every compressed tool call; the refactor wave needs its own regression guard (full existing-behavior test suite run green before *and* after) and should not share a wave with new feature work.
- Suggested ordering: `hygiene warm-up → compress.py refactor (isolated wave) → Tier 1 cache → Tier 2 imports graph → Tier 3 plugin stub + parameter-aware keys → MinHash session context + cluster tags → intent rules → PostToolUse metrics hook → result diffing / learning auto-tune`. Exact ordering is planner's call; this is a sketch.
- Hygiene items:
  - `tests/unit/adapters/embed/test_model2vec_embedder.py::TestModel2VecEmbedder::test_repr` (DEVN-05, ~5 min fix)
  - `tests/unit/cli/test_stats_command.py::TestStatsCommand::test_stats_prints_formatted_table` (DEVN-05, ~5 min fix)
  - `FileRedirectStrategy` — dict ordering non-determinism (Phase 9 wave 5 audit, marked `deterministic=False`)
  - `ProgressiveDisclosureStrategy` — timestamp non-determinism (Phase 9 wave 5 audit, marked `deterministic=False`)

---

### D5 — GA5 PostToolUse hook gap

**Question:** Address the "zero PostToolUse hooks" finding from hook-collision audit §11.9 in Phase 10, or defer?

**Recommendation:** Metrics-only PostToolUse hook in Phase 10. Full output rewriting deferred.

**Clarification discussion:** User asked for a complexity and time comparison between a metrics-only hook and full PostToolUse output compression. The comparison revealed that "full PostToolUse output compression" is a misleading label — per `project_output_compression_strategy.md`, PostToolUse hooks in Claude Code **cannot actually replace built-in tool output**. The "full" option is really a PreToolUse CLI-wrapper rollout for Read/Grep/Glob, each requiring its own wave-scale effort. The two options differ by ~20–50× in effort and are categorically different types of work.

**User decision:** Metrics-only PostToolUse hook. ~1–2 days.

**Rationale:**
- Observational hook (reads `tool_output` size + `tool_name` + timing), writes rows to the Phase 3 learning store
- Matcher `*`, additive install via existing idempotent `install_hooks()` pattern
- Directly powers the "enhanced cross-session learning" ROADMAP deliverable
- Closes the documented audit gap (zero PostToolUse → one observational PostToolUse)
- Low adversarial surface: no input rewriting, no subprocess spawning, fails open

**Planner guidance:**
- New module: `src/token_sieve/hooks/posttooluse_metrics.{sh,py}` + SQLite schema migration for learning store
- Schema addition: `post_tool_use_metrics` table with columns `(tool_name TEXT, output_size_bytes INT, duration_ms INT, timestamp INTEGER, session_id TEXT)`
- Install path: extend `_SCRIPT_HOOK_ENTRIES` or a new `_POSTTOOLUSE_SCRIPT_HOOK_ENTRIES` list, wire into `install_hooks()`
- Tests: writer unit tests, hook dispatcher tests, install idempotency tests, learning store integration test — target ~15–20 new tests
- Must not conflict with GitNexus's PostToolUse Bash hook (per hook collision audit §11.6: parallel execution, both safe since neither emits `updatedInput`)

---

### D2 — GA2 Cache coherence strategy

**Question:** How do we pay off the `project_cache_design_debt` fuzzy-cache-disabled issue? Parameter-aware keys, blast-radius invalidation, or both? And how do we handle users without jCodeMunch/GitNexus?

**Initial recommendation:** Both layered, using jCodeMunch `get_blast_radius` as the AST oracle.

**User challenge:** "Most users will not have jCodeMunch and jDocMunch. So that would be an issue. Can't we use other methods that use tree sitters and stuff like that?"

**Reframe:** Per `project_target_audience.md`, the target is the broad Claude Code community, not jMunch power users. Baseline must work with zero external code-intelligence dependencies. token-sieve already owns a tree-sitter stack from Phase 6 (`TreeSitterASTExtractor` for Python/TS/JS/Go/Rust/Java) — we can extend it ourselves rather than depending on jCodeMunch.

**Decision: tiered cache coherence + parameter-aware keys.**

#### Tier 1 — Content-hash manifest (universal, zero deps)
- Every cached file-scoped tool response records `file_manifest: {path → sha256}`
- On cache lookup, re-hash each referenced path; any change → invalidate
- Works on 100% of users, every language, every filesystem
- Near-industry-standard for file-scoped MCP caching; this is table stakes
- **Planner:** new SQLite column `file_manifest` (JSON blob), hash-on-write, re-hash-on-read, fast-path when no file inputs

#### Tier 2 — Imports-only graph via token-sieve's own tree-sitter
- Extends Phase 6 `TreeSitterASTExtractor` with imports-only queries
- Languages: Python, TypeScript, JavaScript, Go, Rust, Java (Phase 6 coverage)
- Query complexity: ~10–30 lines of tree-sitter patterns per language
- Build a lightweight imports graph (not a call graph — 80% of the signal at ~10% of the implementation cost)
- When file X changes, invalidate cache entries whose manifest touches X *or any file that transitively imports X*
- **Planner:** new module `src/token_sieve/ast/imports_graph.py`, per-language query files in `src/token_sieve/ast/queries/imports/{python,typescript,javascript,go,rust,java}.scm`, graph storage alongside the Phase 6 extractor output
- **Language rollout decision deferred to planner:** all 6 in one wave vs. scripting (Python/TS/JS) in one wave + compiled (Go/Rust/Java) in another

#### Tier 3 — Optional plugin oracle (power users)
- Protocol: `BlastRadiusOracle` (hexagonal adapter interface per `user_architecture_preference.md`)
- Runtime detection: probe for jCodeMunch and/or GitNexus MCP servers
- Delegate blast-radius queries to them when available for better precision + PageRank weighting
- Never required; never on the critical path
- **Planner:** Protocol + adapter stub + runtime detection + delegation wiring; GitNexus adapter blocked on FM-3 empirical test from hook audit §11.7

#### Parameter-aware keys (orthogonal baseline)
- For non-file-scoped tools (WebFetch results, stats queries, search)
- Engineer exact cache keys including normalized parameters rather than fuzzy matching
- Pays off `project_cache_design_debt` directly for the tool-types that can't use the blast-radius approach
- **Planner:** extend cache key function in the cache module; feature flag `cache.fuzzy_matching` stays off; new flag `cache.blast_radius_enabled` with auto-detect default

**Rationale:**
- Universal baseline: Tier 1 alone is a fully working cache coherence story for every user regardless of installed tools
- token-sieve owns the moat: Tier 2 is a native capability no other MCP compressor has
- Leverages existing Phase 6 infrastructure
- Publishable contribution: "tiered cache coherence with automatic tier detection"
- Matches DDD/hexagonal/plug-and-play architecture preference
- Still pays off `cache_design_debt` via the parameter-aware keys dimension

**Planner guidance:**
- Tier 2 is the load-bearing piece; if it slips, Tier 3 and the GA4 cluster-tag signal both degrade
- Feature flag default: `cache.blast_radius_enabled = "auto"` (detect Tier 2 at startup)
- Tier 3 plugin surface must be testable without the actual external tool installed (use mocks/fakes)

---

### D4 — GA4 Session context tracking substrate

**Question:** Bloom filter vs MinHash vs structural tracking (cluster-based) for session context dedup?

**Recommendation:** MinHash + imports-graph cluster tags.

**User decision:** Accepted recommendation.

**Rationale:**
- Claude sessions contain rephrased, partially-overlapping content — similarity is the right question, not exact match
- MinHash O(1) amortized lookups with tunable precision via `(num_perm, threshold)` knobs
- Cluster tags are free metadata once GA2 Tier 2 exists — every tracked item gets a connected-component ID from the imports graph
- Reranker uses both signals: content similarity + cluster membership ("seen this cluster already → compress harder; new cluster → preserve context")
- Bloom filter rejected: "have I seen exactly this?" is too weak for actual Claude session patterns
- Avoids betting the phase on the experimental Leiden approach (connected components are a simpler, proven proxy)

**Planner guidance:**
- Library: `datasketch` (pure Python, stable, no native deps)
- New module: `src/token_sieve/session/context_tracker.py` — MinHash signature computation, storage, similarity lookup
- **Hard dependency on GA2 Tier 2** — the cluster-tag half of this feature does not function until the imports graph exists
  - Options: (a) sequence Tier 2 wave strictly before session-context wave; (b) ship MinHash-only in an early wave and add cluster tags in a follow-up wave once Tier 2 lands. Planner should pick based on wave parallelizability analysis.
- Tests: MinHash signature determinism, similarity-threshold tuning, cluster-tag assignment correctness, reranker integration

---

### D3 — GA3 Intent-aware compression shape

**Question:** Rule-based, statistical classifier, LLM inference, or drop-and-replace with clusters?

**Recommendation:** Rule-based n-grams + cluster-tag secondary signal.

**User decision:** Accepted recommendation.

**Rationale:**
- Rules are declarative, testable, deterministic — aligns with token-sieve's determinism bias (Phase 9 D4)
- Fit in a single Python file with a lookup table of n-gram patterns
- Statistical classifier rejected: no labeled corpus yet; rule-based baseline will *produce* the corpus for a later classifier
- LLM inference rejected: breaks determinism, adds cost, architecturally wrong for a compression proxy
- Cluster-only rejected: misses non-structural signals like `Read×10` (skimming) that don't correlate with cluster membership

**Concrete rule sketch (planner to refine):**
- `(Grep → Read → Edit)` → **debugging** — compress seen files harder, preserve diff context
- `(WebFetch → Read → Read)` → **research** — preserve more context per fetch, less aggressive truncation
- `(Bash → Bash → Bash)` → **exploration** — aggressive truncation, surface summaries
- `(Read × N, same file tree)` → **skimming** — progressive disclosure levels up
- `(Edit → Bash:test → Edit)` → **test-fix loop** — aggressive cache reuse, similar-file compression
- `(Glob → Read → Grep)` → **refactor** — preserve call-graph context

**Planner guidance:**
- The novel work is **not** the rules themselves (shallow) — it's the wiring: mode → budget multiplier → per-adapter budget adjustment
- New module: `src/token_sieve/intent/detector.py` — n-gram pattern matcher with configurable rule table; `src/token_sieve/intent/budget_modulation.py` — mode → adapter-budget-multiplier mapping
- Integration point: existing compression pipeline reads budget from config; add a modulation layer that applies `mode_multiplier × base_budget`
- Cluster-tag secondary signal: when a tool call touches a cluster the session has already visited, bias toward the "debugging" multiplier even if the n-gram pattern hasn't fired yet
- Tests: rule matching determinism, n-gram sliding window correctness, budget modulation integration with existing adapters, cluster-tag signal propagation
- 1–2 waves of effort; rules themselves are small, the integration surface is where the work lives

---

## Dependency Graph (for planner)

```
hygiene warm-up (D1)  ──────────┐
                                │
compress.py refactor (D1)  ─────┼──> core stability for everything downstream
                                │
Tier 1 content-hash cache (D2) ─┤
                                │
Tier 2 imports graph (D2)  ─────┼──> required by Tier 3 + MinHash cluster tags + intent cluster signal
                                │
Tier 3 plugin oracle (D2)  ─────┤    (depends on Tier 2 for the interface shape)
                                │
param-aware keys (D2)  ─────────┤    (orthogonal to Tier 1-3)
                                │
MinHash session context (D4) ───┼──> required by intent cluster-tag signal
                                │    (cluster-tag half depends on Tier 2)
                                │
intent rules (D3)  ─────────────┤    (cluster-tag signal depends on D4 + Tier 2)
                                │
PostToolUse metrics hook (D5) ──┤    (independent, small, can land any wave)
                                │
result diffing (ROADMAP)   ─────┤    (orthogonal; planner handles in plan)
                                │
learning auto-tune (ROADMAP) ───┘    (depends on PostToolUse metrics for fresh data)
```

**Critical path:** `compress.py refactor → Tier 2 imports graph → MinHash session context → intent rules`. This is the longest chain; Tier 1 + param-aware keys + PostToolUse hook can parallelize.

## Success Criteria (for QA)

- 30–50% token savings in typical long sessions (measured via session stats report)
- Up to 70% savings in iterative debugging workflows (measured via seeded scenario benchmarks)
- Zero non-determinism findings in Phase 10 adapter audit (pays off Phase 9 residue)
- Cache coherence: ≥95% correct invalidation in Tier 1 test scenarios, ≥90% in Tier 2
- PostToolUse metrics hook: 100% of tool calls recorded to learning store (matcher `*`)
- All existing Phase 9 tests stay green through `compress.py` refactor
- Tier 3 plugin surface ships with at least one working adapter (jCodeMunch) and a documented stub for GitNexus

## References

- `.vbw-planning/ROADMAP.md` — Phase 10 definition
- `.vbw-planning/RESEARCH-gitnexus-vs-jmunch.md` — all sections; §7 (Ideas 1–11), §11 (hook collision audit), §11.11 (impact on ideas)
- `~/.claude/projects/.../memory/project_phase10_backlog.md` — hygiene items, per-adapter audit, compress.py simplification, sync/async removal, VBW plugin bugs
- `~/.claude/projects/.../memory/project_cache_design_debt.md` — fuzzy cache disabled, 30% false-hit rate
- `~/.claude/projects/.../memory/project_output_compression_strategy.md` — why PostToolUse cannot replace built-in tool output
- `~/.claude/projects/.../memory/project_target_audience.md` — broad Claude Code community, not jMunch power users
- `~/.claude/projects/.../memory/user_architecture_preference.md` — DDD, hexagonal, plug-and-play
- `~/.claude/projects/.../memory/reference_claude_code_hooks_parallel.md` — hooks decorate in parallel, not chain
- `~/.claude/projects/.../memory/project_phase09_gotchas.md` — non-determinism residue, locale scope, worktree bugs, editable install pollution
- Phase 6 `TreeSitterASTExtractor` — infrastructure reused by Tier 2 imports graph
- Phase 3 SQLite learning store — consumer of PostToolUse metrics hook
- Phase 4 DietMCP schema virtualization — extension point for deferred "dual-MCP router" (GitNexus research Idea 4)
