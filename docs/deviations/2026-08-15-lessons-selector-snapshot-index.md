# Deviation: lesson selector snapshot and ordered index

**Date:** 2026-08-15
**Author:** implementation session for the verdict-quota review
**Authorized by:** user instruction to fix all final-review findings

## Original contract

The approved, sealed plan is
`docs/plans/2026-08-15-001-fix-lessons-verdict-quota-plan.md`.

It makes two implementation commitments that the reviewed implementation no longer follows:

1. Architecture notes at lines 67-72 select three independent, bounded per-verdict
   `SELECT` statements with Python post-processing.
2. The File structure table at lines 127-143 names every planned file and concludes
   "No file is created."

U1 steps 3-4 at lines 300-343 repeat the three-query implementation literally.

## Observable behavior that deviates

The final selector differs in two ways:

1. `src/entirecontext/core/futures.py` reads all three bounded verdict partitions in one
   `WITH ... UNION ALL` statement, then performs the same floor reservation and global-recency
   top-up in Python.
2. Schema v18 adds the ordered partial index
   `idx_assessments_feedback_recency` on
   `(verdict, created_at DESC, id DESC) WHERE feedback IS NOT NULL`. This creates
   `src/entirecontext/db/migrations/v018.py` and
   `tests/test_migration_v018.py`, and updates the schema and migration registry.

The public floor allocation, total-cap, recency, deterministic tie-break, configuration, CLI,
MCP, and automatic-distillation contracts remain unchanged. A later review fix adds the existing
CLI `--since` predicate to each candidate partition before allocation; it does not change callers
that omit `since`.

## Why the deviation is authorized

Independent review reproduced a concurrent enrichment between separate verdict reads: one
assessment could move from one verdict partition to another and be selected twice. Three
independent autocommit statements cannot guarantee one read snapshot. One SQLite statement does.

The same review measured the planned queries building temporary B-trees for
`ORDER BY created_at DESC, id DESC`. The ordered partial index removes those sorts while retaining
bounded reads. A conditional migration no-op was rejected because it could mark a damaged database
as schema v18 without the index, breaking schema-version meaning and ADR 0009's invariant.

The user directed the session to fix all final-review findings. This addendum records that authority
without rewriting the sealed plan.

## Verification and rollback

- `tests/test_futures.py` covers concurrent verdict mutation, duplicate suppression by one snapshot,
  deterministic tie ordering, pre-allocation `since` filtering, floor allocation, shortfalls,
  limits, and the zero-floor compatibility path.
- `tests/test_migration_v018.py` covers v17-to-v18 migration, fresh-schema parity, idempotence, index
  SQL, and `EXPLAIN QUERY PLAN` use without a temporary B-tree.
- Full verification after the review fixes: `2204 passed, 1 skipped`; mypy clean; ruff clean. A final
  rerun is required after the `since` fix and this addendum.
- Rollback is forward compensation: reinstall a selected base revision and use its schema-aware
  code. SQLite indexes may safely remain if application code no longer depends on them.

## Traceability

- ADR: `docs/adr/0009-bounded-verdict-floor-for-lessons.md`
- EC decision: `23b1d3e8-9fdd-4f0c-bd8f-4baba74db93b`
- Plan: `docs/plans/2026-08-15-001-fix-lessons-verdict-quota-plan.md`
- Review findings: snapshot consistency, ordered query-plan performance, and sealed-plan deviation
  findings from the final implementation review
