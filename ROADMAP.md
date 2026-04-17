# EntireContext Roadmap

_Updated against codebase on 2026-04-16._

## Product Thesis

EntireContext should become the system that helps coding agents accumulate engineering judgment over time.

The goal is not to store more agent history. The goal is to make past decisions, lessons, and feedback reappear at the exact moment they can improve the next code change.

In short:

`capture -> distill -> retrieve -> intervene`

## What We Are Optimizing For

1. Better decisions in repeated coding workflows
2. Less context loss across sessions, repos, and agents
3. Reuse of past lessons before mistakes repeat
4. Strong git grounding for trust, auditability, and rewindability

## Current Position

The project already has broad infrastructure in place:

- capture hooks for sessions, turns, checkpoints, and tool activity
- git-aware rewind, attribution, and checkpoint history
- hybrid retrieval across search, AST, graph, dashboard, and MCP tooling
- futures assessments, feedback loops, lessons, and trend reporting
- sync, filtering, export, and consolidation for operating the memory layer

That foundation is useful, but it is broader than the product wedge. The next phase should narrow EntireContext around **decision memory for coding agents**, not expand it horizontally as a generic memory platform.

The main implementation hardening gap still on the table is sync merge/retry policy alignment between runtime and docs.

## v0.2.0 (Shipped 2026-04-15)

- [x] **Define a first-class decision model**
- [x] **Make retrieval proactive, not just query-based** (#42)
- [x] **Staleness and contradiction handling** (#39)
- [x] **Sync merge/retry 정책 정비** (P2, spec §10 #4)

## v0.3.0 — Close the Loop (Shipped 2026-04-17)

Theme: close the decision-memory feedback arc — retrieval records its footprint, extraction quality gets validated, outcome data flows back into ranking.

- [x] **E1. `include_contradicted` default flip** (#69)
  - Breaking change committed in v0.2.0 deprecation notice
  - Flip `True→False` in `fts_search_decisions`, `hybrid_search_decisions`, `list_decisions`, `ec_decision_search`

- [x] **E2. Retrieval telemetry completeness** (#70)
  - SessionStart hook: add `record_retrieval_event` + `record_retrieval_selection`
  - PostToolUse hook: add `record_retrieval_selection`
  - Include `selection_id` in fallback Markdown for downstream outcome recording

- [x] **E3. Extraction validation & noise gate** (#71)
  - Session noise gate: ≥1 checkpoint OR ≥3 turns with files_touched
  - Confidence recalibration, dedup audit
  - Enable `auto_extract=true` safely

- [x] **E4. Relevance-based reactivation** (#72)
  - Upgrade SessionStart from file-list lookup to full `rank_related_decisions` ranker
  - Signal assembly: uncommitted diff, recent commit files, checkpoint SHA

- [x] **E5. Minimal quality loop** (#73)
  - `ec_context_apply` → auto-record "accepted" outcome
  - SessionEnd: infer "ignored" for surfaced-but-unacted decisions (config-gated)
  - Surface `quality_score` in retrieval output

## Later

- [ ] **Sharpen product messaging around decision memory**

- [ ] **Decision quality loop (full)**
  - Measure which decisions actually improve later changes
  - Use outcomes to improve ranking and distillation quality

- [ ] **Team policy and review memory**
  - Capture recurring team preferences, review heuristics, and architectural constraints
  - Separate repo-local norms from cross-repo lessons

- [ ] **Sync and runtime hardening**
  - Resolve merge/retry policy alignment in the sync engine
  - Test divergent shadow-branch conflict scenarios

- [ ] **UserPromptSubmit decision surfacing**
  - Requires async worker pattern (currently SYNC handler)

## Done Foundations

- [x] Capture hooks, checkpoints, rewind, and attribution
- [x] Hybrid search, AST search, graph/dashboard tooling, and MCP exposure
- [x] Futures assessments, typed relationships, feedback, lessons, and trend analysis
- [x] Async workers, filtering, export, consolidation, and cross-repo support

## Exploration

- **Temporal queries** — how decisions and lessons change over time
- **Agent learning reports** — where prior guidance helped and where it was ignored
- **Decision packs by area** — reusable memory bundles for domains like sync, testing, or search
- **Human-in-the-loop correction UX** — fast review of extracted decisions and stale lessons

## Non-Goals for This Phase

- Becoming a generic knowledge management system
- Expanding dashboard or graph breadth before retrieval quality improves
- Storing more raw transcripts without better distillation
- Adding platform surface area that does not reinforce the decision-memory loop

## References

- [Agent Memory Landscape Research](docs/research/agent-memory-landscape.md)
