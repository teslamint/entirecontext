# Verdict-Balanced Enrichment Implementation Plan

> **For agentic workers:** execute this Plan as one independently reviewable measurement-correctness unit. Use test-driven development and preserve every Specification-named test.

**Goal:** Close ROADMAP 231 by removing neutral-volume bias from enrichment candidate selection and measuring representative verdict support.

**Architecture:** Replace the global-recency candidate query with one snapshot-consistent SQLite window query: filter eligibility first, rank within verdict, then order by per-verdict rank and deterministic recency. Preserve every caller and returned field. Use the normal enrichment CLI against the repository dogfood database only after focused tests pass.

**Tech Stack:** Python 3.12+, SQLite window functions, pytest, Markdown.

**Spec:** `docs/specs/2026-08-17-verdict-balanced-enrichment-design.md`

**Decision:** EC decision `c2d371bc-0015-4a92-b7e2-d3ddd95a0ff5`; companion ADR `docs/adr/0014-verdict-balanced-enrichment.md`

## Global Constraints

- Do not change verdict mapping without measured non-neutral evidence.
- Do not add schema, indexes, configuration, dependencies, CLI options, or queue state.
- Preserve the function signature and returned row fields.
- Exclude every feedback-bearing row before ranking.
- Use deterministic ordering at both ranking levels.
- Restore any temporary local backend override before commit.
- Do not commit local database, AAR, worker, `.entire/`, `.opencode/`, or hook-generated `LESSONS.md` artifacts.

## Assumption Recheck

The approved Specification retains one live measurement assumption. The repository accuracy command was rerun before Plan authoring and matched: 39 enriched assessments, 97.4% agreement, with all 39 original verdicts neutral. The selector source also matched the stated recency-only query and absent feedback filter.

## File Structure

- Modify `src/entirecontext/core/auto_assess.py`: verdict-balanced candidate query only.
- Modify `tests/test_auto_assess.py`: four observable selector contracts.
- Modify `ROADMAP.md`: close row 231 with measured post-change evidence.
- Create `docs/specs/2026-08-17-verdict-balanced-enrichment-design.md`: approved behavioral contract.
- Create `docs/adr/0014-verdict-balanced-enrichment.md`: durable selection-policy rationale.
- Create `docs/superpowers/plans/2026-08-17-006-verdict-balanced-enrichment-plan.md`: executable work contract.
- Create `docs/plans/evidence/2026-08-17-006-verdict-balanced-enrichment-plan-cf501eb51e72/verdict-selector.json`: hash-bound authoring evidence.

## Carry-Forward Trigger Audit

The audit rechecked all 19 distinct open ROADMAP workstreams from the ordered backlog. Drift-based rows 204/265/300/301/382 remain fired and belong to the separate measurement-telemetry unit already in progress. Row 231 is fired and folded into this Plan. Edit-based rows 209, 336, 338/384, 353-359, 362-365, and 379 do not name this Plan's source or test files; row 231 is the only selector-specific overlap. Event/product rows 395, 411, 413, and 418 remain deferred to their ordered units. Shipped-but-unclosed Exploration rows 437 and 439 remain in the later backlog-reconciliation unit. No open row is silently dropped.

## Scenario Coverage Map

| Scenario | Unit chain | Observable evidence |
|---|---|---|
| S1 mixed backlog | Task 1 tests -> Task 2 query -> Task 3 dogfood | `test_get_enrichment_candidates_balances_available_verdicts`; post-change per-verdict report |
| S2 authoritative feedback | Task 1 test -> Task 2 eligibility predicate | `test_get_enrichment_candidates_excludes_feedbacked_rows` |
| S3 sparse/scoped backlog | Task 1 tests -> Task 2 query | deterministic and filter-preservation tests |

## Spec Test Disposition

| Spec test | Disposition | Plan test(s) | Rationale |
|---|---|---|---|
| `test_get_enrichment_candidates_balances_available_verdicts` | retained | `test_get_enrichment_candidates_balances_available_verdicts` | — |
| `test_get_enrichment_candidates_orders_each_verdict_deterministically` | retained | `test_get_enrichment_candidates_orders_each_verdict_deterministically` | — |
| `test_get_enrichment_candidates_excludes_feedbacked_rows` | retained | `test_get_enrichment_candidates_excludes_feedbacked_rows` | — |
| `test_get_enrichment_candidates_preserves_session_window_and_limit` | retained | `test_get_enrichment_candidates_preserves_session_window_and_limit` | — |

