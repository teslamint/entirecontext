# Decision File Rename Lineage Implementation Plan

> **For agentic workers:** implement each task test-first and verify the whole changed module before commit.

**Goal:** Preserve exact path-based decision retrieval and outcome feedback through committed, transitive Git renames without adding Git work to query or PostToolUse paths, while keeping explicit unlink intent durable across replay.

**Architecture:** Schema v19 stores Git-proven rename edges plus one repository-local scan watermark. Schema v20 stores exact per-decision destination suppressions. The core synchronizer scans committed rename records at SessionStart, persists lineage, recursively materializes unsuppressed destination paths into the existing `decision_files` read model, and advances the watermark atomically. Existing explicit link/unlink operations clear/create suppressions in their existing transactions. Readers and public interfaces remain unchanged.

**Tech Stack:** Python 3.10+, SQLite recursive CTEs, Git plumbing, pytest real-repository fixtures.

**Spec:** `docs/specs/2026-08-17-decision-file-rename-lineage-design.md`

**Decisions:** EC decisions `235ba317-fd3b-4682-b8c9-52fccf0ba78c` and `841ee79c-f7d3-4c10-b39e-2e72cb8ce10d`; companion ADR `docs/adr/0015-decision-file-rename-lineage.md`

## Global Constraints

- Treat Git `R<score>` records as the only rename authority; do not propagate copies.
- Preserve every historical `decision_files` row unless the user explicitly unlinks that exact decision/path pair.
- Advance the watermark only in the same successful transaction as lineage insertion and destination propagation.
- Keep same-HEAD replay so decisions linked after an earlier scan receive persisted lineage.
- Make successful explicit link/unlink and matching suppression removal/insertion atomic.
- Keep every CLI, MCP, and `get_decision()['files']` return shape unchanged.
- Keep PostToolUse subprocess-free and within its existing three-second budget.
- Fail SessionStart open through the existing hook warning mechanism.
- Do not change path normalization beyond the current leading dot-slash prefix and backslash behavior.

## Assumption Recheck

The approved Spec's live assumptions were rechecked on 2026-08-17:

- **match:** `decision_outcomes` references `decision_id`, not paths.
- **match:** the pre-feature schema had no lineage or alias relation.
- **match:** exact ranking exposes `score_breakdown.file_exact == 3.0`.
- **match:** extraction feedback exposes deterministic per-path outcome counts.
- **match:** PostToolUse documents a three-second exact-match path and performs no Git subprocess today.
- **review correction:** same-HEAD replay is necessary for decisions linked after the scan but restored explicitly unlinked destinations. Existing unlink deleted only `decision_files`; additive suppressions are required to preserve both late-link propagation and user intent.

No contradiction or unavailable evidence remains after the suppression correction.

## File Structure

- Create `src/entirecontext/db/migrations/v019.py`: strict canonical lineage-table/index migration.
- Create `src/entirecontext/db/migrations/v020.py`: strict canonical suppression-table migration.
- Modify `src/entirecontext/db/migrations/__init__.py`: register schemas v19 and v20.
- Modify `src/entirecontext/db/schema.py`: schema version and fresh-schema objects.
- Create `src/entirecontext/core/decision_file_lineage.py`: Git log parser, scan-range selection, transactional unsuppressed propagation.
- Modify `src/entirecontext/core/decisions.py`: atomically create/clear suppressions during explicit file unlink/link.
- Modify `src/entirecontext/hooks/decision_hooks.py`: fail-open repository synchronization helper.
- Modify `src/entirecontext/hooks/handler.py`: invoke synchronization before SessionStart decision ranking.
- Create `tests/test_migration_v019.py`: migration strictness, rollback, and bootstrap parity.
- Create `tests/test_migration_v020.py`: suppression migration strictness, rollback, and bootstrap parity.
- Create `tests/test_decision_file_lineage.py`: parser, real-Git, incremental, divergence, idempotence, suppression, ranking, outcomes, restart.
- Modify `tests/test_decisions_core.py`: atomic explicit link/unlink suppression rollback.
- Modify `tests/test_handler.py`: SessionStart ordering and failure isolation.
- Modify `tests/test_decision_hooks.py`: helper warning behavior and PostToolUse non-invocation.
- Modify `tests/test_db_schema.py`: fresh-schema expected tables.
- Modify `CLAUDE.md`, `README.md`, and `docs/spec.md`: schema v20 architecture references.
- Modify `ROADMAP.md`: close only the decision-file rename tracking row after measurements pass.
- Modify `CHANGELOG.md`: record the user-visible retrieval and unlink correctness fix.
- Modify `docs/specs/2026-08-17-decision-file-rename-lineage-design.md` and `docs/adr/0015-decision-file-rename-lineage.md`: incorporate the approved suppression contract.

