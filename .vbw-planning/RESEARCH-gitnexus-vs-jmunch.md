---
title: GitNexus vs jCodeMunch/jDocMunch — Research & Integration Ideas for token-sieve
date: 2026-04-09
scouts: 2 (parallel, sonnet, balanced effort)
status: findings only — no Phase 10 plan yet
---

# GitNexus vs jMunch — Research for token-sieve

## 1. Framing — they solve different problems

- **jMunch is a *retrieval optimizer*.** Thesis: agents waste tokens reading whole
  files when they only need one symbol or one doc section. Builds a lightweight
  AST + heading index once, then serves precise slices. Unit of value =
  **tokens saved per fetch**.
- **GitNexus is a *reasoning substrate*.** Thesis: agents waste *decisions* when
  they can't see the call graph, the blast radius, or how components cluster
  functionally. Builds a heavy persistent property graph once, then answers
  questions that static search simply can't. Unit of value = **decisions
  unlocked per call**.

They occupy adjacent layers. For a token-savings project like token-sieve,
that distinction matters.

Key insight: jMunch compresses *what you read*. GitNexus compresses *what you
need to read in the first place* by answering the question directly from a
graph. Both save tokens, but via orthogonal mechanisms: one shrinks payloads,
the other eliminates round-trips.

## 2. Head-to-head comparison

| Axis | jCodeMunch | jDocMunch | GitNexus |
|---|---|---|---|
| Primary role | Code retrieval | Doc retrieval | Code reasoning graph |
| Tool count (MCP) | 26 | 14 | 16 |
| Language coverage | 54 langs via tree-sitter (17+ full symbol extraction) | 10+ doc/structured formats | 15 langs via tree-sitter |
| Stack | Python, PyPI, local index | Python, PyPI, `~/.doc-index/` | **Node.js/TypeScript**, LadybugDB graph, ONNX |
| Indexing model | Single-pass AST, incremental | Byte-precise section index | 8-stage pipeline (import→call→type→Leiden→process→BM25+vec) |
| Query model | Symbol name, fuzzy, path, regex, hybrid | Weighted keyword, stable section IDs | **Cypher + hybrid BM25+semantic+RRF** |
| Storage | Local (unspecified format) | `~/.doc-index/` | `.gitnexus/` LadybugDB + `~/.gitnexus/registry.json` |
| Output bounds | Per-tool limits, summary-first | Summary-first + `_meta` envelope with `tokens_saved` | `limit`, `max_symbols`, `include_content=false` default — **but `cypher` is unbounded** |
| Claimed savings | 95%+ vs full-file reads (92–98% benchmarks) | Up to 95% (12K→400 example) | **None documented** |
| Unique powers | Blast radius, PageRank, cycles, hotspots, layer violations, `audit_agent_config`, `plan_turn` | `get_doc_coverage`, broken links, OpenAPI-aware | **Leiden communities, process/flow tracing, cross-repo `group_sync` Contract Registry, graph-assisted coordinated rename with confidence** |
| License | Dual: free personal, $79–$1999 commercial | Same dual model | **PolyForm Noncommercial — commercial use requires paid license from akonlabs.com** |
| Maturity | 1.5k stars, 2 open issues, last commit Jan 2025 (stale-ish) | 137 stars, 1 open issue | **25.6k stars, ~2.8k forks, 159 open issues, viral Feb 2026, actively churning (KuzuDB→LadybugDB migration)** |
| Install friction into Python project | Zero (pip) | Zero (pip) | **Non-trivial (Node runtime + subprocess/HTTP bridge)** |
| Cross-repo | No | No | **Yes (`group_*` tools)** |
| Git diff integration | `get_changed_symbols` | — | `detect_changes` + `impact` chain |
| Cross-session memory | No | No | No (but graph persists per repo) |

## 3. jMunch — complete tool surface (from repos)

### jCodeMunch (26 tools)

`index_folder`, `index_file`, `index_repo`, `search_symbols`, `get_symbol_source`,
`get_file_outline`, `get_file_content`, `get_file_tree`, `get_repo_outline` /
`summarize_repo`, `search_text`, `find_importers`, `get_blast_radius`,
`get_class_hierarchy`, `get_call_hierarchy`, `find_dead_code`,
`get_changed_symbols`, `get_symbol_importance` (PageRank), `get_hotspots`
(complexity × churn), `get_dependency_cycles`, `get_coupling_metrics`,
`get_layer_violations`, `plan_turn`, `get_ranked_context` (token-budgeted),
`audit_agent_config`, `discover_tools`, `explain_compression`.

