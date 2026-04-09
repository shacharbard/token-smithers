---
phase: 10
kind: phase-research
status: complete
source: pre-existing multi-scout research (2026-04-09)
---

# Phase 10 Research — Pointer + Phase-Specific Framing

## Primary Research Document

**Canonical source (READ IN FULL):**
`.vbw-planning/RESEARCH-gitnexus-vs-jmunch.md`

This document is the product of **three parallel Scout passes** conducted during the Phase 10 discussion session (2026-04-09):
- **Scout 1:** GitNexus deep dive (architecture, 16-tool MCP surface, licensing, maturity signals)
- **Scout 2:** jCodeMunch + jDocMunch complete tool inventory (66 tools across both) and capability gaps
- **Scout 3:** Hook collision audit — does GitNexus's Claude Code hook layer conflict with token-sieve's?

The document has 11 major sections:
1. Framing — retrieval optimizer vs reasoning substrate
2. Head-to-head comparison matrix
3. jMunch complete tool surface
4. GitNexus complete tool surface
5. Pros / cons
6. Direct "which is better" answer
7. **Creative integration ideas ranked by ROI × novelty** (Ideas 1–11)
8. Concrete next-step ranking
9. Confidence
10. Caveats
11. **Hook collision audit** — verdict, evidence, failure modes, composition paths, test plan, upstream asks

Phase 10 must not duplicate this research. The Lead agent should read it before planning and treat it as the evidence base for every architectural decision in this phase.

## Phase 10 Context Document

**Discussion decisions (READ IN FULL):**
`.vbw-planning/phases/10-session-intelligence/10-CONTEXT.md`

This captures the 5 gray-area resolutions from the Phase 10 discussion, the Planner Execution Constraints (sequential waves, worktree per wave, strict TDD), the Dependency Graph, the Success Criteria, and the Out-of-Scope list. Every decision in CONTEXT.md was made with the research findings in hand — do not re-litigate them.

## Phase 10-Specific Research Framing

The Phase 10 discussion surfaced three research-backed constraints that should shape the plan:

### 1. Zero external code-intelligence dependencies as the baseline (from GA2 reframe)

Per `project_target_audience.md`: token-sieve targets the broad Claude Code community, not jMunch power users. The cache coherence and structural session-context features must work on 100% of users without jCodeMunch or GitNexus installed. token-sieve **owns its own tree-sitter stack** (Phase 6 `TreeSitterASTExtractor` covers Python/TS/JS/Go/Rust/Java) — the imports graph for Tier 2 must be built on that stack, not delegated.

Research justification: §7 Idea 3 proposed using `get_blast_radius` as a cache coherence oracle. That's the right *pattern* but the wrong *substrate* — the research assumed jCodeMunch would be available. GA2 reframed this: we implement the oracle pattern ourselves, and expose jCodeMunch/GitNexus as optional plugins via the Tier 3 interface.

### 2. Sequential enrichment at the hook layer is not possible (from §11 hook collision audit)

Per hook collision audit verdict: Claude Code runs all matching hooks for an event **in parallel** — they read the same original stdin independently and cannot chain. This means:
- GitNexus integration (if ever added) enriches via `additionalContext` **in parallel** with token-sieve's compression hooks, not before them
- The "dual-MCP router" idea (§7 Idea 4) must be implemented at the **MCP tool layer** (Phase 4 schema virtualization), not the hook layer
- token-sieve's own PostToolUse metrics hook (GA5) runs in parallel with any other PostToolUse hooks — it must be decoration-only, never a rewrite

Research justification: §11.11 explicitly marked Idea 4 as "reframe required" — the original mental model of pipeline composition was wrong. The plan for Phase 10 must not assume sequential hook chaining.

### 3. GitNexus runtime integration is blocked by FM-3 empirical test (from §11.5)

Per hook collision audit Failure Mode FM-3: GitNexus's PostToolUse Bash staleness check reads `tool_output`, and token-sieve's Bash wrapper rewrites that output. A silent degradation exists where GitNexus may miss reindex signals against compressed output. Before any GitNexus runtime dependency, the Phase 10 plan should include an optional verification task (FM-3 Test 5 from §11.7) — but **this test is not blocking** Phase 10 since the Tier 3 plugin interface ships with a stub, not a live adapter.

Research justification: §11.11 marked Idea 5 (hook collision audit) as "RESOLVED — only the ~1hr FM-3 empirical test remains as optional validation." The plan should allocate the test as a de-risk task but should not gate any wave on its outcome.

## Key Research Findings That Map to Phase 10 Deliverables

| Phase 10 Deliverable | Research Source | Design Implication |
|---|---|---|
| Cache coherence (GA2 / Tier 1) | §7 Idea 3 + §6 "fit with stack" analysis | Content-hash manifest is industry-standard; zero deps |
| Cache coherence (GA2 / Tier 2) | §7 Idea 3 reframed + §2 comparison matrix | token-sieve owns tree-sitter, can build imports graph internally |
| Cache coherence (GA2 / Tier 3) | §7 Idea 4 + §11.11 reframe | Plugin oracle interface at adapter layer, not hook layer |
| Session context (GA4) | §7 Idea 2 (Leiden clusters as prior) | Simpler proxy: imports-graph connected components |
| Intent (GA3) | §7 Idea 2 secondary signal | Cluster-tag signal feeds intent mode detection |
| PostToolUse metrics (GA5) | §11.9 + `project_output_compression_strategy.md` | Observational only; cannot replace built-in output |
| Adversarial gaps | §11.5 FM-3, FM-5 | FM-3 as optional test, FM-5 not applicable (we don't run GitNexus setup CLI) |
| Target audience alignment | `project_target_audience.md` | Every Tier-1 feature must work with zero external deps |

## Out of Scope for Phase 10 (from research)

- **Full PostToolUse output rewriting via CLI wrapper pattern** — §7 Idea 6 is really a Phase 11+ architectural track, not a single deliverable
- **Leiden community detection** — §7 Idea 2. Connected components are a simpler proxy for Phase 10; Leiden can be added in a later phase if the CC signal proves too coarse
- **Bundling GitNexus or hard-requiring it** — §7 Idea 11 rejected due to PolyForm Noncommercial license
- **Replacing Phase 6 tree-sitter extractor with GitNexus** — §7 Idea 10 rejected (license + Node dep + schema churn + already working)
- **Dual-MCP router** — §7 Idea 4 must be implemented at the MCP tool layer (Phase 4 extension), not hook layer. Phase 11 or 12 candidate.
- **`audit_agent_config` on our own CLAUDE.md** — §7 Idea 7. CI cron post-Phase-10, not phase work.

## How to Use This Document

Lead agent: **do not re-summarize the research**. Read the canonical file (`.vbw-planning/RESEARCH-gitnexus-vs-jmunch.md`) directly and read this framing document alongside it. Use the Phase 10 Context document (`10-CONTEXT.md`) as the source of truth for decisions already made — it supersedes anything in the research if they disagree (the research is the evidence base; CONTEXT is the decisions made on top of that evidence).
