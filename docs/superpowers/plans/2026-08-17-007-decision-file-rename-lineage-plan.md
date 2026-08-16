# Decision File Rename Lineage Implementation Plan

> **For agentic workers:** implement each task test-first and verify the whole changed module before commit.

**Goal:** Preserve exact path-based decision retrieval and outcome feedback through committed, transitive Git renames without adding Git work to query or PostToolUse paths.

**Architecture:** Schema v19 stores Git-proven rename edges plus one repository-local scan watermark. A new core synchronizer scans committed rename records at SessionStart, persists lineage, recursively materializes destination paths into the existing `decision_files` read model, and advances the watermark atomically. Existing readers and public interfaces remain unchanged.

**Tech Stack:** Python 3.10+, SQLite recursive CTEs, Git plumbing, pytest real-repository fixtures.

**Spec:** `docs/specs/2026-08-17-decision-file-rename-lineage-design.md`

**Decision:** EC decision `235ba317-fd3b-4682-b8c9-52fccf0ba78c`; companion ADR `docs/adr/0015-decision-file-rename-lineage.md`

## Global Constraints

- Treat Git `R<score>` records as the only rename authority; do not propagate copies.
- Preserve every historical `decision_files` row.
- Advance the watermark only in the same successful transaction as lineage insertion and destination propagation.
- Keep every CLI, MCP, and `get_decision()['files']` return shape unchanged.
- Keep PostToolUse subprocess-free and within its existing three-second budget.
- Fail SessionStart open through the existing hook warning mechanism.
- Do not change path normalization beyond the current leading-`./` and backslash behavior.

## Assumption Recheck

The approved Spec's live assumptions were rechecked on 2026-08-17:

- **match:** `decision_outcomes` references `decision_id`, not paths.
- **match:** `decision_files` has no lineage or alias relation in schema v18.
- **match:** exact ranking exposes `score_breakdown.file_exact == 3.0`.
- **match:** extraction feedback exposes deterministic per-path outcome counts.
- **match:** PostToolUse documents a three-second exact-match path and performs no Git subprocess today.

No contradiction or unavailable evidence remains.

## File Structure

- Create `src/entirecontext/db/migrations/v019.py`: strict canonical lineage-table/index migration.
- Modify `src/entirecontext/db/migrations/__init__.py`: register schema v19.
- Modify `src/entirecontext/db/schema.py`: schema version and fresh-schema objects.
- Create `src/entirecontext/core/decision_file_lineage.py`: Git log parser, scan-range selection, transactional propagation.
- Modify `src/entirecontext/hooks/decision_hooks.py`: fail-open repository synchronization helper.
- Modify `src/entirecontext/hooks/handler.py`: invoke synchronization before SessionStart decision ranking.
- Create `tests/test_migration_v019.py`: migration strictness, rollback, and bootstrap parity.
- Create `tests/test_decision_file_lineage.py`: parser, real-Git, incremental, divergence, idempotence, ranking, outcomes, restart.
- Modify `tests/test_handler.py`: SessionStart ordering and failure isolation.
- Modify `tests/test_decision_hooks.py`: helper warning behavior and PostToolUse non-invocation.
- Modify `tests/test_db_schema.py`: fresh-schema expected tables.
- Modify `CLAUDE.md`: architecture map for the new core module and schema tables.
- Modify `ROADMAP.md`: close only the decision-file rename tracking row after measurements pass.
- Modify `CHANGELOG.md`: record the user-visible retrieval correctness fix.

## Carry-Forward Trigger Audit

All 19 distinct open ROADMAP workstreams identified in the 2026-08-17 repository audit were reconsidered against the file list above. The decision-file rename tracking row (`ROADMAP.md:418`) is the only fired feature trigger and is folded into Task 4. Measurement gates, semantic Signal C, verdict tuning, Git escape extensions, agent hook installation, disable symmetry, Plan guards, build provenance, alpha graduation, product messaging, team scope, and unrelated Exploration candidates are not changed by this implementation. The already recorded drift rows remain governed by their separate branches or telemetry work; none is silently folded into this unit.

## Scenario Coverage Map

| Scenario | Unit chain | Integration evidence |
|---|---|---|
| S1 retrieve after rename | U1 -> U2 -> U3 | real Git one-hop/two-hop exact-rank test |
| S2 outcomes through restarts | U1 -> U2 -> U3 | reopen DB, compare old/final outcome statistics and all links |
| S3 divergent history recovery | U1 -> U2 | non-ancestor watermark forces full rescan test |
| S4 fail-open SessionStart | U2 -> U3 | parser/Git failure leaves watermark and handler proceeds |

No stateful ceremony in the deliverable; no mutation/failure-state matrix required.

---

### Task 1 (U1): Add strict schema v19 lineage storage

**Files:**
- Create: `src/entirecontext/db/migrations/v019.py`
- Modify: `src/entirecontext/db/migrations/__init__.py`
- Modify: `src/entirecontext/db/schema.py`
- Create: `tests/test_migration_v019.py`
- Modify: `tests/test_db_schema.py`

- [ ] **Step 1: Write failing migration contracts**

Cover canonical creation of `decision_file_lineage` and `decision_file_lineage_state`, required indexes, v18-to-v19 migration, matching-object replay, incompatible same-named object rejection, rollback when the schema-version insert fails, and fresh/migrated SQL parity.

