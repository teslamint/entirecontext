# Hypothesis Validation Framework

_Draft brainstorm. Created 2026-07-04. Milestone: v0.11.0. Confidence: 78%._

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
| Q1 | Does surfacing decisions change agent behavior? | proxy: file overlap → "accepted" | causal: controlled comparison |
| Q2 | When behavior changes, is the outcome better? | none | quality measurement on output |
| Q3 | Does the ranker surface the right decisions? | none | precision@k against human labels |

## Approach 1: Holdout Experiment (Q1 + Q2)

### Design

A/B split at session level: inject decisions in treatment sessions, suppress in control sessions. Measure output quality difference.

| Dimension | Treatment | Control |
|-----------|-----------|---------|
| `inject_on_user_prompt` | true | false |
| `surface_on_session_start` | true | false |
| Decision MCP tools | enabled | enabled (but no proactive injection) |

Assignment: config key `[decisions.injection] holdout_probability = 0.0` (default off). When > 0, each SessionStart flips a coin; holdout sessions get `inject_on_user_prompt = false` silently. Session metadata records `{"holdout": true/false}`.

### Quality Signals (output proxies)

Since we cannot measure "code quality" directly without human review, use observable proxies:

| Signal | Source | Hypothesis |
|--------|--------|-----------|
| Commit revert rate | git log: revert commits within 24h of original | Treatment has fewer reverts |
| Assessment verdict distribution | expand/narrow/neutral ratio | Treatment has higher expand rate |
| Session duration for similar tasks | session metadata | Treatment is faster (fewer turns to completion) |
| Test pass rate post-session | CI results if available | Treatment introduces fewer test failures |
| Decision contradiction rate | outcome_type = contradicted in subsequent sessions | Treatment decisions get contradicted less |

### Minimum Sample Size

Power analysis: to detect a 15% difference in revert rate (baseline ~10%) at α=0.05, β=0.80 → ~350 sessions per arm. At current dogfooding cadence (~5 sessions/day), this requires ~140 days or deliberate adoption scaling.

Pragmatic alternative: start with paired comparison on the same user doing similar tasks, reducing variance. 50 paired sessions may suffice for directional signal.

### Implementation

- [ ] Add `holdout_probability` config key under `[decisions.injection]`.
- [ ] SessionStart handler: if rand < holdout_probability, set session metadata `holdout=true` and suppress all proactive injection for this session.
- [ ] AAR: record holdout status in after-action report.
- [ ] New CLI: `ec experiment report` — aggregate quality signals split by holdout status, compute effect size + confidence interval.

## Approach 2: Outcome Inference Accuracy Audit (validates Loop 1)

### Problem

`auto_apply.py` infers "accepted" when surfaced-decision files overlap with modified files. False positive rate is unknown.

### Design

Sample N=50 sessions where auto-apply inferred "accepted". For each, a human reviewer answers: "Did the agent actually use this decision's guidance, or was the file modification coincidental?"

| Verdict | Meaning |
|---------|---------|
| True positive | Agent visibly followed the decision |
| False positive | File overlap was coincidental |
| Ambiguous | Cannot determine from transcript |

### Implementation

- [ ] New CLI: `ec experiment sample-outcomes --type accepted --count 50` — outputs session_id, decision_id, files_overlap, and a link to the relevant turn content for human review.
- [ ] Reviewer records verdict in a JSONL file: `{session_id, decision_id, verdict}`.
- [ ] New CLI: `ec experiment outcome-accuracy --verdicts <path>` — computes precision of the auto-apply heuristic.

### Decision Gate

If precision < 0.5 (more than half of "accepted" are false positives), the entire quality → ranking feedback loop is corrupted and must be redesigned before trusting the holdout experiment results.

## Approach 3: Ranking Precision Benchmark (Q3)

### Problem

`rank_related_decisions()` returns top-k decisions for a given context (files, diff, commits). No ground truth exists for whether those k decisions are actually relevant.

### Design

