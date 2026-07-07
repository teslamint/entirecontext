# EntireContext Roadmap

_Updated 2026-07-07._

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

**Target users (through v1.0):** individual developers (1) + agent frameworks via MCP (3). Team-scoped features are deferred to v1.x+.

With v0.4.0 the loop now feeds itself — outcomes flow into ranking and extraction, and UserPromptSubmit opens a new signal channel. v0.5.0 hardened the loop by closing 3x-deferred correctness debt before adding new feature surface. v0.6.0 widened the outcome vocabulary (`refined`/`replaced`) and v0.6.1 normalized the rejected-alternative data shape. v0.7.0 made retrieval default behavior — Proactive Decision Injection now surfaces decisions at the top of every conversation turn without explicit search, raising `retrieval_assisted_session_rate` from 0.049 to 0.125. v0.7.1 hardened PDI with per-session capture_disabled gating, tiktoken-accurate token counting, and Signal A (diff file-path extraction). v0.8.0 broke the three-sprint distill=0 streak with auto-assess on checkpoint create, added Signal B (working-file inference from recent commits), and laid Signal C embedding foundation — raising maturity from 32 to 61. v0.8.1 corrected measurement infrastructure (codex session auto-close, rate normalization, verdict accuracy baseline). v0.9.0 automates the weakest dimension (intervene=5) with SessionEnd auto-apply inference, backfill tooling, and Signal C activation. v0.10.0 adds dual-channel lesson surfacing (SessionStart + PDI) to activate `lesson_reuse_rate`, and Layer 2 git-evidence outcome inference (refined/replaced) to close the v1.0 autonomous-loop gate. v0.11.0 adds hypothesis validation infrastructure — ranking snapshots for retrieval auditing and experiment block config for ON/OFF crossover experiments.

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

## v0.6.0 — Outcome Semantics (Shipped 2026-05-10)

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

## v0.6.1 — Rejected-Alternative Quality (Shipped 2026-05-20)

Theme: clean up the rejected-alternatives data shape without mutating existing records or inventing rationale.

- [x] Rejected alternative normalization helpers in `core/decisions.py` accepting legacy strings and structured objects
- [x] `ec decision alternatives audit` — list reasonless, malformed, mixed, or legacy alternatives without mutating data
- [x] `ec decision alternatives normalize` — convert legacy strings to structured objects; use `"Unknown from recorded context"` for missing reasons
- [x] `ec decision alternatives set` or equivalent manual update command for explicit structured replacements
- [x] Tighten extraction prompts to request rejected-alternative reasons only when source text contains enough evidence; parser and candidate-confirmation paths share the same normalizer
- [x] Tests: legacy string compatibility, malformed JSON detection, mixed arrays, empty alternatives, empty reasons, audit categories, normalization idempotency, manual set behavior

## v0.7.0 — Proactive Decision Injection + Debt Clearance (Shipped 2026-05-20)

Theme: make retrieval default behavior, close three deferred debt items.

- [x] **PDI: `rank_decisions_for_prompt()`** — pure ranking function extracted from async worker, reusable by both sync and async paths
- [x] **PDI: `optimize_for_context_budget()`** — min_confidence cut → top_k slice → token trim → rationale truncation
- [x] **PDI: `UserPromptSubmit` hook stdout JSON** — `additionalContext` injection with `inject_timeout_ms` hard cap (default 250ms, `shutdown(wait=False)`)
- [x] **PDI: `[decisions.injection]` config section** — `inject_on_user_prompt=true` default (p95@1000=61.8ms < 250ms gate)
- [x] **B1: `ec session backfill-ended-at`** — recover `ended_at IS NULL` rows with optimistic concurrency and 1h safety gate
- [x] **B2: `accepted_boost`** — `accepted_boost_amount`/`accepted_boost_threshold` in `ExtractionWeights`; finishes ec decision `3a1ccb19`
- [x] **B3: Remove `unverified_changes.patch`** — duplicate of already-committed docs files

## v0.7.1 — PDI Hardening + Signal A (Shipped 2026-06-02)

Theme: close correctness gaps in PDI, establish measurement baseline, and activate the highest-value missing retrieval signal.

