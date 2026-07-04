# Hypothesis Validation Framework

_Draft brainstorm. Created 2026-07-04. Revised 2026-07-04 after self-review. Milestone: v0.11.0. Confidence: 72%._

## Intent

Prove or disprove the core hypothesis: "structured decision retrieval measurably improves agent work quality compared to no retrieval or raw transcript retrieval."

Current state: the feedback loops (outcome → quality → ranking) are architecturally sound, but all evidence is circular — the system measures its own internal metrics (applied_context_rate, quality_score) without external ground truth. This document defines an evaluation framework that produces non-circular evidence.

User-visible outcomes:

- Operators can see whether decision injection actually helps, with honestly-reported uncertainty (directional signal at solo scale; statistical confidence only if the experiment scales to more users).
- Ranking weights can be tuned empirically instead of hand-set.
- The project can respond to the "memorizing transcripts isn't useful" criticism with data.

## The Three Questions

| # | Question | Current evidence | Required evidence |
|---|----------|-----------------|-------------------|
| Q1 | Does **proactive injection** change agent behavior? | proxy: file overlap → "accepted" | causal: controlled comparison |
| Q2 | When behavior changes, is the outcome better? | none | quality measurement on output |
| Q3 | Does the ranker surface the right decisions? | none | precision@k against human labels |

