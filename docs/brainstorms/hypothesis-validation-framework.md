# Hypothesis Validation Framework

_Draft brainstorm. Created 2026-07-04. Revised 2026-07-04 after self-review. Milestone: v0.11.0. Confidence: 72%._

## Intent

Prove or disprove the core hypothesis: "structured decision retrieval measurably improves agent work quality compared to no retrieval or raw transcript retrieval."

Current state: the feedback loops (outcome → quality → ranking) are architecturally sound, but all evidence is circular — the system measures its own internal metrics (applied_context_rate, quality_score) without external ground truth. This document defines an evaluation framework that produces non-circular evidence.

User-visible outcomes:

- Operators can see whether decision injection actually helps, with statistical confidence.
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

Instead, alternate injection on/off in **time blocks** (e.g., weekly), and compare block-level aggregates:

| Block | `inject_on_user_prompt` | `surface_on_session_start` | MCP tools |
|-------|------------------------|---------------------------|-----------|
| ON weeks | true | true | enabled |
| OFF weeks | false | false | enabled |

Assignment: config key `[decisions.injection] experiment_schedule = ""` (default empty = no experiment). When set to e.g. `"weekly-alternate:2026-07-07"`, SessionStart computes the current block from the anchor date and suppresses injection in OFF blocks. Session metadata records `{"injection_block": "on"|"off"}`.

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

Assumption: revert/fixup baseline rate ~10% of sessions, and we care about an **absolute** reduction of 10 percentage points (10% → down to near-zero would be implausible; 10%→5% halving is the realistic target). Two-proportion test at α=0.05, power=0.80:

- Detect 10%→5% (5pp absolute): ~435 sessions per arm
- Detect 10%→2.5% (7.5pp absolute): ~180 sessions per arm

At solo-dogfooding cadence (~5 sessions/day, split across blocks) either target takes months. Therefore: treat Approach 1 as a **directional signal generator**, not a hypothesis test. Report block-pair differences with confidence intervals and explicitly state the achieved power. Do not claim significance the sample cannot support. If directional signal is consistently positive across 4+ block pairs, that justifies recruiting more users for a properly powered run.

### Implementation

- [ ] Add `experiment_schedule` config key under `[decisions.injection]`.
- [ ] SessionStart handler: compute block from anchor date; suppress proactive injection in OFF blocks; record `injection_block` in session metadata.
- [ ] AAR: record block status in after-action report.
- [ ] New CLI: `ec experiment report` — aggregate quality signals per block, compute paired block differences with confidence intervals, and report manual-retrieval compensation (retrieval_events count per block).

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

### Implementation

- [ ] New CLI: `ec experiment sample-outcomes --type accepted --count 50` — outputs session_id, decision_id, files_overlap, and a link to the relevant turn content for review, withholding the recorded outcome label until the verdict is written.
- [ ] Reviewer records verdict in a JSONL file: `{session_id, decision_id, verdict, rationale}`.
- [ ] New CLI: `ec experiment outcome-accuracy --verdicts <path>` — computes precision of the auto-apply heuristic.

### Decision Gate

If precision < 0.5 (more than half of "accepted" are false positives), the entire quality → ranking feedback loop is corrupted and must be redesigned before trusting the injection experiment results.

## Approach 3: Ranking Precision Benchmark (Q3)

### Problem

`rank_related_decisions()` returns top-k decisions for a given context (files, diff, commits). No ground truth exists for whether those k decisions are actually relevant.

### Prerequisite: Signal Snapshot Capture (blocking)

The existing telemetry cannot support this benchmark. `retrieval_events` stores only `query`, `file_filter`, `commit_filter`, `result_count`, and `latency_ms` — it does not store the diff text, the resolved file list, the ranked result list, or the per-signal score breakdown. Offline re-ranking (required for weight tuning) needs the ranker's exact inputs, and those are currently discarded after each call.

Therefore Phase 2 starts with a capture change, not an export command:

- [ ] New table `ranking_snapshots`: `{id, retrieval_event_id, input_files JSON, input_diff_text TEXT, input_commits JSON, ranked_results JSON (decision_id, score, per-signal breakdown), created_at}`. Written by `rank_related_decisions` callers when `[decisions] capture_ranking_snapshots = true` (default false; diff text storage has size and secrecy implications — reuse the existing content_filter redaction path before persisting).
- [ ] Only after snapshots accumulate can labeling begin. Budget ~4–6 weeks of dogfooding to collect 100 usable cases.