### jDocMunch (14 tools)

`index_local`, `doc_index_repo`, `doc_list_repos`, `delete_index`, `get_toc`,
`get_toc_tree`, `get_document_outline`, `search_sections`, `get_section`,
`get_sections`, `get_section_context`, `get_broken_links`, `get_doc_coverage`,
`explain_compression`.

Both implement the jMRI (jMunch Retrieval Interface) spec from
`mcp-retrieval-spec`. Summary-first retrieval pattern. Both expose
`explain_compression` for session-level token accounting. Sibling j*munch
repos: `jdatamunch-mcp`, `jOutputMunch`, `jMunchWorkbench`.

## 4. GitNexus — complete tool surface (16 MCP tools)

| Tool | What it does |
|---|---|
| `list_repos` | Enumerate indexed repos |
| `query` | Hybrid BM25 + vector search, ranked execution flows |
| `cypher` | Raw Cypher query against graph → Markdown table (unbounded) |
| `context` | 360° symbol view: callers, callees, processes, location |
| `impact` | Blast-radius analysis with risk level |
| `detect_changes` | Map git diffs to affected symbols + processes |
| `rename` | Graph-assisted coordinated rename with confidence |
| `route_map` | API route → handler → middleware chain |
| `tool_map` | Tool definition → handler files |
| `shape_check` | Route response shape vs. consumer property access |
| `api_impact` | Route-level blast radius |
| `group_list` | Multi-repo group configs |
| `group_sync` | Build Contract Registry across repos |
| `group_contracts` | Query contracts in a group |
| `group_query` | Hybrid search across a repo group (RRF-merged) |
| `group_status` | Staleness per repo in group |

Architecture: 8-stage pipeline — scan → tree-sitter parse → import resolve →
call resolve → type fixpoint (5-phase SCC) → Leiden community detection →
process detection → BM25 + ONNX semantic indexing. Persistent LadybugDB graph
under `.gitnexus/`. `~/.gitnexus/registry.json` global registry. Ships
first-class MCP server; community npm wrapper exists
(`@iflow-mcp/abhigyanpatwari-gitnexus`).

## 5. Pros / cons

### jMunch family

**Pros**
- Python-native, zero friction inside token-sieve
- 66 total MCP tools across the two — widest tool surface of the three
- Friendly dual license; commercial path cheap
- jMRI spec means both servers share conventions → easy to extend
- `audit_agent_config`, `plan_turn`, `get_ranked_context` are genuinely unique
- Already battle-tested in our daily workflow

**Cons**
- jCodeMunch last commit early 2025 — likely dormant, key-person risk (`jgravelle` alone)
- No cross-repo analysis, no runtime data, no NL semantic by default
- No knowledge graph / entity relationships
- jDocMunch star count (137) → small community, bus factor concern

### GitNexus

**Pros**
- Precomputed call graph is a category difference — millisecond callers/callees/processes
- Leiden community detection → automatic functional clusters
- Cross-repo Contract Registry (`group_*`) — multi-service blast radius in one call
- `detect_changes` → `impact` chain = risk-scored PR previews in one workflow
- Active, viral, well-maintained; MCP server ships ready
- Cypher escape hatch for unbounded expressiveness

**Cons**
- **License is the blocker.** PolyForm Noncommercial. Any commercial deployment of
  token-sieve that bundles GitNexus becomes legally fraught.
- **Node.js runtime** in a Python codebase = subprocess/HTTP bridge
- **Storage churn**: KuzuDB → LadybugDB in under a year → production red flag
- **Cypher is a footgun**: no pagination, unbounded output
- **No non-code file support** — Markdown/YAML/JSON excluded; jDocMunch covers this gap and cannot be replaced
- **8 GB heap cap, 8 concurrent queries** — non-trivial memory footprint at index time
- **No documented token-savings benchmarks** — token savings is not its design goal
- **159 open issues** — active but unstable

## 6. Direct answer: which is "better"?

| Criterion | Winner |
|---|---|
| Token savings (published benchmarks + per-response accounting) | **jMunch, not close** |
| Number of tools | **jMunch (66 across two) > GitNexus (16)** — but tool count misleads; GitNexus's 16 are architecturally deeper |
| Novel capabilities token-sieve doesn't have today | **GitNexus wins the creativity axis** — Leiden, cross-repo contracts, process flows, risk-scored blast radius |
| Fit with our Python stack | **jMunch by a wide margin** |
| License safety for a project that may commercialize | **jMunch** |