**Scope note on Q1**: the controlled comparison below suppresses the proactive injection channel only. Decision MCP tools and manual `ec search` remain available in both arms (dogfooding instructions mandate their use, and disabling them changes the agent's toolset in ways that confound the comparison). A null result therefore means "proactive injection adds nothing over on-demand retrieval" — it does NOT mean "the decision system is useless." Testing the broader claim is Approach 4's job.

## Approach 1: Injection On/Off Experiment (Q1 + Q2)

### Design: Time-Block Crossover (not session-level randomization)

Session-level A/B randomization is invalid here: treatment and control sessions share the same repo and the same decision DB. A treatment session that applies a decision commits code that later control sessions inherit — the treatment effect leaks into the control arm through the codebase (SUTVA violation). No amount of session-level coin-flipping fixes this.

Instead, alternate injection on/off in **4-day time blocks**, and compare block-level aggregates. (Resolved from review: at ~5 sessions/day, 4-day blocks yield ~20 sessions/block and ~1.75× more block pairs than weekly in the same calendar time, with shorter carryover accumulation per block. Since rare-event proxies are underpowered either way and the deliverable is directional signal, more pairs beats bigger blocks.)

OFF blocks must suppress **every** proactive surfacing channel, not just one — the repo has four independent paths, each behind its own config key:

| Channel | Config key (actual) | ON blocks | OFF blocks |
|---------|--------------------|-----------|------------|
| SessionStart related decisions | `[decisions] show_related_on_start` | true | false |
| UserPromptSubmit async surfacing (F4 file) | `[decisions] surface_on_user_prompt` | true | false |
| PostToolUse surfacing | `[decisions] surface_on_tool_use` | true | false |
| UserPromptSubmit sync injection (planned, v0.7.0+) | `[decisions.injection] inject_on_user_prompt` | true | false |
| Decision MCP tools / manual `ec search` | — | enabled | enabled |

Missing even one channel contaminates OFF blocks with partial treatment. If the toggles are flipped by hand or cron (the minimal path below), the flip script must set all of them atomically. A reviewer-endorsed alternative that is still a small change: a single `[decisions.injection] experiment_block` flag consulted by all surfacing handlers — one source of truth, no per-key drift risk. Prefer the flag if Phase 2 work touches those handlers anyway; otherwise the atomic flip script suffices for a solo run.

Assignment: flip the config keys above at block boundaries (manually or via cron) and log each transition — see Implementation and the Build vs Script Tradeoff section. A dedicated `experiment_schedule` config key with SessionStart block computation is the multi-user upgrade path, not the starting point.

Crossover with multiple block pairs partially controls for time trends (repo maturity, task mix drift). Analyze as paired block differences, not pooled sessions.

Known limitation — **not blind**: in a solo-dogfooding setup the operator is the tool's author and will notice when injections stop appearing. Behavioral compensation (manually running `ec search` more in OFF blocks) is likely and must be measured: compare manual retrieval_events counts between ON and OFF blocks and report alongside results. If OFF blocks show compensatory manual retrieval, the estimand shifts from "injection vs nothing" to "proactive vs on-demand retrieval" — still a useful question, but report which one was actually measured.

### Quality Signals (output proxies)

Since we cannot measure "code quality" directly without human review, use observable proxies:

| Signal | Source | Hypothesis | Caveat |
|--------|--------|-----------|--------|
| Commit revert/fixup rate | git log: revert commits or `fix`-type commits touching same files within 48h | ON blocks have fewer | Rare in solo repos; may lack power |
| Session turn count for similar tasks | session metadata | ON blocks complete in fewer turns | Task mix varies between blocks |
| Test pass rate post-session | CI results if available | ON blocks introduce fewer failures | Only observable when CI runs |
| Decision contradiction rate | outcome_type = contradicted in subsequent sessions | ON-block decisions contradicted less | Lagging indicator |

Dropped from the earlier draft: **assessment verdict distribution** (expand/narrow ratio). The rule-based assessor derives verdicts from commit message patterns (`^feat` → expand), so this proxy measures commit-message wording habits, not output quality — it is circular.

### Minimum Sample Size

Assumption: revert/fixup baseline rate ~10% of sessions, and the realistic effect to detect is an **absolute** reduction of 5 to 7.5 percentage points (a halving or better; anything smaller is not worth the experiment cost at this scale). Two-proportion test at α=0.05, power=0.80:

- Detect 10%→5% (5pp absolute): ~435 sessions per arm
- Detect 10%→2.5% (7.5pp absolute): ~180 sessions per arm

(Normal-approximation estimates without continuity correction; treat as order-of-magnitude planning figures, not exact requirements.)

At solo-dogfooding cadence (~5 sessions/day, split across blocks) either target takes months. Therefore: treat Approach 1 as a **directional signal generator**, not a hypothesis test. Report block-pair differences with confidence intervals and explicitly state the achieved power. Do not claim significance the sample cannot support. If directional signal is consistently positive across 4+ block pairs, that justifies recruiting more users for a properly powered run.

### Implementation (minimal path)

The existing config toggles already provide the on/off switches. Block transitions flip all four keys from the channel table above (`show_related_on_start`, `surface_on_user_prompt`, `surface_on_tool_use`, `inject_on_user_prompt`) atomically — manually or via cron editing the config — so no channel leaks treatment into OFF blocks. No scheduler code needed for a solo run.

- [ ] Record block membership: a one-line entry in a `experiment-blocks.jsonl` log (`{block_start, injection}`) maintained by hand or by the cron that flips the toggle.
- [ ] Analysis: a standalone script (not shipped CLI) joining sessions to blocks by timestamp, computing paired block differences with confidence intervals, and counting manual retrieval_events per block for the compensation check.
- [ ] Only if the experiment graduates to multi-user scale: promote to an `experiment_schedule` config key + SessionStart block computation + `ec experiment report` CLI.

## Approach 2: Outcome Inference Accuracy Audit (validates Loop 1)

### Problem

`auto_apply.py` infers "accepted" when surfaced-decision files overlap with modified files. False positive rate is unknown.

### Design

Sample N=50 sessions where auto-apply inferred "accepted". For each, a reviewer answers: "Did the agent actually use this decision's guidance, or was the file modification coincidental?"

| Verdict | Meaning |
|---------|---------|
| True positive | Agent visibly followed the decision |
| False positive | File overlap was coincidental |
| Ambiguous | Cannot determine from transcript |

Precision note: with N=50, a point estimate near 0.5 carries a 95% CI of roughly ±0.14. That is adequate for the coarse gate below (distinguishing "mostly right" from "mostly wrong") but not for fine-grained calibration. If the estimate lands in 0.4–0.6, extend to N=100 before deciding.

Annotator bias note: in the current solo setup the annotator is also the project author, who wants the heuristic to work. Mitigations: (a) annotate from the transcript alone without looking at which outcome was recorded, (b) write the verdict rationale before revealing the auto-inferred label, (c) when a second annotator becomes available, double-label a 20-case subset and report agreement. Until (c) happens, report results as single-annotator with declared conflict of interest.

### Implementation (minimal path)

No new CLI needed. Sampling is a SQL query against `decision_outcomes` (filter `outcome_type='accepted'` with `note LIKE 'auto:%'`, join to sessions/turns for transcript links); label-blinding means the query output omits the recorded label column.

- [ ] Standalone sampling script (or documented SQL) producing the 50-case review sheet: session_id, decision_id, files_overlap, turn content path — outcome label withheld.
- [ ] Reviewer records verdict in a JSONL file: `{session_id, decision_id, verdict, rationale}`.
- [ ] Precision computation: a ~20-line script over the verdicts file. Promote to `ec experiment` subcommands only if the audit becomes a recurring practice.
- [ ] Lightweight explicit feedback (resolved from review): after `ec context apply`, print one line — `Applied. Useful? [Y/n/skip]`, default skip on Enter — and record the response as `feedback:yes/no/skip` in the existing `context_applications.note` field (no schema change). Acquiescence bias is real, but a biased explicit signal beats none: it provides an independent cross-check against auto-apply's file-overlap verdicts in this audit (agreement rate between manual feedback and inferred outcomes is itself a useful precision proxy). Skip-by-default keeps workflow friction near zero.

### Decision Gate

If precision < 0.5 (more than half of "accepted" are false positives), the **outcome-derived signals** — quality scores, outcome-based ranking boosts, extraction-confidence feedback, and the decision-contradiction-rate proxy in Approach 1 — are corrupted and must not be trusted until auto_apply is redesigned.

Scope of the gate, both directions:
- **Not too broad**: direct ON/OFF quality metrics (turn count, revert/fixup rate, CI failures) do not depend on auto-apply and remain valid even if Phase 1 fails. Phase 3 can proceed on those metrics alone; only its outcome-derived proxy is blocked.
- **Not too narrow**: this audit measures precision only. False negatives (decisions the agent applied without touching linked files, so no outcome was recorded) are invisible to it — a high precision score does not prove the loop captures everything. Label Phase 1 results as precision-only; a false-negative audit (sample sessions with surfaced-but-no-outcome decisions) is a candidate follow-up, not part of this gate.

## Approach 3: Ranking Precision Benchmark (Q3)

### Problem

`rank_related_decisions()` returns top-k decisions for a given context (files, diff, commits). No ground truth exists for whether those k decisions are actually relevant.

### Prerequisite: Signal Snapshot Capture (blocking)

The existing telemetry cannot support this benchmark. `retrieval_events` stores only `query`, `file_filter`, `commit_filter`, `result_count`, and `latency_ms` — it does not store the diff text, the resolved file list, the ranked result list, or the per-signal score breakdown. Offline re-ranking (required for weight tuning) needs the ranker's exact inputs, and those are currently discarded after each call.

Therefore Phase 2 starts with a capture change, not an export command:

- [ ] New table `ranking_snapshots`: `{id, retrieval_event_id, input_files JSON, input_diff_text TEXT, input_commits JSON, scored_candidates JSON (decision_id, score, per-signal breakdown — the FULL scored set before `scored[:limit]` truncation), effective_limit INTEGER, created_at}`. Written by `rank_related_decisions` callers when `[decisions] capture_ranking_snapshots = true` (default false).
- [ ] Privacy policy for `input_diff_text` (and any persisted transcript excerpt): note that `content_filter.redact_content()` is a no-op unless `capture.exclusions.enabled` is set, so it alone is NOT a safety net. Requirements: (a) always apply `security.filter_secrets()` (default patterns) AND configured `redact_content` before persisting — defense-in-depth, matching the F4 worker's double-filter model; (b) cap stored diff at the existing 8192-byte truncation; (c) exclude `ranking_snapshots` from `ec sync` export by default; (d) cover with `ec purge`, and add a retention default (e.g. 90 days); (e) seeded-secret regression test proving a planted token never reaches the table.
- [ ] Capture exhaustively while the config is on — no sampling. (Resolved from review: ~5–15 snapshots/day at ~10–30KB each ≈ 7–10MB over the 4–6 week collection window, trivial for SQLite; sampling at 1-in-3 would stretch collection to 12–18 weeks for no meaningful storage savings.)
- [ ] Only after snapshots accumulate can labeling begin. Budget ~4–6 weeks of dogfooding to collect 100 usable cases.

### Design

Offline evaluation dataset: collect N=100 real (context, scored_candidates) snapshot pairs.

Precision@k alone cannot detect **recall failures**: if candidate generation never gathered the right decision, the top-k can be 100% "relevant among what was considered" while the ranker still failed the user. Two design consequences:

1. The snapshot stores the full scored candidate set (pre-truncation) plus the effective limit — note that production surfacing paths truncate aggressively (`surface_on_user_prompt_limit` defaults to 3, ranker slices `scored[:limit]`), so judging only what was surfaced would judge a 3-item window.
2. The judgment pool per case = surfaced top-k ∪ sampled non-surfaced candidates ∪ a keyword/FTS sweep of the full decisions table for that context. Annotate the pool, not just the output.

Labels: relevant / partially relevant / irrelevant per (context, decision) pair.

Metrics:
- **Precision@5**: fraction of top-5 that are relevant (partial counts 0.5)
- **NDCG@5**: position-weighted relevance (gain: relevant=2, partial=1, irrelevant=0)
- **MRR**: mean reciprocal rank of first relevant decision
- **Missed-relevant audit**: count of pool-relevant decisions absent from the scored candidate set (candidate-generation recall failure) vs present-but-ranked-below-cutoff (ranking failure) — these have different fixes

### Weight Tuning Protocol

With only ~100 labeled cases, a 70/30 split leaves a 30-case test set — too small to distinguish a real NDCG lift from noise, and grid search over that set will overfit. Instead:

1. Use **5-fold cross-validation** over the full labeled set; report mean ± std of NDCG@5 per weight configuration. Start labeling at 100 cases; if cross-fold NDCG@5 std ≥ 0.15 (folds of 20 are noisy for a position-sensitive metric), extend labeling to 150 before drawing tuning conclusions.
2. Restrict the search space: vary only `file_exact_weight`, `diff_relevance_weight`, `quality_weight` within ±50% of defaults (coarse grid, ≤27 configurations) to limit multiple-comparison inflation.
3. Ship new defaults only if the best configuration beats the current defaults by more than one std of the CV estimate — otherwise declare current weights adequate.
4. Re-validate on the next 50 cases collected after the tuning decision (temporal holdout) before finalizing.

## Approach 4: Comparative Baseline (validates project thesis vs. article criticism)

### Problem

The article argues raw transcript search is useless. But entirecontext's structured decisions may or may not be better than:
- (a) No memory at all
- (b) Raw FTS5 over transcripts (the thing the article criticizes)
- (c) CLAUDE.md / manual memory files

### Design

Three-arm comparison on a fixed task set (e.g., 20 well-defined coding tasks on the same repo):

| Arm | Memory source |
|-----|---------------|
| A (control) | No memory injection |
| B (transcript) | Raw `ec search` results injected as context |
| C (structured) | `rank_related_decisions` top-5 injected |

Quality metric: human-graded output quality (1-5 scale) + task completion time.

Implementation note: arm B requires building a transcript-injection path that does not currently exist (raw search results are not wired into `additionalContext`). Count that build cost into the decision to run this study.

### Pragmatic Start

This is expensive. Defer until Approach 1 produces a directional read. Interpretation discipline: a null Phase 3 result says only that **proactive injection adds no incremental value over on-demand retrieval** — it says nothing about structured decisions vs raw transcripts vs no memory, which is precisely this approach's question. So a null Phase 3 does not license skipping Approach 4; it changes its priority. If Phase 3 is null AND the compensation check shows no manual retrieval either, run at least a small-N (5-task) version of this comparison before accepting the article's thesis; if Phase 3 is positive, run the full version to attribute the effect.

## Build vs Script Tradeoff

At solo-dogfooding scale, building the experiment framework as shipped product features (`ec experiment` subcommands, scheduler config) costs more than the experiments themselves — each shipped command carries test, docs, and maintenance burden for what may be a one-shot validation. Default posture:

| Component | Minimal path | Promote to product when |
|-----------|-------------|------------------------|
| Phase 1 sampling + precision | SQL + standalone scripts | Audit becomes a recurring (per-release) practice |
| Phase 3 block switching | Existing surfacing toggles (all four channel keys), flipped atomically by script/cron | Multi-user experiment needs consistent assignment → central experiment-block helper |
| Phase 3 analysis | Standalone script over sessions + blocks log | Same |
| **Phase 2 `ranking_snapshots` capture** | **Must be product code** — hooks into `rank_related_decisions` call sites, needs redaction + config gate | n/a (only real build in this plan) |

The only unavoidable product change is the ranking snapshot capture; everything else starts as scripts under `scripts/experiments/` (or documented SQL) and earns promotion by repeated use.

## Scope

### In

- Ranking snapshot capture (new table, config gate, redaction) — the one product-code change.
- Time-block crossover experiment: block log convention, analysis script, compensation check.
- Outcome inference accuracy audit: sampling SQL/script with label-blinding, verdict format, precision script.
- Precision benchmark tooling as scripts (label, evaluate, cross-validate).
- Documentation of methodology, achieved power, and decision gates.

### Out

- `ec experiment` CLI subcommands and `experiment_schedule` scheduler config (promote from scripts only on demonstrated recurring use).
- Automated weight tuning in production (defer until benchmark shows a lift exceeding CV noise).
- Three-arm comparative study (defer until injection experiment shows signal).
- Changes to existing ranking or injection logic (this is measurement only).
- Feedback UI beyond the single-line `ec context apply` prompt (no per-injection ratings, no notification-driven surveys).
- Integration with external CI systems for test pass rate collection.

## Sequencing

```
Phase 1 (v0.11.0): Outcome Inference Accuracy Audit (precision-only)
  → Gate: if precision < 0.5, outcome-derived signals are untrusted until
    auto_apply is fixed; direct ON/OFF metrics remain usable
  → If estimate in 0.4–0.6, extend N=50 → N=100 before deciding

Phase 2a (v0.11.0): Ranking Snapshot Capture
  → The one product-code change; ships with redaction, purge, export
    exclusion, and seeded-secret test

Phase 2b (v0.11.x): First Precision/Recall Report
  → Labeling starts after ~100 snapshots accumulate (~4-6 weeks)
  → Deliverable: P@5, NDCG@5, MRR, missed-relevant audit — no tuning yet

Phase 2c (optional): Weight Tuning
  → Only if 2b shows headroom; 5-fold CV, ship only if lift exceeds CV
    noise, temporal holdout before finalizing

Phase 3 (v0.12.0): Injection On/Off Crossover Experiment
  → Direct quality metrics usable regardless of Phase 1 outcome;
    outcome-derived proxies only if Phase 1 passed
  → Requires 4+ block pairs; report directional signal with declared power

Phase 4 (v0.13.0, conditional on Phase 3 read):
  → Phase 3 positive → full Comparative Baseline to attribute the effect
  → Phase 3 null → small-N (5-task) Comparative Baseline before accepting
    the article's thesis
```

Phase 1 gates the outcome-derived signal chain (quality score → ranking boost → extraction feedback) because if outcome inference is broken, everything downstream of it is built on sand. It does not gate metrics that never touch auto_apply.

## Risks

- **Underpowered by construction**: solo-dogfooding volume cannot reach conventional significance for rare-event proxies like revert rate. Mitigation: report effect direction + CI + achieved power honestly; scale users before making strong claims.
- **Cross-block carryover**: even with time blocks, decisions applied in ON blocks persist in the codebase and benefit OFF blocks. Crossover reduces but does not eliminate this; treat estimates as lower bounds on the true effect.
- **Not blind**: the operator notices missing injections and may compensate with manual retrieval. Mitigation: measure manual retrieval per block and report which estimand was actually measured.
- **Proxy validity**: revert rate and turn count may not correlate with actual code quality. Mitigation: treat as directional signals, not proof; supplement with human review on a subset.
- **Annotation bias**: single annotator who is also the author. Mitigation: label-blinding, rationale-first verdicts, double-label a subset when a second annotator is available.
- **Snapshot storage**: ranking snapshots persist diff text, which may contain secrets. Mitigation: reuse the existing content_filter redaction path before persisting; gate behind opt-in config.
- **Survivorship bias**: only decisions that survived extraction + confirmation are evaluated; the system may be filtering out the most useful candidates before they reach the ranker.

## Resolved Questions

Answered in PR #184 review with codebase-grounded analysis; decisions folded into the body above.

| Question | Resolution | Where applied |
|----------|-----------|---------------|
| Block length: weekly or 3–4 days? | **4-day blocks** — ~1.75× more pairs per calendar time, shorter carryover accumulation; pairs beat block size when the goal is directional signal | Approach 1 Design |
| Suppress all proactive channels in OFF blocks? | **Yes, all of them** — one leaking channel contaminates the independent variable; single shared `experiment_block` flag endorsed as the drift-proof implementation | Approach 1 channel table |
| 100 labeled cases enough for the benchmark? | **Start at 100**; extend to 150 only if cross-fold NDCG@5 std ≥ 0.15 — existing guardrails (1-std ship bar, temporal holdout) make early start safe, and waiting costs 2–3 extra weeks | Approach 3 Weight Tuning Protocol |
| Sample or exhaustively capture snapshots? | **Exhaustive** — ~7–10MB over the collection window is trivial; 1-in-3 sampling stretches collection to 12–18 weeks | Approach 3 Prerequisite |
| Add "was this useful?" prompt to `ec context apply`? | **Yes, minimally** — `Useful? [Y/n/skip]`, skip default, stored in existing `note` field; biased explicit signal beats none and cross-checks auto-apply precision | Approach 2 Implementation |