---

### Task 1: Pin selector behavior with failing tests

**Files:**
- Modify: `tests/test_auto_assess.py`
- Test: `tests/test_auto_assess.py`

- [x] **Step 1: Add deterministic assessment fixtures**

Create assessments with explicit IDs and timestamps by using existing session/checkpoint/assessment APIs, then update only their timestamps where ordering control is needed. Keep all data inside `ec_db` and repository fixtures.

- [x] **Step 2: Add all four Specification-named tests**

Assert mixed-backlog rank interleaving, deterministic within-verdict tie handling, feedback exclusion, and combined session/window/limit behavior through the public `get_enrichment_candidates()` interface. Assert exact IDs or verdict sequences, not SQL text.

- [x] **Step 3: Run the four tests before implementation**

Confirm the balance and feedback-exclusion tests fail against the global-recency selector for their intended observable mismatches. Do not alter production code until the failures are observed.

### Task 2: Implement verdict-balanced selection

**Files:**
- Modify: `src/entirecontext/core/auto_assess.py`
- Test: `tests/test_auto_assess.py`
- Test: `tests/test_verdict_accuracy.py`

- [x] **Step 1: Filter and rank in one query**

Use a common-table expression that filters rule-based, unfeedbacked, in-window, optionally session-scoped rows before applying `ROW_NUMBER() OVER (PARTITION BY verdict ORDER BY created_at DESC, id DESC)`.

- [x] **Step 2: Bound the ranked batch deterministically**

Select the unchanged row fields from the ranked relation, order by verdict rank, then `created_at DESC, id DESC`, and apply the existing limit. Keep positional parameters for window, optional session, and limit.

- [x] **Step 3: Run focused owning-module verification**

```bash plan-check id=verdict-selector expected-status=0 evidence=docs/plans/evidence/2026-08-17-006-verdict-balanced-enrichment-plan-cf501eb51e72/verdict-selector.json
set -euo pipefail
uv run pytest -q tests/test_auto_assess.py tests/test_verdict_accuracy.py
```

### Task 3: Measure the mapping gate and close the row

**Files:**
- Modify: `ROADMAP.md`

- [x] **Step 1: Enrich one normal batch with the available Codex backend**

Temporarily point the local untracked EntireContext configuration at Codex, run one normal backlog enrichment batch, and immediately restore the prior backend value. Do not stage runtime artifacts.

- [x] **Step 2: Record the actual accuracy result**

Run the existing accuracy command. Record total support, agreement, per-verdict support, and any verdict class still absent. Do not infer mapping quality for a zero-support class.

- [x] **Step 3: Close ROADMAP 231 without changing mappings unless evidence requires it**

Mark the row complete with the measured result. If a non-neutral disagreement exposes a mapping defect, add a failing mapping test before changing the mapping; otherwise state that no mapping change was warranted.

## Mutation/Failure-State Matrix

No stateful ceremony in the deliverable; no mutation/failure-state matrix required.

## Open Unknowns

**Planning-time:** None.

**Implementation-time:** The post-change per-verdict counts depend on the eligible seven-day dogfood backlog and Codex responses. The Plan requires reporting the observed counts rather than predicting them.

## Deferred to Follow-Up Work

- Statistical confidence intervals or a fixed minimum per verdict; the current row gates on total `n>=30`, and the immediate defect is zero support caused by selection bias.
- A new enrichment index; the bounded dogfood query does not justify schema expansion without measured latency pressure.
- Rule-mapping changes unsupported by the diversified result.

## Self-Review

- Every Specification test is retained and mapped.
- All three user scenarios have an implementation chain and observable evidence.
- The changed function has two callers (`futures enrich-backlog` and SessionEnd's background worker); both consume the same unchanged list-of-dicts contract.
- Snapshot consistency, deterministic ordering, global limit, and feedback authority are explicit invariants.
- The Plan adds no outward publication or durable state transition beyond normal local assessment enrichment; no stateful ceremony applies.
- The ROADMAP carry-forward row is folded into Task 3; other fired drift rows retain their separate ordered unit.
- No planning-time unknown remains.