## Carry-Forward Trigger Audit

All 19 distinct open ROADMAP workstreams identified in the 2026-08-17 repository audit were reconsidered against the file list above. The decision-file rename tracking row (`ROADMAP.md:418`) is the only fired feature trigger and is folded into Task 4. Measurement gates, semantic Signal C, verdict tuning, Git escape extensions, agent hook installation, disable symmetry, Plan guards, build provenance, alpha graduation, product messaging, team scope, and unrelated Exploration candidates are not changed by this implementation. The already recorded drift rows remain governed by their separate branches or telemetry work; none is silently folded into this unit.

## Scenario Coverage Map

| Scenario | Unit chain | Integration evidence |
|---|---|---|
| S1 retrieve after rename | U1 -> U2 -> U3 | real Git one-hop/two-hop exact-rank test |
| S2 outcomes through restarts | U1 -> U2 -> U3 | reopen DB, compare old/final outcome statistics and all links |
| S3 divergent history recovery | U1 -> U2 | non-ancestor watermark forces full rescan test |
| S4 fail-open SessionStart | U2 -> U3 | parser/Git failure leaves watermark and handler proceeds |
| S5 explicit unlink survives replay | U1 -> U2 | v20 migration contracts; unlink/replay/relink and suppressed-intermediate traversal tests; explicit link/unlink rollback tests |

## Mutation/Failure-State Matrix

| Trigger | Transactional mutation | Observable state | Recovery |
|---|---|---|---|
| Lineage reaches an unsuppressed destination | Insert destination into `decision_files` | Current-path lookup and outcome evidence work | Idempotent replay |
| Explicit unlink succeeds | Delete exact link and insert exact suppression | Destination is absent and remains absent on replay | Explicit relink |
| Later rename continues from a suppressed intermediate path | Traverse the intermediate but filter it from final insertion; insert unsuppressed descendants | Intermediate remains absent; current descendant becomes discoverable | Idempotent replay |
| Explicit relink succeeds | Insert exact link and delete exact suppression | Destination and normal future propagation are restored | Normal explicit unlink |
| Link/unlink transaction fails | Roll back both link and suppression mutation | Prior link/suppression state remains coherent | Retry the user operation |
| SessionStart synchronization fails | Roll back lineage, destination, and watermark writes | Prior links/suppressions/watermark remain coherent; hook warns and continues | Later SessionStart retry |

## Spec Test Disposition

| Spec test | Disposition | Plan test(s) | Rationale |
|---|---|---|---|
| `test_fresh_schema_matches_migrated_v19_objects` | retained | `test_fresh_schema_matches_migrated_v19_objects` | — |
| `test_v19_accepts_matching_existing_objects` | retained | `test_v19_accepts_matching_existing_objects` | — |
| `test_v19_rejects_mismatched_existing_table` | retained | `test_v19_rejects_mismatched_existing_table` | — |
| `test_v19_rejects_mismatched_existing_index` | retained | `test_v19_rejects_mismatched_existing_index` | — |
| `test_v19_rolls_back_objects_when_version_insert_fails` | retained | `test_v19_rolls_back_objects_when_version_insert_fails` | — |
| `test_v20_adds_lineage_suppression_table` | retained | `test_v20_adds_lineage_suppression_table` | — |
| `test_v20_accepts_matching_existing_table` | retained | `test_v20_accepts_matching_existing_table` | — |
| `test_v20_rejects_mismatched_existing_table` | retained | `test_v20_rejects_mismatched_existing_table` | — |
| `test_v20_rolls_back_table_when_version_insert_fails` | retained | `test_v20_rolls_back_table_when_version_insert_fails` | — |
| `test_fresh_schema_matches_migrated_v20_table` | retained | `test_fresh_schema_matches_migrated_v20_table` | — |
| `test_parse_rename_log_preserves_commit_and_exact_paths` | retained | `test_parse_rename_log_preserves_commit_and_exact_paths` | — |
| `test_parse_rename_log_rejects_malformed_or_unpersistable_records` | retained | `test_parse_rename_log_rejects_malformed_or_unpersistable_records` | — |
| `test_sync_preserves_ranking_outcomes_and_all_transitive_paths` | retained | `test_sync_preserves_ranking_outcomes_and_all_transitive_paths` | — |
| `test_sync_uses_incremental_range_after_initial_watermark` | retained | `test_sync_uses_incremental_range_after_initial_watermark` | — |
| `test_sync_same_head_replays_lineage_for_later_decision` | retained | `test_sync_same_head_replays_lineage_for_later_decision` | — |
| `test_sync_full_rescans_when_watermark_is_not_an_ancestor` | retained | `test_sync_full_rescans_when_watermark_is_not_an_ancestor` | — |
| `test_db_error_rolls_back_lineage_links_and_watermark` | retained | `test_db_error_rolls_back_lineage_links_and_watermark` | — |
| `test_unlink_file_rolls_back_when_suppression_insert_fails` | retained | `test_unlink_file_rolls_back_when_suppression_insert_fails` | — |
| `test_relink_file_rolls_back_when_suppression_delete_fails` | retained | `test_relink_file_rolls_back_when_suppression_delete_fails` | — |
| `test_unlink_suppresses_lineage_replay_until_explicit_relink` | retained | `test_unlink_suppresses_lineage_replay_until_explicit_relink` | — |
| `test_suppressed_intermediate_does_not_block_later_destination` | retained | `test_suppressed_intermediate_does_not_block_later_destination` | — |
| `test_syncs_rename_lineage_before_decision_ranking` | retained | `test_syncs_rename_lineage_before_decision_ranking` | — |
| `test_lineage_exception_does_not_suppress_other_session_start_surfaces` | retained | `test_lineage_exception_does_not_suppress_other_session_start_surfaces` | — |
| `test_failure_records_warning_and_closes_database` | retained | `test_failure_records_warning_and_closes_database` | — |
| `test_post_tool_use_never_invokes_rename_synchronizer` | retained | `test_post_tool_use_never_invokes_rename_synchronizer` | — |

