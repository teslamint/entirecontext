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