- [x] **Per-session `capture_disabled` check in PDI** — implemented in PR #143; per-session disable flag gates PDI ranking on the same DB connection used for ranking
- [x] **tiktoken accurate token counting** — eager module-level `cl100k_base` encoding (core dependency); `disallowed_special=()` for safe special-token handling; byte-heuristic fallback retained for import-failure edge cases
- [x] **Signal A: diff file-path extraction** — `git diff --name-status -M -z HEAD` for rename-aware, NUL-delimited file path collection; deleted files included via `--- a/` path; `surrogateescape` for non-UTF-8 filenames; ranking + optimization inside timeout thread for `inject_timeout_ms` compliance
- [x] **PDI effect measurement** — `retrieval_assisted_session_rate` already computed in `dashboard.py`; establish n≥30 session baseline across v0.7.1 window before interpreting the 0.049→0.125 lift as confirmed

## v0.8.0 — Closed Loop (Distill Automation + Signal B/C) (Shipped 2026-06-07)

Theme: break the three-sprint distill=0 streak through structural automation, and deepen retrieval signal coverage informed by v0.7.1 hit-rate measurement.

The `capture→distill→retrieve→intervene` loop has stalled at `distill=0` for v0.6.0, v0.6.1, and v0.7.0. Checkpoint coverage is 100%; assessment coverage is 0% all three sprints. Will-based rules cannot enforce this gap — only automatic triggering can.

### Distill Automation

- [x] **Auto-assess on checkpoint create** (primary trigger) — `ec checkpoint create` automatically triggers `auto_assess_checkpoint()` (rule-based assessment) before the command returns; no session ends with a checkpoint and zero assessments. PR #157.
- [x] **SessionEnd safety net + AAR** — SessionEnd hook backfills un-assessed checkpoints (safety net via `_maybe_backfill_assessments`), SessionStart catches up crashed sessions (`_maybe_catchup_assessments`), then emits a structured AAR (After-Action Report): decisions surfaced, PDI retrieve→intervene delta, assessments created. AAR written to `.entirecontext/aar-{session_id}.json` and printed to stdout. Config: `[capture] emit_aar` (default true).
- [ ] **Maturity ≥75 (Closed Loop)** — distill automation brings `distill` off zero (achieved: distill=25); sustained dogfooding target requires measurement over multiple sessions

### Signal Assembly