**Recommendation:** Keep jCodeMunch + jDocMunch as primary daily drivers. Do NOT
replace them. Instead, *selectively steal GitNexus's best ideas* — either by
running it alongside for specific workflows, or by reimplementing its core
graph primitives inside token-sieve where the license and stack friction bite.

## 7. Creative integration ideas (ranked by ROI × novelty)

### Idea 1 — GitNexus as a compression adapter test subject (Phase 10 fit) ✓
GitNexus's `cypher` is unbounded and verbose → perfect adversarial test case for
token-sieve's progressive-disclosure strategy. Wrap GitNexus as an adapter, feed
Cypher results through our existing `ProgressiveDisclosureStrategy` +
`FileRedirectStrategy`. Benefits: killer demo ("we make the hottest AI tool of
2026 actually usable"), generates per-adapter audit fixtures Phase 10 needs,
surfaces regressions via a heavyweight real-world adapter. Lowest-cost,
highest-PR-value integration.

### Idea 2 — Leiden clusters as a compression prior ✓
GitNexus runs Leiden community detection on the call graph: "function X belongs
to the auth cluster with 12 siblings." Steal the concept: when a user reads one
symbol, `get_ranked_context` / `ProgressiveDisclosureStrategy` discloses
*cluster peers* instead of textual neighbors. **Structural progressive
disclosure** — a novel compression strategy for Phase 10. You don't need
GitNexus at runtime; run a Leiden pass over the jCodeMunch call graph.
Implement inside token-sieve, avoid the license problem entirely.

### Idea 3 — Blast-radius as a cache coherence oracle ✓
`cache_design_debt`: fuzzy cache disabled due to 30% false-hit rate; Phase 10
needs parameter-aware keys. `impact` gives the exact set of symbols affected by
a change, ranked by depth. Use as **cache invalidation signal**: when a file
changes, invalidate only cached tool responses whose input paths intersect the
impacted symbol set. Blast-radius becomes a semantic cache coherence protocol.
Can be built on jCodeMunch's `get_blast_radius` (already exists!) — no GitNexus
required. **Probably the single most valuable idea in this list.**

### Idea 4 — Dual-MCP intelligent router (leverages Phase 4 schema virtualization) ✓
Phase 4 DietMCP already virtualizes MCP schemas. Extend it to expose a unified
`code_intelligence.*` namespace that dispatches to the best backend:
- `code_intelligence.find(symbol)` → jCodeMunch `get_symbol_source`
- `code_intelligence.impact(symbol)` → jCodeMunch `get_blast_radius` OR GitNexus `impact`
- `code_intelligence.clusters()` → GitNexus `cypher` (Leiden) with fallback
- `code_intelligence.doc_for(symbol)` → jDocMunch `get_doc_coverage` + `get_section`

Agent sees one tool family; token-sieve routes, compresses, caches, and falls
back. Solves the daily "which tool do I use?" friction.

### Idea 5 — PreToolUse hook collision audit ○
**Surprising fact worth investigating urgently:** GitNexus also uses Claude
Code PreToolUse hooks (it auto-injects graph context). token-sieve operates in
the same layer. Two possibilities:
- **Conflict:** ordering issues, double-injection, enrichment bypassing compression
- **Composition:** GitNexus enriches → token-sieve compresses → agent gets graph context for free

Before any runtime integration, do a focused day of hook-ordering testing. If
composition works, token-sieve becomes the "graph-aware compressing proxy" for
free, with zero code.

### Idea 6 — `detect_changes` + `impact` as a PR review compressor ○
New token-sieve workflow: given a git diff, call GitNexus `detect_changes` →
`impact`, compress the response. Agent reviewing a PR gets a ranked risk
summary instead of re-reading every changed file. jCodeMunch
`get_changed_symbols` gives you a weaker version today; stacking GitNexus adds
risk scoring and cross-module tracing. Killer workflow for code review
assistants built on top of token-sieve.

### Idea 7 — Use jCodeMunch `audit_agent_config` on token-sieve's own CLAUDE.md ○
Meta-win: we have a large global CLAUDE.md and project-specific guidance. Run
`audit_agent_config` on ourselves in CI to detect token waste, stale rules,
dead references. Freebie, eats our own dogfood. Scheduled job post-Phase-10.

### Idea 8 — Contract Registry for token-sieve's MCP adapters ○
GitNexus's `group_sync` validates HTTP contracts across microservices.
token-sieve has 28 adapters with their own envelope contracts (Phase 9 audit).
Steal the pattern: build a "compression contract registry" enforcing adapter
envelope shapes across versions. Answers a Phase 10 backlog item
("per-adapter audit fixtures") with a proven architectural pattern. Steal the
idea, don't ship the dep.

### Idea 9 — Feed Leiden clusters into the learning store ○
Phase 3 built a SQLite learning store + statistical reranker. Add Leiden
cluster IDs as features: "when a query touches cluster `auth-middleware`, boost
results from the same cluster." Gives the reranker structural priors for free.

### Idea 10 — Replace Phase 6 tree-sitter extractor with GitNexus ⚠ REJECTED
Tempting on paper — covers same language set and more — but don't do this.
(a) License blocker, (b) Node runtime in Python project, (c) schema churn drag,
(d) we already ship and tests pass. Record as "considered and rejected."

### Idea 11 — Bundle GitNexus as a token-sieve dependency ⚠ REJECTED
License blocker. Optional "bring your own GitNexus" config flag is fine;
bundling is not.

## 8. Concrete next-step ranking

1. **Idea 3** (blast-radius cache oracle) — highest ROI, uses existing jCodeMunch, slots into Phase 10. No new deps. Ship first.
2. **Idea 2** (Leiden clusters as compression prior) — novel research angle, publishable. Implement inside token-sieve.
3. **Idea 4** (dual-MCP router via schema virtualization) — leverages Phase 4. Makes token-sieve visibly smarter.
4. **Idea 5** (hook collision audit) — must-do *before* any GitNexus integration; one day of work.
5. **Idea 1** (GitNexus as adapter test) — PR value, helps Phase 10 audit coverage gap.
6. **Ideas 6, 7, 8, 9** — backlog.

## 9. Confidence

- **High ✓:** tool counts, language coverage, licensing facts, architecture comparisons, Python vs Node friction, jMunch maturity signals
- **Medium ○:** the "viral 25.6k stars Feb 2026" figure on GitNexus (single-source, plausible but not cross-checked); the claim that GitNexus hooks will compose cleanly with ours (needs Idea 5 to verify)
- **Low ⚠:** specific token-count estimates for a GitNexus `context` or `query` response — no published benchmarks

## 10. Caveats to flag

- **`cypher` is an unbounded footgun.** Any integration exposing `cypher` to an agent must go through token-sieve compression first. Don't hand `cypher` raw to Claude.
- **License.** PolyForm Noncommercial is not permissive. If token-sieve ever ships a paid tier, a hosted service, or is used inside a commercial product, you cannot bundle or hard-require GitNexus. Plan every integration as optional, runtime-detected, and replaceable.
- **Storage churn.** Two graph DB rewrites in a year (KuzuDB → LadybugDB). Don't build deep dependencies on GitNexus internals; stay at the MCP tool surface.

## Sources

- https://github.com/abhigyanpatwari/GitNexus
- https://deepwiki.com/abhigyanpatwari/GitNexus
- https://www.npmjs.com/package/@iflow-mcp/abhigyanpatwari-gitnexus
- https://github.com/jgravelle/jcodemunch-mcp
- https://github.com/jgravelle/jdocmunch-mcp
- `mcp-retrieval-spec` (jMRI v1.0 specification)

---

## 11. Hook Collision Audit (Follow-up)

*Added 2026-04-09. Third Scout pass (sonnet, balanced). Source-backed investigation
of Idea 5 from §7 — does GitNexus's Claude Code hook layer conflict with
token-sieve's?*

### 11.1 Verdict

**✓ Composition — with one silent-degradation caveat.**

Claude Code runs all matching hooks **in parallel** (not chained), and both
systems use **different delivery paths** — so neither installer can clobber the
other. GitNexus only emits `additionalContext` (never rewrites `updatedInput`),
so there's **no active write conflict** today. The one real caveat: GitNexus's
PostToolUse Bash staleness check reads `tool_output`, and when token-sieve
rewrites Bash to the compressor wrapper, that output is transformed — GitNexus
may silently miss git-mutation patterns. No errors, just a degraded
reindex-detection signal.

### 11.2 Evidence — token-sieve hook footprint

Read directly from `src/token_sieve/cli/setup.py` (lines 360–542) and
`src/token_sieve/hooks/*.sh`:

- **PreToolUse only** — zero PostToolUse hooks installed anywhere.
  ⚠ **Surprising gap:** the project's value prop mentions PostToolUse but the
  actual installer footprint is Pre-only. Orthogonal architectural finding
  worth tracking separately from this audit.
- 6 entries installed:
  - Advisory echoes on matchers `Grep`, `Glob`, `Read`, `Bash` (non-blocking,
    exit 0, advisory text only — jCodeMunch / ctx_execute suggestions)
  - `bash-compress-rewrite.sh` on matcher `Bash` — rewrites `tool_input.command`
    via `updatedInput` to wrap in
    `TSIEV_WRAP_CMD=<orig> python3 -m token_sieve compress --wrap-env` (D1 rewrite)
  - `webfetch-redirect.sh` on matcher `WebFetch` — blocks and redirects to
    `ctx_fetch_and_index`
- **Installer behavior:** `install_hooks()` reads existing `settings.json`,
  backs up, appends entries to `data["hooks"]["PreToolUse"]` (an array).
  Dedup by marker string (`"token-sieve"`). Never overwrites existing entries.
  Idempotent on re-runs.
- **Delivery path:** writes directly to `~/.claude/settings.json` (user-level)
  or project-level.

### 11.3 Evidence — GitNexus hook footprint

Read directly from `gitnexus-claude-plugin/hooks/hooks.json` and
`gitnexus-claude-plugin/hooks/gitnexus-hook.js` on GitHub:

- `PreToolUse` — matcher: `"Grep|Glob|Bash"` — runs `gitnexus-hook.js`,
  timeout 10s, status "Enriching with GitNexus graph context..."
- `PostToolUse` — matcher: `"Bash"` only — same script, status
  "Checking GitNexus index freshness..."
- **Hook behavior:**
  - PreToolUse: extracts search pattern from `tool_input`, calls
    `gitnexus augment` to fetch related call-graph context, emits JSON
    with `hookSpecificOutput.additionalContext` injected into Claude's
    context window.
  - PostToolUse: compares current HEAD against last-indexed commit in
    `.gitnexus/meta.json`; notifies agent if reindex needed.
  - **Critically: does NOT emit `updatedInput`** — context-only injection.
    Fails open. No exit 2.
- **Delivery path:** Claude plugin system (`hooks.json` in plugin dir), **not**
  direct `settings.json` mutation. Merged at plugin-enable time.

### 11.4 Evidence — Claude Code hook model

Confirmed from https://code.claude.com/docs/en/hooks (directly fetched):

- **Multiple hooks per event: YES.** `hooks.PreToolUse` is an array of
  matcher-group objects, each containing a `hooks` array of handlers.
- **Ordering:** all matching hooks run **in parallel**. No serial chaining.
  A hook cannot modify what another hook sees.
- Each hook reads the **same original stdin** independently.
- `additionalContext` from multiple hooks is concatenated.
- `updatedInput` collision: docs don't specify merge winner; last-writer-wins
  race. Not active today because GitNexus doesn't emit it.
- Decision precedence (PreToolUse): `deny > defer > ask > allow`.
- Plugin hooks merge with user/project hooks automatically.
- Identical handler commands are deduplicated.

### 11.5 Failure modes (ranked)

| # | Mode | Risk | Active today? |
|---|---|---|---|
| FM-1 | Parallel `updatedInput` race on Bash | ✓ High (latent) | **No** — GitNexus doesn't rewrite. Active only if GitNexus ever adds command rewriting. |
| FM-3 | GitNexus PostToolUse staleness regex runs on token-sieve's compressed Bash output | ○ Medium | **Yes** — silent degradation, no errors |
| FM-2 | GitNexus's graph context describes original Bash command, not wrapper | ○ Medium | **Cosmetic** — semantically correct for user intent |
| FM-4 | Ordering within parallel array | ✓ Documented | **No** — parallel execution makes ordering moot |
| FM-5 | `settings.json` corruption from naive GitNexus CLI installer | ⚠ Low / unverified | Plugin delivery path observed; `gitnexus setup` CLI not inspected |

### 11.6 Composition behavior per tool

- **Grep / Glob** → ✓ clean: GitNexus enriches, token-sieve advisory-echoes. Both visible to Claude.
- **Bash** → ✓ works, with FM-3 caveat: token-sieve rewrites, GitNexus enriches original intent, PostToolUse may miss drift patterns in compressed output.
- **WebFetch** → ✓ clean: token-sieve blocks+redirects, GitNexus has no WebFetch hook.
- **Read** → ✓ clean: token-sieve advisory only, GitNexus no hook.

### 11.7 Test plan (reproducible today)

1. `cat ~/.claude/settings.json | python3 -m json.tool | grep -A 200 PreToolUse` — baseline
2. `token-sieve setup --install-hooks` + enable GitNexus plugin → re-inspect
3. `CLAUDE_DEBUG=hooks claude -p "run: ls /tmp"` → confirm both fire, inspect rewrite + context
4. `CLAUDE_DEBUG=hooks claude -p "grep for 'def install_hooks' in this project"` → confirm clean composition
5. In a GitNexus-indexed test repo: `git commit --allow-empty -m test`, then `Bash("git log --oneline -1")` via Claude → verify whether GitNexus PostToolUse still fires reindex notification against the compressed output (FM-3 check)

### 11.8 Upstream asks

**token-sieve (minor):**
- If a PostToolUse hook is ever added, follow the additive/dedup pattern already used for Pre. Document this contract explicitly.
- Consider emitting a structured `additionalContext` string (e.g., `"token-sieve: N tokens saved"`) so both systems' presence is visible side-by-side in Claude's context.

**GitNexus (moderate):**
- Document that `tool_output` may be a compressed/transformed representation if a companion compression tool is active. Fall back to HEAD comparison (not output regex) when a `TSIEV_COMPRESSED` marker is present.
- Document whether the `gitnexus setup` CLI writes `settings.json` directly. If it does, it must use the additive array pattern.

**Joint (nice-to-have):**
- A shared hook execution trace format (e.g., `{"system": "token-sieve|gitnexus", "hook": "...", "matcher": "...", "action": "rewrite|enrich"}` to stderr with `CLAUDE_DEBUG=hooks`) would make empirical testing clean.

### 11.9 Surprising facts

- **token-sieve installs ZERO PostToolUse hooks** — despite the layer being referenced in the project's value proposition, the entire hook footprint is PreToolUse-only. GitNexus owns the PostToolUse Bash slot entirely and faces no competition there. ✓ high (read directly from `_SCRIPT_HOOK_ENTRIES`).
- **GitNexus hooks are delivered via the Claude plugin system**, not by mutating `settings.json` directly. A user who inspects `settings.json` manually after installing both will only see token-sieve's entries; GitNexus's are invisible there. Makes the combined state harder to audit. ✓ high.
- **Claude Code runs all matching hooks in parallel with no serial chaining.** The commonly assumed mental model of "hook A runs first, then hook B sees A's output" is **wrong**. Each hook reads the same original stdin. This means hook systems can't *chain* — they can only *decorate*. Any "graph-aware compressed proxy" design must treat enrichment and compression as parallel contributions, not a pipeline. ✓ high (directly from Claude Code docs).

### 11.10 Confidence on this audit

- ✓ **High:** token-sieve installer behavior, GitNexus hook manifest + script, Claude Code parallel execution semantics, verdict of "composition works today"
- ○ **Medium:** FM-3 severity in practice (needs Test 5 to quantify), FM-2 cosmetic vs. real impact
- ⚠ **Low:** GitNexus `gitnexus setup` CLI behavior (not inspected), whether any managed-policy hook override exists that could change the picture

### 11.11 Impact on §7 ideas

- **Idea 5 (hook collision audit) — RESOLVED.** Verdict above is sufficient to de-risk it. No further audit needed before Phase 10 starts; only the ~1-hour FM-3 empirical test (Test 5) remains as optional validation.
- **Idea 4 (dual-MCP intelligent router) — REFRAME.** My original framing implied sequential enrichment ("GitNexus enriches → token-sieve compresses"). Because hooks run in parallel, the router must be implemented at the **MCP tool layer** (where token-sieve schema-virtualizes), not at the hook layer. The hook layer can only *decorate* in parallel.
- **NEW finding: token-sieve PostToolUse gap** — orthogonal to GitNexus but surfaced by this audit. Either dead code in the value prop or a missing feature. Worth a Phase 10 sub-plan or a backlog entry in its own right.