- [ ] **Step 2: Implement the strict migration**

Use one callable migration step that creates absent objects and normalizes/compares `sqlite_master.sql` for existing objects. Reject incompatible objects with `sqlite3.OperationalError`; never advance schema version on mismatch.

- [ ] **Step 3: Update fresh schema and migration registration**

Set `SCHEMA_VERSION = 19`, add canonical bootstrap DDL, and register version 19 in the bounded migration loader.

- [ ] **Step 4: Verify U1**

Run `uv run pytest -q tests/test_migration_v019.py tests/test_db_schema.py` and `uv run ruff check` on changed Python files.

---

### Task 2 (U2): Implement committed rename synchronization

**Files:**
- Create: `src/entirecontext/core/decision_file_lineage.py`
- Create: `tests/test_decision_file_lineage.py`

- [ ] **Step 1: Write failing parser and scan-range tests**

Cover multi-commit NUL framing, spaces/newlines in paths, malformed records, first full scan, ancestor incremental range, same-HEAD no-op, non-ancestor full rescan, Git failure, and watermark preservation.

- [ ] **Step 2: Write the failing transitive behavior test**

In a real Git fixture, link a decision with an accepted outcome to `src/old.py`, commit `old.py -> middle.py -> new.py`, synchronize, reopen the DB, and require old/intermediate/final links, exact weight `3.0` for the final path, and identical outcome counts for old/final paths.

- [ ] **Step 3: Implement the parser and synchronizer**

Resolve `HEAD`; choose full or incremental range by ancestry; parse only `R<score>` records with their 40- or 64-character commit SHA; reject malformed or SQLite-unrepresentable text. In one transaction insert edges, recursively follow persisted lineage from normalized decision paths with set semantics, `INSERT OR IGNORE` all destinations, and upsert the watermark. Return observable counts for scanned edges and added links.

- [ ] **Step 4: Prove replay and concurrency-safe semantics**

Assert same-HEAD rerun adds zero edges/links and a later decision linked to a historical old path is propagated from persisted lineage even when no new Git commit exists.

- [ ] **Step 5: Verify U2**

Run `uv run pytest -q tests/test_decision_file_lineage.py tests/test_decisions_core.py tests/test_decision_extraction.py` and `uv run ruff check` on changed Python files.

---

### Task 3 (U3): Wire fail-open SessionStart synchronization

**Files:**
- Modify: `src/entirecontext/hooks/decision_hooks.py`
- Modify: `src/entirecontext/hooks/handler.py`
- Modify: `tests/test_handler.py`
- Modify: `tests/test_decision_hooks.py`

- [ ] **Step 1: Write failing hook-order tests**

Require `_handle_session_start` to create/resume the session, synchronize rename lineage, then rank/surface decisions. Require synchronization exceptions not to suppress ranking or lesson surfacing.

- [ ] **Step 2: Add the fail-open helper and handler call**

Resolve the repository, open the local DB, invoke the core synchronizer, close the DB, and route exceptions through `_record_hook_warning`. Call the helper exactly once before `on_session_start_decisions`.

- [ ] **Step 3: Defend PostToolUse isolation**

Assert `on_post_tool_use_decisions` does not invoke the lineage synchronizer or Git-history subprocess, including an enabled edit-surfacing path.

- [ ] **Step 4: Verify U3**

Run `uv run pytest -q tests/test_handler.py tests/test_decision_hooks.py tests/test_session_lifecycle.py` and `uv run ruff check` on changed Python files.

---

### Task 4 (U4): Close documentation and roadmap traceability

**Files:**
- Modify: `CLAUDE.md`
- Modify: `ROADMAP.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update architecture documentation**

Document the new core module, schema tables, SessionStart ownership, additive historical-link invariant, and no query/PostToolUse Git work.

- [ ] **Step 2: Close the roadmap row with measured evidence**

Mark decision-file rename tracking complete only after U1-U3 pass. State committed Git lineage, transitive old/intermediate/current preservation, SessionStart synchronization, and the exact-rank/outcome test evidence.

- [ ] **Step 3: Add the changelog entry**

Record that committed renames no longer sever path-based decision ranking or outcome feedback.

- [ ] **Step 4: Run final verification**

Run module-focused tests, then `uv run ruff check .`, `uv run mypy src/`, and `uv run pytest -q`. Inspect the changed source and tests for placeholders or skipped/only tests.

## Deferred to Follow-Up Work

- A CLI/MCP lineage inspection command: not needed for the retrieval contract.
- Uncommitted rename persistence: current PDI already sees both names transiently; durable behavior requires a separate lifecycle decision.
- Copies, case-folding, symlink, Unicode-normalization, and non-UTF-8 path policy: broader path-identity semantics than the roadmap item.
- First-scan background execution or configurable timeout: add only if measured SessionStart telemetry shows a sustained regression.

## Open Unknowns

### Planning-time

None.

### Implementation-time

- Exact `git log` NUL framing is pinned by parser fixtures and a real Git repository test before implementation.
- SQLite's reported `rowcount` for recursive `INSERT OR IGNORE` may require `SELECT changes()` for deterministic result counts; the public contract is the returned count, not the internal mechanism.