---

### Task 1 (U1): Add strict schema v19 lineage and v20 suppression storage

**Files:**
- Create: `src/entirecontext/db/migrations/v019.py`
- Create: `src/entirecontext/db/migrations/v020.py`
- Modify: `src/entirecontext/db/migrations/__init__.py`
- Modify: `src/entirecontext/db/schema.py`
- Create: `tests/test_migration_v019.py`
- Create: `tests/test_migration_v020.py`
- Modify: `tests/test_db_schema.py`

- [x] **Step 1: Write failing migration contracts**

Cover canonical creation of `decision_file_lineage`, `decision_file_lineage_state`, and `decision_file_lineage_suppressions`; required indexes; v18-to-v19-to-v20 migration; matching-object replay; incompatible same-named object rejection; rollback when the schema-version insert fails; and fresh/migrated SQL parity.

- [x] **Step 2: Implement the strict migration**

Use one callable migration step per version that creates absent objects and normalizes/compares `sqlite_master.sql` for existing objects. Reject incompatible objects with `sqlite3.OperationalError`; never advance schema version on mismatch.

- [x] **Step 3: Update fresh schema and migration registration**

Set `SCHEMA_VERSION = 20`, add canonical bootstrap DDL, and register versions 19 and 20 in the bounded migration loader.

- [x] **Step 4: Verify U1**

```bash implementation-only reason=schema-verification
uv run pytest -q tests/test_migration_v019.py tests/test_migration_v020.py tests/test_db_schema.py
uv run ruff check src/entirecontext/db/migrations/v019.py src/entirecontext/db/migrations/v020.py src/entirecontext/db/migrations/__init__.py src/entirecontext/db/schema.py tests/test_migration_v019.py tests/test_migration_v020.py tests/test_db_schema.py
```

---

### Task 2 (U2): Implement committed rename synchronization

**Files:**
- Create: `src/entirecontext/core/decision_file_lineage.py`
- Create: `tests/test_decision_file_lineage.py`
- Modify: `src/entirecontext/core/decisions.py`
- Modify: `tests/test_decisions_core.py`

- [x] **Step 1: Write failing parser and scan-range tests**

Cover multi-commit NUL framing, spaces/newlines in paths, malformed records, first full scan, ancestor incremental range, a same-HEAD zero-range scan with persisted lineage replay, non-ancestor full rescan, Git failure, and watermark preservation.

- [x] **Step 2: Write the failing transitive behavior test**

In a real Git fixture, link a decision with an accepted outcome to `src/old.py`, commit `old.py -> middle.py -> new.py`, synchronize, reopen the DB, and require old/intermediate/final links, exact weight `3.0` for the final path, and identical outcome counts for old/final paths.

- [x] **Step 3: Implement the parser and synchronizer**