Offline evaluation dataset: collect N=100 real (context, surfaced_decisions) pairs from telemetry. A human annotator labels each surfaced decision as relevant/irrelevant/partially-relevant.

Metrics:
- **Precision@5**: fraction of top-5 that are relevant
- **NDCG@5**: position-weighted relevance
- **MRR**: mean reciprocal rank of first relevant decision

### Implementation

- [ ] New CLI: `ec experiment export-ranking-cases --count 100` — extracts (context_signals, ranked_decisions, metadata) from retrieval_events + retrieval_selections.
- [ ] Annotation format: JSONL with `{case_id, decision_id, relevance: 0|1|2}`.
- [ ] New CLI: `ec experiment ranking-eval --annotations <path>` — computes P@5, NDCG@5, MRR.
- [ ] Once baseline established: grid search over RankingWeights to maximize NDCG@5 on the labeled set.

### Weight Tuning Protocol

After 100+ labeled cases:
1. Split 70/30 train/test.
2. Grid search on train: vary `file_exact_weight`, `diff_relevance_weight`, `quality_weight` within ±50% of defaults.
3. Evaluate on test: report NDCG@5 lift over default weights.
4. If lift > 10%, ship new defaults. If < 5%, current weights are adequate.

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

### Pragmatic Start

This is expensive. Defer until Approach 1 shows directional signal. If holdout shows no effect, skip this and accept the article's thesis applies to us too.

## Scope

### In

- Holdout experiment infrastructure (config key, session metadata, report CLI).
- Outcome inference accuracy audit tooling (sample, annotate, evaluate).
- Ranking precision benchmark tooling (export, annotate, evaluate).
- Documentation of methodology and decision gates.

### Out

- Automated weight tuning in production (defer until benchmark shows > 10% lift opportunity).
- Three-arm comparative study (defer until holdout shows signal).
- Changes to existing ranking or injection logic (this is measurement only).
- User-facing feedback UI ("was this helpful?" prompts).
- Integration with external CI systems for test pass rate collection.

## Sequencing

```
Phase 1 (v0.11.0): Outcome Inference Accuracy Audit
  → Decision gate: if precision < 0.5, fix auto_apply before proceeding

Phase 2 (v0.11.0): Ranking Precision Benchmark
  → Establishes baseline; enables weight tuning if lift > 10%

Phase 3 (v0.12.0): Holdout Experiment
  → Requires Phase 1 passing (feedback loop is trustworthy)
  → Requires sufficient session volume (~100 paired sessions minimum)

Phase 4 (v0.13.0, conditional): Comparative Baseline
  → Only if Phase 3 shows positive effect
```

Phase 1 is gating because if outcome inference is broken, all downstream metrics (quality score, ranking, holdout quality signals) are built on sand.

## Risks

- **Sample size**: dogfooding cadence may be too low for statistical significance. Mitigation: start with paired comparisons; recruit additional users.
- **Hawthorne effect**: knowing a session is being evaluated changes behavior. Mitigation: holdout is silent; user doesn't know which arm they're in.
- **Proxy validity**: commit revert rate and session duration may not correlate with actual code quality. Mitigation: treat as directional signals, not proof; supplement with human review on a subset.
- **Annotation cost**: ranking benchmark requires human labeling of 500+ (decision, context) pairs. Mitigation: start with 100; assess inter-annotator agreement before scaling.
- **Survivorship bias**: only decisions that survived extraction + confirmation are evaluated; the system may be filtering out the most useful candidates before they reach the ranker.

## Review Questions

- Is 50 sessions sufficient for the outcome inference audit, or should we require 100 for robust precision estimates?
- Should the holdout experiment be per-user (consistent experience) or per-session (more samples faster)?
- For the ranking benchmark, should "partially relevant" count as 0.5 or be treated as a separate category in NDCG?
- Is commit revert rate actually observable in single-developer repos, or is it too rare to be a useful signal?
- Should we add an explicit "was this useful?" prompt to `ec context apply` as a lightweight ground-truth source, even though it biases toward positive responses?
