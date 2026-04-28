# EntireContext Roadmap

_Updated against codebase on 2026-04-27._

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

With v0.4.0 the loop now feeds itself — outcomes flow into ranking and extraction, and UserPromptSubmit opens a new signal channel. v0.5.0 hardened the loop by closing 3x-deferred correctness debt before adding new feature surface.

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

## v0.4.0 — Feed the Loop (Shipped 2026-04-17)

Theme: deepen the decision-memory loop so outcome data flows into both ranking and extraction, and add UserPromptSubmit as a new retrieval signal channel.

Plan reference: `~/.claude/plans/v0-4-0-streamed-pond.md`.

- [x] **F1. Outcome recency decay** (#83 merged)
  - Time-decayed contribution in `calculate_decision_quality_score`
  - New config `[decisions.quality] recency_half_life_days` (default 30)
  - Single-outcome smoothing (`min_volume`) to avoid ranking swings

- [x] **F2. Outcome → extraction feedback (penalty only)** (#84 merged)
  - `run_extraction` penalises candidate confidence when the candidate's files have historical contradicted outcomes
  - Ratio gate to limit false positives; accepted-boost deferred to v0.5 to avoid self-reinforcing loops
  - New config `[decisions.extraction] outcome_feedback_*`

- [x] **F3. Ranking weight config** (#85 merged)
  - `[decisions.ranking]` section replaces hardcoded `_STALENESS_FACTORS`, `_ASSESSMENT_RELATION_WEIGHTS`, and file/commit signal weights
  - Defaults unchanged; `score_breakdown` keys stable (additive only)

- [x] **F4. UserPromptSubmit async decision surfacing** (#86 merged)
  - Prompt text redacted in-memory before any tmp write, then `launch_worker` for ranking
  - Worker assembles prompt + diff + recent commits signals and writes `.entirecontext/decisions-context-prompt-<session>-<turn>.md`
  - Gated by `[decisions] surface_on_user_prompt` (default off)

- [x] **E2E coverage** (`tests/test_e2e_feed_the_loop.py`)
  - Single scenario wires F1 decay + F2 penalty + F3 ranking config + F4 surfacing against one repo and one decision
  - Verifies contradicted-default filter (negative assertion), O_EXCL 0600 tmp mode, turn-scoped filename, and end-to-end redaction of `sk-[A-Za-z0-9]{48}` patterns through hook → tmp → worker → Markdown

Scope note: outcome type enum extension (`refined`/`replaced`) was originally scoped here as F5 but is deferred to the v0.6 breaking track so the enum change + schema v14 + automatic recording paths land together in one release. Held out of v0.5.0 to keep the "Stabilize the Loop" theme free of schema bumps.

## v0.5.0 — Stabilize the Loop (Shipped 2026-04-27)

Theme: close the 3x-deferred correctness debt before adding new feature surface — zero new product features, zero schema changes.

Holding hardening separate from the same-day v0.3.0 → v0.4.0 release pattern (no soak window) so unfixed atomicity and transaction-control debt does not compound under more product weight.

- [x] **S1. `confirm_candidate` atomicity** (D.4)
  - `src/entirecontext/core/decision_candidates.py:92-224` currently uses CAS-claim + per-helper internal commits because `create_decision`/`link_decision_to_*` each commit independently. A crash between step 2 and step 3 leaves the candidate in `confirmed` state with `promoted_decision_id IS NULL`.
  - Resolve via single outer transaction (refactor helpers to commit-free) OR add a recovery detector that re-promotes orphaned `confirmed` rows on next access.
  - References: ec decisions `e59c78eb` (original D.4), `4c7893b0` (promotion to v0.5.0 primary).

- [x] **S2. `LEGACY_TRANSACTION_CONTROL` migration** (D.5)
  - `src/entirecontext/core/context.py:18` and `tests/test_transaction_helper.py:4` rely on Python 3.12's legacy transaction mode. Re-verify under Python 3.13+ autocommit semantics before claiming cross-version support.
  - Decide: migrate to autocommit (preferred) or pin to Python 3.12 with explicit support note.
  - References: ec decision `dcc64267`.

- [x] **S3. F4 subprocess-path E2E**
  - `tests/test_e2e_feed_the_loop.py:213` runs the prompt surfacing worker in-process (direct function call), so F4's security model — `O_EXCL` + `0600` tmp file (`turn_capture.py:90`), detached subprocess isolation (`turn_capture.py:76`), worker-side defense-in-depth re-redaction (`decision_prompt_surfacing.py:184`) — is not exercised end-to-end.
  - Add a new integration test (separate file or named subtest) that launches the actual subprocess, plants a raw secret in the tmp file, and asserts: (a) tmp created with `O_EXCL` + `0600`, (b) worker re-applies redaction even when tmp contains raw secrets, (c) tmp removed in success and failure paths, (d) symlink at tmp path is rejected.
  - References: ec decision `03ab3e25`.

- [x] **S4. Review-bot noise reduction** (D.6)
  - `.github/workflows/claude-code-review.yml` and `.github/workflows/tidy-pilot.yml` produce sticky comments on every `synchronize` event regardless of substance (claude[bot] = 71% of inline comments in v0.2.0 audit; PR #59 stale-commit race + PR #55 test-comment garbage as concrete noise instances).
  - Apply at minimum: `concurrency: cancel-in-progress` on review workflow + remove the explicit "Skip the already reviewed check entirely" directive (`.github/workflows/claude-code-review.yml:40-43`). Tighter `paths` filter and post-push cooldown are stretch.
  - Validation: open a no-op PR after the change and verify only one review run completes.
  - References: ec decision `eaa24b32`.

Scope note: F5 (outcome type enum extension `refined`/`replaced` + schema v14 migration) is intentionally held out of v0.5.0 and deferred to v0.6.0's breaking track. Mixing schema bumps into a hardening release would re-introduce the exact "feature on top of correctness debt" risk that v0.5.0 is designed to close (per ec decision `4c7893b0`). v0.5.0 ships zero schema changes — still v13.

E2E coverage note: v0.5.0 does not need a single integrated E2E like v0.4.0's `test_e2e_feed_the_loop.py` because S1–S4 each have their own focused integration test. S3 in particular IS the missing E2E for v0.4.0's F4.

## v0.6.0 — Outcome Semantics (Breaking Track)

Theme: strengthen the decision outcome lifecycle — agents can distinguish guidance that was accepted, ignored, contradicted, refined, or replaced. Narrow scope: outcome recording and ranking behavior only. No extraction confidence changes, no storage rework beyond the minimum for outcome semantics.

Plan reference: `docs/brainstorms/v0-6-0-roadmap-plan.md`.

- [x] **F5. Outcome type enum expansion** (deferred from v0.4.0)
  - Add `refined` and `replaced` outcome types to `decision_outcomes.outcome_type`
  - Schema v14 migration: rebuild constrained table safely, preserve existing rows, recreate indexes, test v13→v14 migration and rollback behavior
  - Define and document the outcome truth table: quality score signal, staleness auto-promotion, successor-chain mutation, extraction confidence effect for all five types (`accepted`, `ignored`, `contradicted`, `refined`, `replaced`)

- [x] **F5a. Recording paths for expanded outcome vocabulary**
  - Manual outcome recording accepts all five outcome values through CLI and MCP
  - Existing `ec_context_apply` accepted recording remains unchanged
  - SessionEnd ignored inference remains limited to `ignored`
  - `ec decision supersede` now writes a `replaced` outcome row in the same transaction as staleness/successor updates
  - Candidate confirmation does not infer `refined` or `replaced`

- [x] **F5b. Accepted ranking verification**
  - Existing quality-score path (`accepted × 1.0`) provides the accepted ranking boost — no weight delta needed
  - `refined`/`replaced` carry weight 0 (display/audit only) — verified by regression tests
  - Accepted boost stays out of extraction confidence in v0.6.0 (extraction boost deferred to v0.7.0)

- [x] **F5c. Tests and documentation**
  - Tests proving extraction confidence is unchanged by `refined`/`replaced` outcomes
  - README outcome vocabulary section updated with all 5 values
  - CHANGELOG v0.6.0 entry includes schema v14 breaking note and compatibility subsection

## v0.6.1 — Rejected-Alternative Quality

Theme: clean up the rejected-alternatives data shape without mutating existing records or inventing rationale.

- [ ] Rejected alternative normalization helpers in `core/decisions.py` accepting legacy strings and structured objects
- [ ] `ec decision alternatives audit` — list reasonless, malformed, mixed, or legacy alternatives without mutating data
- [ ] `ec decision alternatives normalize` — convert legacy strings to structured objects; use `"Unknown from recorded context"` for missing reasons
- [ ] `ec decision alternatives set` or equivalent manual update command for explicit structured replacements
- [ ] Tighten extraction prompts to request rejected-alternative reasons only when source text contains enough evidence; parser and candidate-confirmation paths share the same normalizer
- [ ] Tests: legacy string compatibility, malformed JSON detection, mixed arrays, empty alternatives, empty reasons, audit categories, normalization idempotency, manual set behavior

## Hardening Backlog

Structural debt outside the "decision memory depth" wedge. The three items previously listed here (`confirm_candidate` atomicity, `LEGACY_TRANSACTION_CONTROL`, review-bot noise) have been absorbed into v0.5.0 — see S1, S2, S4 above. New items go here as they are surfaced.

## Later

- [ ] **Sharpen product messaging around decision memory**

- [ ] **Team policy and review memory**
  - Capture recurring team preferences, review heuristics, and architectural constraints
  - Separate repo-local norms from cross-repo lessons

- [ ] **Decision file rename tracking**
  - Preserve historical outcome trail when `decision_files` paths are renamed or moved

## Done Foundations

- [x] Capture hooks, checkpoints, rewind, and attribution
- [x] Hybrid search, AST search, graph/dashboard tooling, and MCP exposure
- [x] Futures assessments, typed relationships, feedback, lessons, and trend analysis
- [x] Async workers, filtering, export, consolidation, and cross-repo support
- [x] Sync merge/retry policy and shadow-branch conflict handling (spec §6.3, v0.2.0)

## Exploration

Items below have been evaluated in the 2026-04-27 ideation session ([docs/ideation/2026-04-27-product-roadmap-ideation.md](docs/ideation/2026-04-27-product-roadmap-ideation.md)) and promoted to concrete candidates. Items marked "moved from v0.6.0" were initially proposed for the breaking track but fall outside the outcome-lifecycle scope defined in `docs/brainstorms/v0-6-0-roadmap-plan.md`.

- **Proactive Decision Injection** — `UserPromptSubmit` hook auto-pushes top-k relevant decisions into `additionalContext` without agent query; Context Budget Optimizer (token cap + confidence threshold) gates noise. Highest-leverage retrieval improvement — converts AGENTS.md policy from opt-in to default behavior. _(Confidence 92%, Medium complexity)_ Plan reference: `docs/brainstorms/proactive-decision-injection.md`.

- **Temporal Query Language (TQL)** — `--at <ref>`, `since:`, `between:` syntax for all search/retrieval commands; queries evaluate against memory state at a specific git commit or date. Exploits EC's unique moat (git-anchored time-travel) — no competitor offers this. _(Confidence 88%, Medium complexity)_ Plan reference: `docs/brainstorms/temporal-query-language.md`.

- **`ec blame` — Decision-Annotated Git Blame** — `ec blame <file> [line]` traverses `decision_commits` → `decision_checkpoints` → decision records to answer "why does this code exist?" with rationale and rejected alternatives. `blame_cmds` module already in CLI architecture. _(Confidence 85%, Medium complexity)_ Plan reference: `docs/brainstorms/ec-blame-decision-annotated.md`.

- **Retroactive Git Archaeology (`ec archaeologize`)** — `git log --patch` + merged PR bodies through the existing extraction pipeline; generates a `source:inferred` bootstrapped decision corpus. Eliminates cold-start — the largest adoption barrier. _(Confidence 80%, Medium-High complexity)_ Plan reference: `docs/brainstorms/retroactive-git-archaeology.md`.

- **Alive Session Memory (Rolling WAL Capture)** — `PostToolUse` writes turn content to append-only JSONL shard immediately; `core/async_worker.py` background thread consolidates on a 30-second rolling window. Makes EC crash-safe for long-running CI and agentic tasks. _(Confidence 83%, Medium complexity)_ Plan reference: `docs/brainstorms/alive-session-memory.md`.

- **Agent Learning Report (After-Action Digest)** — `SessionEnd` hook emits a structured AAR (new decisions extracted, prior decisions surfaced, `ec_context_apply` signal). Full "lessons applied / stale reversed" accounting requires new tracking instrumentation and runs as a detached background worker (5-second SessionEnd budget is a hard constraint). _(Confidence 90%, Low-Medium complexity; moved from v0.6.0 — out of scope for outcome lifecycle track)_ Plan reference: `docs/brainstorms/agent-learning-report.md`.

- **Decision Conflict Flagging** — on new decision write, `fts_decisions` keyword-overlap check surfaces flagged pairs as `decision_candidates` for human review via `ec review` queue. Does NOT auto-generate `contradicted` outcomes — keyword co-occurrence ≠ semantic contradiction; auto-write would corrupt F2 penalty scoring. _(Confidence 78%, Medium complexity; moved from v0.6.0 — out of scope for outcome lifecycle track)_ Plan reference: `docs/brainstorms/decision-conflict-flagging.md`.

- **Decision packs by area** — reusable memory bundles for domains like sync, testing, or search (original exploration item; Decision Keystone Detection is a prerequisite for intelligent pack assembly)

- **Human-in-the-loop correction UX** — fast review of extracted decisions and stale lessons via `ec review` interactive HITL queue (original exploration item)

## Non-Goals for This Phase

- Becoming a generic knowledge management system
- Expanding dashboard or graph breadth before retrieval quality improves
- Storing more raw transcripts without better distillation
- Adding platform surface area that does not reinforce the decision-memory loop

## References

- [Agent Memory Landscape Research](docs/research/agent-memory-landscape.md)
