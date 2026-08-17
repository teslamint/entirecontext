# 0014. Balance Verdict Enrichment Before Recency

**Status:** accepted
**Date:** 2026-08-17
**EC Decision:** `c2d371bc-0015-4a92-b7e2-d3ddd95a0ff5`

## Context

The verdict-accuracy gate reached 39 enriched assessments and 97.4% agreement, but every measured original verdict was `neutral`. `get_enrichment_candidates()` selected the newest rule-based rows globally, so high-volume neutral checkpoints displaced `expand` and `narrow` rows from every ten-item batch. The total sample size therefore met the ROADMAP threshold without measuring the mappings that the row was meant to evaluate.

Candidate selection also did not exclude rows that already carried feedback. Although successful LLM enrichment changes `model_name` and normally removes such rows from later batches, manually feedbacked rule-based rows remained eligible for overwrite. Filtering selection alone is insufficient: feedback can also arrive while the slow LLM call is in flight.

## Decision

Select only unfeedbacked rule-based assessments within the existing time and optional session scope. Assign each eligible row a one-based ordinal within its verdict, ordered by newest creation time and descending identifier. Order the final batch by this ordinal before global recency and apply the existing global limit.

After the LLM call, write the enriched fields and automatic feedback in one conditional statement guarded by the original eligibility state: `model_name = 'rule-based' AND feedback IS NULL`. If another writer changed either field, the conditional write affects zero rows and enrichment reports no update. Do not hold a database transaction across the LLM call.

This is deterministic verdict-balanced round-robin selection with optimistic compare-and-set persistence. It gives every available verdict one opportunity before any verdict gets a second row, preserves progress when only one verdict exists, and keeps feedback recorded during enrichment authoritative. It does not fabricate missing classes or claim that the resulting sample is statistically balanced.

Keep the existing function signatures, selected row shape, CLI behavior, schema, and configuration unchanged.

## Consequences

- Recent minority-verdict rows can enter normal enrichment batches.
- Existing manual or automatic feedback remains authoritative.
- The newest global rows are no longer always selected when a minority verdict has an older in-window candidate.
- A verdict absent from the eligible window still has zero support and must be reported as an evidence limitation.
- The window-function query is more complex than a global recency sort, but the bounded batch size and existing SQLite requirement make a new index or queue table unnecessary.
- A concurrent feedback writer can win without waiting for the LLM call or having its result overwritten.

## Rejected Alternatives

- **Keep global recency:** preserves the observed neutral-only measurement bias.
- **Random sampling:** loses reproducibility and can still omit a minority verdict.
- **Fixed per-verdict quotas:** under-fills sparse batches or requires redistribution policy and configuration without evidence that users need it.
- **Rewrite verdict mapping immediately:** changes behavior without representative `expand` or `narrow` evidence.
- **Persist queue state:** adds schema and lifecycle complexity for a deterministic query problem.
- **Recheck after the LLM call, then update separately:** remains racy between the check and update.
- **Hold a write transaction across the LLM call:** avoids the race by blocking other writers for an unbounded external call.

## Verification

The governing Specification names mixed-backlog, deterministic-tie, feedback-exclusion, filter-preservation, and concurrent-feedback tests. The owning module tests and a fresh dogfood accuracy report provide implementation and outcome evidence.

## References

- Specification: [`docs/specs/2026-08-17-verdict-balanced-enrichment-design.md`](../specs/2026-08-17-verdict-balanced-enrichment-design.md)
- ROADMAP item: [`ROADMAP.md`](../../ROADMAP.md)
