# 0009. Bounded Verdict Floor for Lesson Selection

**Status:** accepted
**Date:** 2026-08-15
**EC Decision:** `23b1d3e8-9fdd-4f0c-bd8f-4baba74db93b`

## Context

`get_lessons()` supplied the generated `LESSONS.md`, CLI, MCP, and automatic
distillation paths from one global recency window. In the measured 120-row
feedback corpus, the newest 50 rows contained 49 `neutral` lessons and one
`expand` lesson even though the corpus contained 22 `expand` lessons. Each
neutral assessment of the regenerated artifact could evict another
option-shaping lesson.

The existing `limit` contract is a total result cap, not a per-verdict cap.
Selection must therefore preserve recency as the majority signal, handle
verdicts with fewer rows than their reservation, and remain tunable for callers
that require pure recency.

## Decision

`get_lessons()` reserves up to `min_per_verdict` candidates for each verdict in
`VALID_VERDICTS`. Total reservations are capped at `limit // 2`; remaining
slots are filled by global `(created_at, id)` recency. The public repository
configuration key is `futures.lessons_min_per_verdict`, defaulting to `5`.
Setting it to `0` disables reservations.

Eligibility predicates such as CLI `--since` are applied to each candidate
partition before reservations are allocated; ineligible reserved rows must not
displace eligible rows and then disappear in post-processing.

Candidate rows are read in one SQLite statement so all verdict partitions share
a snapshot. Schema v18 adds the partial ordered index
`idx_assessments_feedback_recency` on
`(verdict, created_at DESC, id DESC) WHERE feedback IS NOT NULL`, keeping each
partition's ordered candidate read index-backed as assessment history grows.

Rejected alternatives:

- Keep pure global recency — measured neutral growth collapsed the default
  window to `expand 1 / neutral 49` and reinforced the collapse on every neutral
  assessment of `LESSONS.md`.
- Split the result equally across verdicts — would replace corpus-sensitive
  recency with a fixed one-third allocation.
- Let reservations consume the entire limit — small-limit calls become
  quota-only; the half-cap preserves at least half the budget for recency.
- Use `ROW_NUMBER() OVER (PARTITION BY verdict)` — the repository has no window
  function precedent. Bounded CTE candidates provide one snapshot without
  adding window semantics.

## Consequences

- Minority verdict lessons remain represented while recent lessons still occupy
  at least half the result.
- Missing or undersized verdict partitions forfeit unused reservations; the
  total result may still fill to `limit` from other verdicts.
- CLI, MCP, and hook-driven distillation must all pass the same repository
  configuration value; dedicated regression tests protect those entry points.
- Selection now depends on schema v18's partial composite index. Fresh databases
  create it from the canonical schema, and existing databases receive it through
  migration v18.
- Adding a verdict requires updating `VALID_VERDICTS`, the lesson renderer, and
  the related selection tests together.
- Plan: `docs/plans/2026-08-15-001-fix-lessons-verdict-quota-plan.md`;
  EC decision: `23b1d3e8-9fdd-4f0c-bd8f-4baba74db93b`.
