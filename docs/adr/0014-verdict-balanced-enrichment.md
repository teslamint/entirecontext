# 0014. Balance Verdict Enrichment Before Recency

**Status:** accepted
**Date:** 2026-08-17
**EC Decision:** `c2d371bc-0015-4a92-b7e2-d3ddd95a0ff5`

## Context

The verdict-accuracy gate reached 39 enriched assessments and 97.4% agreement, but every measured original verdict was `neutral`. `get_enrichment_candidates()` selected the newest rule-based rows globally, so high-volume neutral checkpoints displaced `expand` and `narrow` rows from every ten-item batch. The total sample size therefore met the ROADMAP threshold without measuring the mappings that the row was meant to evaluate.

The selector also did not exclude rows that already carried feedback. Although successful LLM enrichment changes `model_name` and normally removes such rows from later batches, manually feedbacked rule-based rows remained eligible for overwrite.

## Decision

Select only unfeedbacked rule-based assessments within the existing time and optional session scope. Assign each eligible row a one-based ordinal within its verdict, ordered by newest creation time and descending identifier. Order the final batch by this ordinal before global recency and apply the existing global limit.

This is deterministic verdict-balanced round-robin selection. It guarantees one opportunity for every available verdict before any verdict gets a second row, while preserving progress when only one verdict exists. It does not fabricate missing classes or claim that the resulting sample is statistically balanced.

Keep the existing function signature, selected row shape, CLI behavior, schema, and configuration unchanged.

## Consequences

- Recent minority-verdict rows can enter normal enrichment batches.
- Existing manual or automatic feedback remains authoritative.
- The newest global rows are no longer always selected when a minority verdict has an older in-window candidate.
- A verdict absent from the eligible window still has zero support and must be reported as an evidence limitation.
- The window-function query is more complex than a global recency sort, but the bounded batch size and existing SQLite requirement make a new index or queue table unnecessary.

## Rejected Alternatives

- **Keep global recency:** preserves the observed neutral-only measurement bias.
- **Random sampling:** loses reproducibility and can still omit a minority verdict.
- **Fixed per-verdict quotas:** under-fills sparse batches or requires redistribution policy and configuration without evidence that users need it.
- **Rewrite verdict mapping immediately:** changes behavior without representative `expand` or `narrow` evidence.
- **Persist queue state:** adds schema and lifecycle complexity for a deterministic query problem.

## Verification

The governing Specification names mixed-backlog, deterministic-tie, feedback-exclusion, and filter-preservation tests. The owning module tests and a fresh dogfood accuracy report provide implementation and outcome evidence.

## References

- Specification: [`docs/specs/2026-08-17-verdict-balanced-enrichment-design.md`](../specs/2026-08-17-verdict-balanced-enrichment-design.md)
- ROADMAP item: [`ROADMAP.md`](../../ROADMAP.md)