- [x] **Signal B: working-file inference** — `_get_recent_commit_file_paths()` extracts file paths from recent commits via `git log --name-only`; merged into `rank_decisions_for_prompt()` alongside Signal A (uncommitted diff) paths. Decisions linked to recently-committed files now surface even when the working tree is clean.
- [~] **Signal C: semantic similarity** — v0.8.0 ships the foundation: `_build_decision_embed_text()`, `semantic_search_decisions()`, and decision embedding in `generate_embeddings()` (source_type='decision'). Auto-embed on `create_decision()` gated by `[decisions] auto_embed` (default false, requires `entirecontext[semantic]`). Full 2-pass async architecture (background ranking feeding next prompt's PDI, SessionStart pre-warm) deferred to v0.9.0.

## v0.8.1 — Measurement Accuracy (Shipped 2026-06-07)

Theme: fix measurement infrastructure so maturity scores reflect reality. No new features — only corrections that enable trustworthy attribution for subsequent feature releases.

Follows the v0.8.0 retro lesson: "측정 인프라가 측정 대상보다 먼저 정확해야 한다."

- [x] **Codex session auto-close** — `close_stale_sessions()` sets `ended_at = last_activity_at` for codex sessions idle > N minutes (default 60, config: `[capture] codex_session_idle_minutes`). Called automatically during codex notify ingestion with optimistic concurrency guard.
- [x] **Maturity calculation normalization** — `retrieval_assisted_session_rate` numerator and denominator both filter on `ended_at IS NOT NULL`, consistent with `checkpoint_coverage_rate`. Previously, 383 codex sessions with `ended_at=NULL` inflated the denominator without contributing ended-session semantics, and retrieval events in active sessions could inflate the numerator.
- [x] **Verdict accuracy baseline** — `ec checkpoint assess-accuracy` reports agree/disagree rate from LLM enrichment feedback. Current data: 10 enriched (all agree), 8 rule-based pending. v0.9.0 verdict tuning should gate on n≥30.

## v0.9.0 — Intervene Automation

Theme: automate the weakest maturity dimension (intervene=5), activate deferred signal depth, and fix measurement gaps — all measured against v0.8.1's corrected baseline.

- [x] **SessionEnd auto-apply inference** — on SessionEnd, check intersection of surfaced decision-linked files and session-modified files; auto-record `context_application` + `accepted` outcome for matches. Inverse of `_maybe_infer_ignored_decisions`. Config: `decisions.infer_applied_on_session_end` (default true).
- [x] **Auto-apply backfill** — `ec session backfill-applied` retroactively infers applied decisions for historical sessions. Options: `--dry-run` / `--apply`.
- [x] **search_to_selection_rate DISTINCT fix** — formula changed from `total_selections / total_events` to `DISTINCT events with ≥1 selection / total_events`. Now a proper [0,1] fraction.
- [x] **Signal C default ON** — `[decisions] auto_embed` flipped to `true` by default. Graceful no-op without `entirecontext[semantic]`.
- [x] **Codex stale cleanup trigger expansion** — `close_stale_sessions()` now also triggered on SessionEnd, not just codex notify ingestion.
- [x] **Duplicate notify regression test** — guards 150faab auto-close accuracy invariant.
- [ ] **Rule-based verdict mapping tuning** — deferred to n≥30 enriched assessments (current: n=10).

## v0.9.1 — Measurement Calibration

Theme: fix measurement formulas so maturity scores reflect actual loop completion, and establish the retro carry-forward process.

- [x] **`applied_context_rate` session-based formula** — numerator/denominator changed from per-selection counts to per-session counts. Old formula structurally capped at ~6.7%; new formula `sessions_with_application / sessions_with_selection` reaches threshold naturally. ec decision `b09d1aed`.

## v0.9.2 — Process & Measurement Housekeeping

Theme: codify deferred process rules, evaluate measurement edge cases, add dev process conventions.

- [x] **Retro carry-forward → ROADMAP registration rule** — v0.9.0 retro finding: deferred items were not transferred to ROADMAP, causing 4-release drift. Rule added to AGENTS.md: retro completion must register carry-forwards in ROADMAP or mark explicit won't-fix.
- [x] **`reopen → sessions_ended` non-monotonic evaluation** — evaluated: `codex_ingest.py:335` resets `ended_at = NULL` on new turn arrival for existing codex sessions, causing `sessions_ended` decrease. Impact: minor (codex sessions only, eventually re-closed by next hook invocation — not timer-based). Resolution: won't-fix, documented as known limitation. See ADR-0003.
- [x] **Dev process conventions** (PR #165) — Conventional Commits CI gate, ADR directory, measure-first principle, mypy strict with grandfather overrides.
- Deferred: **`auto_extract` default true** → v1.0 (measure-first: 2-month dead code path requires live verification before default-on). ec decision `309d472a`.

## v0.9.3 — Cleanup & Version Sync

Theme: remove legacy shims, fix version drift, correct ADR-0003 trigger documentation.

- [x] **Remove `hybrid_search.py` and `indexing.py` shim modules** (#27) — all callers migrated to `core.search` and `core.embedding` direct imports.
- [x] **`__version__` sync** — runtime version in `__init__.py` was stuck at `0.7.1` since v0.7.1; now synced to release version.
- [x] **ADR-0003 correction** — "self-healing via idle timeout" was inaccurate; corrected to event-driven re-closure.

## v0.10.0 — Lesson Surfacing + Git-Evidence Outcome Inference

Close retro carry-forward debt, activate lesson-reuse path for maturity 75, add layered outcome inference.

- [x] **Carry-forward** — perf threshold 250→300ms, Codex shift-left review gate in docs/RELEASE.md
- [x] **Lesson surfacing: SessionStart** — dual-channel surfacing: broad-context lessons from checkpoint `files_snapshot` overlap at session start
- [x] **Lesson surfacing: PDI** — narrow-context lesson injection into `additionalContext`; decisions priority, lessons fill remaining token budget; timeout-isolated (100ms)
- [x] **Auto-apply lesson extension** — lesson/assessment file-overlap detection at SessionEnd using checkpoint `files_snapshot`; drives `lesson_reuse_rate` for intervene score
- [x] **Git-evidence outcome inference: Layer 2** — `refined`/`replaced` classification via new-decision gate + diff pattern; `infer_outcome_type` config (default true)
- [ ] **Maturity ≥ 75** — measurement outcome, requires sufficient session volume with lesson surfacing active
- Out-of-band: ghost release cleanup (1a), `auto_extract` production verification (1e)

## v0.11.0 — Hypothesis Validation Infrastructure (Shipped 2026-07-07)

Theme: build measurement infrastructure to answer "does decision surfacing actually help?" — ranking snapshots for retrieval auditing and experiment block config for ON/OFF crossover experiments.

- [x] **`ranking_snapshots` table (schema v15)** — records retrieval ranking inputs per `retrieval_events` row for hypothesis validation. Additive migration.
- [x] **Experiment block config** — `[decisions.injection] experiment_block` atomically suppresses all 4 proactive surfacing channels for ON/OFF crossover experiment.
- [x] **Automated block flip** — `scripts/experiments/flip_block.py` runs every 30 min via cron, auto-flips when qualifying session threshold reached. Treatment-independent gate (total_turns >= 5).
- [x] **Audit sampler fixes** — path normalization and content turn selection edge cases.

## v0.12.0 — Carry-Forward Graduation

Theme: graduate all 8 v0.11.0 retro carry-forward items. Diagnosis-first approach — all items pre-diagnosed, results recorded. Zero code changes.

- [x] **C1. intervene 13→5 diagnosis** — rate dilution confirmed (applied_context_rate=5/66=7.6%, threshold 10%). Won't-fix: formula correct, denominator inflated by lesson surfacing + PDI growth outpacing context_apply usage. Intervene improvement requires dogfooding volume.
- [x] **C2. Pre-release checklist** — first live application of `docs/RELEASE.md` unified checklist. All 5 phases followed.
- [x] **C3. Experiment data verification** — plumbing pass: 44 ranking_snapshots, cron active (56 log entries), block=1 (ON), 2/5 qualifying sessions. 7/21 validity analysis → v0.13.0 carry-forward.
- [x] **C4. ROADMAP sections** — v0.11.0 retroactive + v0.12.0 upfront sections added.
- [x] **C5. lesson_reuse_rate** — surfacing active (45 lesson_surfacing retrieval events), zero lesson-typed context_applications. Verdict: usage absence, not infra bug. No code change.
- [x] **C6. PR #185 skipped P2 validation** — 4 snapshot edge-case P2s reviewed (#3524582056 mixed SessionStart linkage, #3524625342/#3524676787 zero-result snapshot preservation, #3524705407 unauditable samples). All justified: experiment too early (2/5 qualifying) for edge-case data to matter. Revisit when experiment produces analysis-ready data.
- [x] **C7. Exploration priority evaluation** — Git Archaeology promoted to next candidate (addresses 91% file-link gap). Automated Block Flip marked shipped. All items evaluated against corpus=122/9% file-linked, maturity=61, experiment=early.
- [x] **C8. Decision corpus assessment** — 122 decisions, 11 with file links (9%), outcomes: accepted=58 contradicted=3 ignored=1 refined=3. 91% without file links limits PDI file-signal effectiveness. Git Archaeology → C7 priority.

Carry-forward to v0.13.0:
- 7/21 experiment validity analysis
- File-link coverage gap (91% decisions without file links)
- Intervene improvement via dogfooding volume

## v1.0 — Loop Completes Autonomously

Qualitative gate: the `capture→distill→retrieve→intervene→outcome` loop completes without human intervention and is repeatably observable across sessions.

The last manual bottleneck is **outcome attribution**. Current automation: SessionEnd infers `ignored` for surfaced-but-unacted decisions (config-gated, fully automatic); `ec decision supersede` auto-writes a `replaced` outcome (trigger is manual, recording is automatic); `ec_context_apply` auto-records `accepted` (trigger is manual — the agent or user must call it). Note: `contradicted` staleness auto-promotion exists but is not an outcome path — it changes `staleness_status` after someone manually records a `contradicted` outcome. The gap: no path automatically detects that an agent _followed_ a surfaced decision — `accepted` requires the agent to explicitly call `ec_context_apply`, and `refined` has no automatic path at all.

- [x] **`auto_extract` default true** — CLIBackend unwrap bug fixed (JSON array response), markdown fence stripping added, stale markers cleared, production verification confirmed candidates produced (1 candidate from 3 bundles).
- [x] **Git-evidence-based outcome inference** — shipped in v0.10.0: Layer 1 (file-overlap → accepted) + Layer 2 (new-decision gate + diff pattern → refined/replaced). `contradicted` auto-inference deferred (semantic judgment).
- [x] **Autonomous loop E2E wiring test** — `test_e2e_autonomous_loop.py` proves all five stages complete in-process; Stop hook fallback ensures extraction triggers on sessions without SessionEnd.
- [ ] **Alpha → stable status** — flip README badge and pyproject classifier once production observability confirms loop completion across multiple real sessions

## Hardening Backlog

Structural debt outside the "decision memory depth" wedge. The three items previously listed here (`confirm_candidate` atomicity, `LEGACY_TRANSACTION_CONTROL`, review-bot noise) have been absorbed into v0.5.0 — see S1, S2, S4 above. New items go here as they are surfaced.

## Later

- [ ] **Sharpen product messaging around decision memory**

- [ ] **Team-scoped decisions**
  - Same decision model as personal, with repo-wide or org-wide visibility
  - EC handles surfacing only; enforcement is out of scope (CI/linter/review bot territory)
  - Capture recurring team preferences and architectural constraints as decisions, not policies

- [ ] **Decision file rename tracking**
  - Preserve historical outcome trail when `decision_files` paths are renamed or moved

## Done Foundations

- [x] Capture hooks, checkpoints, rewind, and attribution
- [x] Hybrid search, AST search, graph/dashboard tooling, and MCP exposure
- [x] Futures assessments, typed relationships, feedback, lessons, and trend analysis
- [x] Async workers, filtering, export, consolidation, and cross-repo support
- [x] Sync merge/retry policy and shadow-branch conflict handling (spec §6.3, v0.2.0)

## Exploration

Most items below were evaluated in the 2026-04-27 ideation session ([docs/ideation/2026-04-27-product-roadmap-ideation.md](docs/ideation/2026-04-27-product-roadmap-ideation.md)) and promoted to concrete candidates. Items marked "moved from v0.6.0" were initially proposed for the breaking track but fall outside the outcome-lifecycle scope defined in `docs/brainstorms/v0-6-0-roadmap-plan.md`. Items added after that session cite their own provenance inline.

_v0.12.0 priority evaluation (2026-07-07):_ corpus=122 decisions (9% with file links), maturity=61 (intervene=5, usage-driven), experiment=plumbing only (2/5 qualifying). **Next candidate: Git Archaeology** — directly addresses the 91% file-link gap that limits PDI signal coverage.

- **Temporal Query Language (TQL)** — `--at <ref>`, `since:`, `between:` syntax for all search/retrieval commands; queries evaluate against memory state at a specific git commit or date. Exploits EC's unique moat (git-anchored time-travel) — no competitor offers this. _(Confidence 88%, Medium complexity)_ Plan reference: `docs/brainstorms/temporal-query-language.md`. _Priority: Medium — unique moat but corpus-independent; doesn't address current bottlenecks._

- **`ec blame` — Decision-Annotated Git Blame** — `ec blame <file> [line]` traverses `decision_commits` → `decision_checkpoints` → decision records to answer "why does this code exist?" with rationale and rejected alternatives. `blame_cmds` module already in CLI architecture. _(Confidence 85%, Medium complexity)_ Plan reference: `docs/brainstorms/ec-blame-decision-annotated.md`. _Priority: Low — requires decision_commits links (currently sparse with 9% file-linked corpus)._

- **Retroactive Git Archaeology (`ec archaeologize`)** — `git log --patch` + merged PR bodies through the existing extraction pipeline; generates a `source:inferred` bootstrapped decision corpus. Eliminates cold-start — the largest adoption barrier. _(Confidence 80%, Medium-High complexity)_ Plan reference: `docs/brainstorms/retroactive-git-archaeology.md`. _Priority: **HIGH — next candidate.** C8 diagnosis (91% file-linkless decisions) confirms cold-start and file-link gap as the largest retrieval bottleneck. Addresses both adoption barrier and PDI signal coverage._

- **Alive Session Memory (Rolling WAL Capture)** — `PostToolUse` writes turn content to append-only JSONL shard immediately; `core/async_worker.py` background thread consolidates on a 30-second rolling window. Makes EC crash-safe for long-running CI and agentic tasks. _(Confidence 83%, Medium complexity)_ Plan reference: `docs/brainstorms/alive-session-memory.md`. _Priority: Medium — valuable for capture dimension but doesn't address file-link or intervene bottlenecks._

- **Pre-Compaction Session Snapshot (`PreCompact` hook)** — add a sixth Claude Code hook (`PreCompact`) that captures a compact working-state snapshot (in-flight files from recent turns + uncommitted diff paths + latest checkpoint SHA + open decision intent) just before context compaction, then replays it through the existing SessionStart reactivation path so the post-compaction agent does not lose its place. Unlike a generic transcript dump, the snapshot is anchored to git state and persists as durable memory, not just resume scratch. Pairs with — and may subsume part of — Alive Session Memory: rolling WAL handles crash-safety, `PreCompact` handles the compaction boundary specifically. _(Confidence 80%, Medium complexity)_ Inspired by the [context-mode](https://github.com/mksglu/context-mode) review (2026-06-05). Plan reference: TBD. _Priority: Low — overlaps Alive Session Memory; sequence together._

- ~~**Agent Learning Report (After-Action Digest)**~~ — absorbed into v0.8.0 as AAR (SessionEnd safety net + structured digest).

- **Decision Conflict Flagging** — on new decision write, `fts_decisions` keyword-overlap check surfaces flagged pairs as `decision_candidates` for human review via `ec review` queue. Does NOT auto-generate `contradicted` outcomes — keyword co-occurrence ≠ semantic contradiction; auto-write would corrupt F2 penalty scoring. _(Confidence 78%, Medium complexity; moved from v0.6.0 — out of scope for outcome lifecycle track)_ Plan reference: `docs/brainstorms/decision-conflict-flagging.md`. _Priority: Low — corpus too thin (122) for useful conflict detection._

- **Retrieval Quality Micro-Ranking** — sharpen decision/turn retrieval relevance (not breadth) with three composable techniques layered onto the existing `hybrid_search` path: (a) **fuzzy query correction** — Levenshtein-bounded term repair before re-search so `kuberntes` still finds `kubernetes`; (b) **proximity reranking** — boost results where multi-term query tokens appear adjacent over those where they are scattered; (c) **smart snippets** — extract context around the FTS5 match offset instead of head-truncating. Directly reinforces the stated "retrieval quality before breadth" priority (see Non-Goals). _(Confidence 82%, Medium complexity)_ Inspired by the [context-mode](https://github.com/mksglu/context-mode) review (2026-06-05). Plan reference: TBD. _Priority: Medium — useful for retrieval precision but file-link gap is bigger bottleneck._

- **Decision packs by area** — reusable memory bundles for domains like sync, testing, or search (original exploration item; Decision Keystone Detection is a prerequisite for intelligent pack assembly) _Priority: Low — prerequisite (Decision Keystone Detection) not built._

- **Human-in-the-loop correction UX** — fast review of extracted decisions and stale lessons via `ec review` interactive HITL queue (original exploration item) _Priority: Medium — useful for corpus quality improvement._

- ~~**Hypothesis Validation: Automated Block Flip**~~ — shipped in v0.11.0. Plan reference: `docs/brainstorms/hypothesis-validation-framework.md`.

## Non-Goals

- Becoming a generic knowledge management system
- Expanding dashboard or graph breadth before retrieval quality improves
- Storing more raw transcripts without better distillation
- Adding platform surface area that does not reinforce the decision-memory loop
- **Policy enforcement / governance / ACL** — EC surfaces decisions, it does not enforce them. This holds at team and company scale. Enforcement belongs to CI, linters, and review bots
- **Agent behavior analysis / monitoring platform** — EC records outcomes via git evidence (outcome _attribution_), it does not judge agent behavior
- **Code generation or change suggestion** — EC surfaces past decisions for context, it does not prescribe what to do
- **Agent-to-agent communication / coordination layer** — EC is single-agent memory with optional cross-repo visibility, not a message bus

## References

- [Agent Memory Landscape Research](docs/research/agent-memory-landscape.md)
