---
date: 2026-04-27
topic: product-roadmap
focus: 제품 방향성과 로드맵
mode: repo-grounded
---

# Ideation: EntireContext Product Direction & Roadmap

## Grounding Context

**Codebase:** Python 3.12+ CLI + MCP server (v0.5.0). Core loop: `capture → distill → retrieve → intervene`. Decision memory anchored to git commits/checkpoints. Schema v13. FTS5 + hybrid BM25 + optional dense vector. Non-goals: generic KM, dashboard breadth before retrieval quality, raw transcript storage without distillation.

**Key architecture facts:** 5 hook types (SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd). Dual output: stdout (Claude Code additionalContext) + session-scoped .md file. Named PID files for worker coordination. 5-second SessionEnd budget. Retrieval hierarchy: ec_decision_context → explicit queries → ec_related/ec_search → ec_lessons.

**ROADMAP direction:** v0.6.0 = F5 outcome type enum + schema v14. Exploration horizon: temporal queries, agent learning reports, decision packs, human-in-the-loop correction UX.

**External context:** Closest competitors (Memorix, Letta Context Repos, mcp-mem0) all lack git-anchored turn replay — EC's moat. DORA 2025: 90% AI adoption → 154% larger PRs, 9% more bugs. LOCOMO benchmark: retrieval memory 40x faster than full context. MCP memory left to ecosystem by MCP roadmap.

## Ranked Ideas

### 1. Proactive Decision Injection
**Description:** `UserPromptSubmit` hook auto-scores the incoming prompt against the decision/lesson corpus and injects top-k relevant records into `additionalContext` before the model sees the message. Paired with a Context Budget Optimizer (token cap + confidence threshold) to prevent noise injection.
**Warrant:** `direct:` `hooks/handler.py` UserPromptSubmit entry point + `additionalContext` write path already exist; `decisions.ranking` config section already defined in schema. AGENTS.md "proactively use EntireContext before answering" rule depends on manual lookup today — gap evidence.
**Rationale:** Low retrieval compliance stems from friction, not bad intent. Push delivery converts retrieval from opt-in discipline to default behavior, closing the loop the spec mandates but can't enforce.
**Downsides:** Low-relevance injection degrades prompt quality; token cost increase; confidence threshold tuning required.
**Confidence:** 92%
**Complexity:** Medium
**Status:** Explored

### 2. Temporal Query Language (TQL)
**Description:** Add `--at <commit-or-tag>`, `since:v0.3.0`, `between:2026-01-01..2026-03-31` syntax to all search/retrieval commands. Queries evaluate against the memory state as it existed at a specific git commit or date range.
**Warrant:** `direct:` `decision_commits` + `decision_checkpoints` tables in schema v13 already record git anchors for every decision — range-filter infrastructure exists. ROADMAP.md Exploration: "temporal queries — how decisions and lessons change over time."
**Rationale:** "Time-travel searchable memory anchored to git state" is EC's core differentiator claim. TQL makes it literally true and demonstrable, not just architectural. No competitor offers this.
**Downsides:** Query parser addition + propagation to all retrieval paths; `around:` window-size edge cases; breaking change risk if syntax conflicts with existing filter args.
**Confidence:** 88%
**Complexity:** Medium
**Status:** Explored

### 3. `ec blame` — Decision-Annotated Git Blame
**Description:** `ec blame <file> [line]` traverses `decision_commits` → `decision_checkpoints` → decision records backward from the commit that last touched the line, returning the originating decision's rationale and rejected alternatives. Answers "why does this code exist?" instead of "who wrote it?"
**Warrant:** `direct:` `blame_cmds` module exists in CLI architecture; `decision_commits` + `decision_checkpoints` FK tables provide the traversal join path; `attributions` table links turns to files.
**Rationale:** "Why does this code exist?" is the most valuable unanswered question in every codebase. EC is the only tool that can answer it — this makes that capability explicit and discoverable.
**Downsides:** `blame_cmds` may be stub-only; initial coverage low (many lines will return "no record") until Retroactive Archaeology bootstraps history.
**Confidence:** 85%
**Complexity:** Medium
**Status:** Explored

### 4. Retroactive Git Archaeology (`ec archaeologize`)
**Description:** One-time or periodic command walks `git log --patch` + merged PR bodies/review comments through the existing decision extraction pipeline, generating a `source:inferred` bootstrapped decision corpus. Makes EC immediately useful on any repo with history, eliminating the cold-start problem.
**Warrant:** `direct:` `core/decisions/` extraction pipeline already processes text → decision candidates; stateless per-commit, requiring only a new CLI command that iterates `git log`. Lore Protocol (arXiv 2603.15566) confirms PR review threads as highest-signal implicit decision source.
**Rationale:** Cold-start is the largest adoption barrier. A 5-year-old repo with zero EC history has no day-1 value. Archaeology converts existing git history into a pre-populated decision ledger.
**Downsides:** Slow on large repos; inferred decisions need lower confidence defaults; `gh api` dependency for PR mining; requires human review queue (ec review) to validate quality before use.
**Confidence:** 80%
**Complexity:** Medium-High
**Status:** Explored