### Design

Offline evaluation dataset: collect N=100 real (context, ranked_decisions) snapshot pairs. An annotator labels each surfaced decision as relevant / partially relevant / irrelevant.

Metrics:
- **Precision@5**: fraction of top-5 that are relevant (partial counts 0.5)
- **NDCG@5**: position-weighted relevance (gain: relevant=2, partial=1, irrelevant=0)
- **MRR**: mean reciprocal rank of first relevant decision

### Weight Tuning Protocol

With only ~100 labeled cases, a 70/30 split leaves a 30-case test set — too small to distinguish a real NDCG lift from noise, and grid search over that set will overfit. Instead:

1. Use **5-fold cross-validation** over the full labeled set; report mean ± std of NDCG@5 per weight configuration.
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

This is expensive. Defer until Approach 1 shows directional signal. If the injection experiment shows no effect and no compensatory manual retrieval, skip this and accept the article's thesis applies to us too.

## Scope

### In

- Time-block crossover experiment infrastructure (config key, block computation, session metadata, report CLI).
- Outcome inference accuracy audit tooling (sample, annotate, evaluate) with label-blinding.
- Ranking snapshot capture (new table, config gate, redaction) and precision benchmark tooling (label, evaluate, cross-validate).
- Documentation of methodology, achieved power, and decision gates.

### Out

- Automated weight tuning in production (defer until benchmark shows a lift exceeding CV noise).
- Three-arm comparative study (defer until injection experiment shows signal).
- Changes to existing ranking or injection logic (this is measurement only).
- User-facing feedback UI ("was this helpful?" prompts).
- Integration with external CI systems for test pass rate collection.

## Sequencing

```
Phase 1 (v0.11.0): Outcome Inference Accuracy Audit
  → Decision gate: if precision < 0.5, fix auto_apply before proceeding
  → If estimate in 0.4–0.6, extend N=50 → N=100 before deciding

Phase 2 (v0.11.0): Ranking Snapshot Capture → Precision Benchmark
  → Capture ships first; labeling starts after ~100 snapshots accumulate
  → Weight tuning via cross-validation, only if lift exceeds CV noise

Phase 3 (v0.12.0): Injection On/Off Crossover Experiment
  → Requires Phase 1 passing (feedback loop is trustworthy)
  → Requires 4+ block pairs; report directional signal with declared power

Phase 4 (v0.13.0, conditional): Comparative Baseline
  → Only if Phase 3 shows positive directional signal
```

Phase 1 is gating because if outcome inference is broken, all downstream metrics (quality score, ranking, block-level quality signals) are built on sand.

## Risks

- **Underpowered by construction**: solo-dogfooding volume cannot reach conventional significance for rare-event proxies like revert rate. Mitigation: report effect direction + CI + achieved power honestly; scale users before making strong claims.
- **Cross-block carryover**: even with time blocks, decisions applied in ON blocks persist in the codebase and benefit OFF blocks. Crossover reduces but does not eliminate this; treat estimates as lower bounds on the true effect.
- **Not blind**: the operator notices missing injections and may compensate with manual retrieval. Mitigation: measure manual retrieval per block and report which estimand was actually measured.
- **Proxy validity**: revert rate and turn count may not correlate with actual code quality. Mitigation: treat as directional signals, not proof; supplement with human review on a subset.
- **Annotation bias**: single annotator who is also the author. Mitigation: label-blinding, rationale-first verdicts, double-label a subset when a second annotator is available.
- **Snapshot storage**: ranking snapshots persist diff text, which may contain secrets. Mitigation: reuse the existing content_filter redaction path before persisting; gate behind opt-in config.
- **Survivorship bias**: only decisions that survived extraction + confirmation are evaluated; the system may be filtering out the most useful candidates before they reach the ranker.

## Review Questions

- Is weekly the right block length, or do shorter blocks (3-4 days) give more pairs at acceptable carryover cost?
- Should the injection experiment also suppress SessionStart surfacing files (the F4 async path), or only `additionalContext` injection?
- For the ranking benchmark, is 100 labeled cases enough to start, given 5-fold CV — or should labeling wait for 150?
- Should ranking snapshots be sampled (e.g., 1 in 3 calls) to bound storage growth, or captured exhaustively while the config is on?
- Should we add an explicit "was this useful?" prompt to `ec context apply` as a lightweight ground-truth source, even though it biases toward positive responses?