Resolve `HEAD`; choose full or incremental range by ancestry; parse only `R<score>` records with their 40- or 64-character commit SHA; reject malformed or SQLite-unrepresentable text. In one transaction insert edges, recursively follow all persisted lineage from normalized decision paths with set semantics, filter exact suppressions only from the final `decision_files` insertion, `INSERT OR IGNORE` remaining destinations, and upsert the watermark. Return observable counts for scanned edges and added links.

- [x] **Step 4: Prove replay, unlink, and concurrency-safe semantics**

Assert same-HEAD rerun adds zero edges/links when state is already materialized, a later decision linked to a historical old path is propagated from persisted lineage, explicit unlink creates a suppression that prevents exact replay without blocking later descendants, explicit relink clears it, and a later unlink is durable again. Force suppression insert/delete failures and require both sides of each explicit link mutation to roll back.

- [x] **Step 5: Verify U2**

```bash implementation-only reason=lineage-verification
uv run pytest -q tests/test_decision_file_lineage.py tests/test_decisions_core.py tests/test_decisions_cli.py tests/test_decision_extraction.py
uv run ruff check src/entirecontext/core/decision_file_lineage.py src/entirecontext/core/decisions.py tests/test_decision_file_lineage.py tests/test_decisions_core.py
```

---

### Task 3 (U3): Wire fail-open SessionStart synchronization

**Files:**
- Modify: `src/entirecontext/hooks/decision_hooks.py`
- Modify: `src/entirecontext/hooks/handler.py`
- Modify: `tests/test_handler.py`
- Modify: `tests/test_decision_hooks.py`

- [x] **Step 1: Write failing hook-order tests**

Require `_handle_session_start` to create/resume the session, synchronize rename lineage, then rank/surface decisions. Require synchronization exceptions not to suppress ranking or lesson surfacing.

- [x] **Step 2: Add the fail-open helper and handler call**

Resolve the repository, open the local DB, invoke the core synchronizer, close the DB, and route exceptions through `_record_hook_warning`. Call the helper exactly once before `on_session_start_decisions`.

- [x] **Step 3: Defend PostToolUse isolation**

Assert `on_post_tool_use_decisions` does not invoke the lineage synchronizer or Git-history subprocess, including an enabled edit-surfacing path.

- [x] **Step 4: Verify U3**

```bash implementation-only reason=hook-verification
uv run pytest -q tests/test_handler.py tests/test_decision_hooks.py tests/test_session_lifecycle.py
uv run ruff check src/entirecontext/hooks/decision_hooks.py src/entirecontext/hooks/handler.py tests/test_handler.py tests/test_decision_hooks.py
```

---

### Task 4 (U4): Close documentation and roadmap traceability

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `docs/spec.md`
- Modify: `ROADMAP.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/specs/2026-08-17-decision-file-rename-lineage-design.md`
- Modify: `docs/adr/0015-decision-file-rename-lineage.md`

- [x] **Step 1: Update architecture documentation**

Document the new core module, schemas v19/v20, SessionStart ownership, additive historical-link invariant, explicit-unlink suppression, and no query/PostToolUse Git work.

- [x] **Step 2: Close the roadmap row with measured evidence**

Mark decision-file rename tracking complete only after U1-U3 pass. State committed Git lineage, transitive old/intermediate/current preservation, SessionStart synchronization, explicit-unlink durability, and the exact-rank/outcome test evidence.

- [x] **Step 3: Add the changelog entry**

Record that committed renames no longer sever path-based decision ranking or outcome feedback and that explicit unlink survives automated replay.

- [x] **Step 4: Run final verification**

```bash plan-check id=rename-lineage expected-status=0 evidence=docs/plans/evidence/2026-08-17-007-decision-file-rename-lineage-plan-37bd84364b7c/rename-lineage.json
set -euo pipefail
uv run ruff check .
uv run mypy src
uv run pytest -q
```

## Deferred to Follow-Up Work

- A CLI/MCP lineage inspection command: not needed for the retrieval contract.
- Uncommitted rename persistence: current PDI already sees both names transiently; durable behavior requires a separate lifecycle decision.
- Copies, case-folding, symlink, Unicode-normalization, and non-UTF-8 path policy: broader path-identity semantics than the roadmap item.
- First-scan background execution or configurable timeout: add only if measured SessionStart telemetry shows a sustained regression.

## Open Unknowns

### Planning-time

None.

### Implementation-time

- Git log's exact NUL framing is pinned by parser fixtures and a real Git repository test before implementation.
- SQLite's reported `rowcount` for recursive `INSERT OR IGNORE` may require `SELECT changes()` for deterministic result counts; the public contract is the returned count, not the internal mechanism.