### 5. Agent Learning Report (After-Action Digest)
**Description:** `SessionEnd` hook auto-generates a structured AAR: `[N new decisions | M lessons applied | K stale decisions reversed | net learning score]`. Rolling 30-session window tracks learning velocity. Delivered via SessionStart additionalContext on the first session of a new day or week.
**Warrant:** `direct:` `SessionEnd` hook already runs `maybe_extract_decisions` + ignored-outcome inference — the data exists in memory, needs only aggregation + formatting. ROADMAP.md Exploration: "agent learning reports" explicitly listed.
**Rationale:** Without a learning report, memory quality is a black box. Showing trajectory ("3 new canonical lessons, 1 stale decision reversed this week") creates a feedback loop that incentivizes capture hygiene.
**Downsides:** "Learning score" definition is subjective; per-session noise risk — needs threshold to suppress empty/trivial reports. Rolling-window computation adds SessionEnd latency.
**Confidence:** 90%
**Complexity:** Low-Medium
**Status:** Explored

### 6. Alive Session Memory (Rolling WAL Capture)
**Description:** Every `PostToolUse` event writes turn content to a durable append-only JSONL shard immediately. `core/async_worker.py` background thread consolidates into main DB on a rolling 30-second window. `SessionEnd` becomes a finalization step, not the only write path. Crash-safe for long-running CI and multi-hour agent tasks.
**Warrant:** `direct:` `core/async_worker.py` exists; `turn_content.content_path` already uses JSONL as the storage primitive. Named PID file pattern (existing) handles worker slot contention.
**Rationale:** Long-running agentic tasks (8-hour CI repairs, large refactors) currently lose all session memory on crash or timeout. Rolling flush converts EC from "best-effort capture" to "durable event log."
**Downsides:** Increased SQLite WAL write frequency; async_worker slot contention (mitigated by named PID files); 5-second SessionEnd budget constraint (rolling flush is always background, no budget impact).
**Confidence:** 83%
**Complexity:** Medium
**Status:** Explored

### 7. Decision Diffing / Contradiction Detection
**Description:** On every new decision write, run a lightweight `fts_decisions` keyword-overlap check against existing decisions covering the same files or keywords. Compute a contradiction score; above threshold, auto-generate a `decision_outcomes` record with `outcome_type: contradicted` and surface the conflict.
**Warrant:** `direct:` `fts_decisions` FTS5 virtual table enables keyword-overlap detection without dense embeddings; `decision_outcomes.outcome_type` already has `contradicted` state support. Unbounded append without contradiction detection is the principal long-term memory corruption risk.
**Rationale:** A memory system that silently accumulates contradictions actively misleads future agents. Contradiction detection at write time converts EC from an append log into an auditable knowledge base.
**Downsides:** FTS5 keyword overlap ≠ semantic contradiction; high false-positive risk without dense vector path; threshold tuning required; may generate correction noise in early stages.
**Confidence:** 78%
**Complexity:** Medium
**Status:** Explored

## Rejection Summary

| # | Idea | Reason Rejected |
|---|------|-----------------|
| 1 | Git Notes Export | Duplicates Decision Pack Export; git namespace pollution |
| 2 | Semantic Retrieval Smoke Test | CI/QA task; below roadmap ambition floor |
| 3 | MCP as De Facto Memory Standard | No concrete buildable feature; positioning strategy |
| 4 | Parallel Agent Memory Bus | SQLite WAL sufficient for current scale; premature |
| 5 | Adversarial Failure Injection | Implementation path unclear; subsumed by Regression Fingerprint |
| 6 | Outcome Blind Tracks | Internal research methodology; not user-facing |
| 7 | Gitless Anchor | FK schema disruption disproportionate to benefit |
| 8 | Procedural Memory Lanes | Workflow sequence extraction unclear; likely expensive ML |
| 9 | Capture Gap Attribution | Subsumed by Retroactive Archaeology |
| 10 | MCP/CLI Parity Enforcer | CI test task; not a product roadmap item |
| 11 | Hook Health Dashboard | Ops monitoring; lower leverage vs core retrieval improvements |
| 12 | Decision Precedent Chains | Valid for v0.6.0 breaking track; second-tier priority |
| 13 | Decision Debt Score | Valid but secondary to capture/retrieval loop improvements |
| 14 | Cross-Session Lesson Deduplication | Quality improvement; not a standalone roadmap driver |
| 15 | Memory Stratigraphy | Covered more generically by TQL |
| 16 | Team Memory / Decision Registry | High value but infrastructure-heavy for current maturity |
| 17 | Regression Fingerprint | High false-positive risk; requires Proactive Injection maturity first |
| 18 | Adaptive Decision Half-Life | Second-order improvement; not a standalone driver |
| 19 | Decision Keystone Detection | Supporting feature for Decision Pack Export |
| 20 | Decision Provenance Seal | Audit feature; low direct impact on agent behavior |
| 21 | `ec review` HITL Correction | Valid (ROADMAP-referenced); lower leverage vs capture/retrieval |
| 22 | Context Budget Optimizer | Supporting feature for Proactive Injection; subsumed |
| 23 | IDE-Agnostic Capture | Runner-up (#8); strong leverage but only `external:` warrant |
| 24 | Decision Pack Export | Valid; Archaeology solves cold-start; packs are a later layer |
