---
title: Verdict-Balanced Enrichment
status: approved
date: 2026-08-17
schema: spec/v1
---

# Verdict-Balanced Enrichment Design

## Overview

`ec checkpoint assess-accuracy` has crossed the ROADMAP's `n>=30` gate, but its measured sample is not representative: the 2026-08-17 pre-change measurement reported 39 enriched assessments at 97.4% agreement, and all 39 original rule verdicts were `neutral`. The enrichment queue currently chooses the newest rule-based assessments without regard to verdict, so neutral checkpoint volume can indefinitely hide `expand` and `narrow` mapping quality.

The governing EC decision is `c2d371bc-0015-4a92-b7e2-d3ddd95a0ff5`.

## Goals

1. Give every available rule verdict a bounded opportunity to enter each enrichment batch.
2. Preserve recency ordering within each verdict and deterministic ordering across the final batch.
3. Never select an assessment that already carries feedback.
4. Preserve the existing window, session, and limit filters.
5. Use the diversified sample to finish the ROADMAP verdict-mapping evaluation with measured per-verdict evidence.

## Non-Goals

- Changing the rule mapping from commit prefixes to `expand`, `narrow`, or `neutral` before representative evidence exists.
- Adding user-facing CLI options, configuration, schema, dependencies, random sampling, or persistent queue state.
- Manufacturing absent verdict classes or requiring a fixed quota when fewer candidates exist.
- Rewriting historical enrichment feedback.

## User Scenarios

### S1. A mixed backlog is enriched fairly

A repository has recent unfeedbacked rule-based assessments across multiple verdicts. A normal enrichment batch includes candidates from each available verdict before taking a second candidate from a high-volume verdict.

### S2. Existing outcomes remain authoritative

A rule-based assessment already has manual or automatic feedback. Candidate selection excludes it, so enrichment cannot overwrite the recorded outcome. If feedback arrives after selection while the LLM call is running, the enrichment write detects the changed row and leaves its model, verdict, and feedback unchanged.

### S3. Sparse backlogs still make progress

A repository has only one available verdict, fewer rows than the requested limit, or a session-scoped subset. Candidate selection returns the available rows in deterministic newest-first order without padding or failure.

## Functional Contract

`get_enrichment_candidates(conn, session_id=None, window_days=7, limit=10)` remains the only selection interface.

Eligibility requires all of the following:

- `assessments.model_name = 'rule-based'`
- `assessments.feedback IS NULL`
- creation within the requested time window
- membership in the requested session when `session_id` is supplied

Eligible rows receive a one-based rank within their verdict, ordered by `created_at DESC, id DESC`. The final batch orders by that verdict rank first, then `created_at DESC, id DESC`, and applies the existing global limit. This round-robin shape gives every available verdict one opportunity before any verdict receives a second candidate while retaining deterministic recency.

The returned row shape and the caller contract remain unchanged.

`enrich_assessment()` persists the enriched fields and automatic feedback in one `UPDATE` guarded by `id`, `model_name = 'rule-based'`, and `feedback IS NULL`. A zero-row update means eligibility changed during the LLM call; the function reports no update and does not retry or overwrite the newer state.

## Acceptance Evidence

- **AE1:** With four neutral, two expand, and one narrow candidate, `limit=3` returns one row from each verdict; `limit=5` returns the three rank-1 rows before any rank-2 row.
- **AE2:** Within a verdict, newer `created_at` wins and `id DESC` breaks timestamp ties.
- **AE3:** Feedback-bearing and non-rule-based assessments are absent from the result.
- **AE4:** Session, time-window, sparse-backlog, and global-limit behavior remain intact.
- **AE5:** Feedback written during the LLM call remains byte-for-byte authoritative; enrichment reports no update.
- **AE6:** A post-change dogfood measurement records total enriched sample size, agreement rate, and per-verdict support; the ROADMAP row is closed with the actual measured result rather than an assumed mapping change.

## Testing

- `test_get_enrichment_candidates_balances_available_verdicts`
- `test_get_enrichment_candidates_orders_each_verdict_deterministically`
- `test_get_enrichment_candidates_excludes_feedbacked_rows`
- `test_get_enrichment_candidates_preserves_session_window_and_limit`
- `test_enrich_assessment_preserves_feedback_written_during_llm_call`

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| A high-volume verdict still dominates after the first round | Rank by per-verdict ordinal before global recency, so each available verdict receives rank-1 priority. |
| Nondeterministic ties produce unstable batches | Use `created_at DESC, id DESC` in both the partition and final ordering. |
| Existing human feedback is overwritten before or during enrichment | Filter `feedback IS NULL` during selection, then atomically compare-and-set enrichment plus automatic feedback after the LLM call. |
| SQL window behavior diverges from the existing interface | Keep the function signature and selected columns unchanged; run the full owning module tests. |
| Balanced selection is mistaken for balanced accuracy | Report actual per-verdict support; do not claim quality for verdicts with zero measured rows. |

## Success Criteria

- The five Specification-named tests pass and fail against the relevant pre-change selector or unconditional enrichment write for the intended reasons.
- Existing `tests/test_auto_assess.py` and `tests/test_verdict_accuracy.py` pass unchanged apart from additive coverage.
- The post-change accuracy report has at least 30 enriched assessments and explicitly reports support for every verdict that the recent eligible backlog can supply.
- ROADMAP line 231 is closed with the observed result and any remaining evidence limitation.

## Measurement Baseline

Command run before implementation: `ec checkpoint assess-accuracy`.

Observed 2026-08-17: 1,347 pending rule-based assessments, 39 enriched assessments, 97.4% agreement, and per-verdict support `neutral=39`, `expand=0`, `narrow=0`.

## Decision Reuse

- Applied `283186e7-c98f-4f1e-9325-ad46c63e6050`: this ROADMAP carry-forward is registered and must be resolved or explicitly re-registered.
- Applied `c2d371bc-0015-4a92-b7e2-d3ddd95a0ff5`: deterministic verdict-balanced selection is preferred over random sampling, recency-only sampling, and configurable quotas.
- Reviewed the lesson on verdict-floor selection and reused its snapshot-consistent, deterministic, bounded-allocation principles; no schema or index change is needed for a ten-row enrichment batch.

## Open Questions

None. The direct instruction to execute the ordered ROADMAP backlog without intermediate questions authorizes this internal selection-policy change; measured evidence, not an assumed rule rewrite, determines closure.
