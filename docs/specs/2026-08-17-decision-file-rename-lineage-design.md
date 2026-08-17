---
title: Decision File Rename Lineage
status: approved
date: 2026-08-17
schema: spec/v1
---

# Decision File Rename Lineage Design

_Created 2026-08-17. Approved by the user on 2026-08-17._

## Overview

Preserve path-based decision retrieval after committed Git renames. EntireContext will store Git-proven old-to-new path edges and, at SessionStart, add every reachable destination path to each affected decision without deleting historical links automatically. An explicit file unlink remains durable across later lineage replay until an explicit relink.

Decision outcomes already attach to decision IDs; this change repairs the path-to-decision lookup used by ranking, surfacing, staleness checks, auto-apply inference, and extraction feedback.

## User Scenarios

### S1: Retrieve a decision after a committed rename

A decision linked to `src/old.py` remains an exact file match when the file is committed as `src/new.py`. The decision retains both paths, so historical and current queries work.

### S2: Preserve outcomes through multiple renames and restarts

A decision linked to `src/old.py` and carrying recorded outcomes survives `old.py -> middle.py -> new.py`. After a later SessionStart, ranking gives `src/new.py` the normal exact-file weight and extraction sees the same outcome counts it saw for `src/old.py`.

### S3: Recover after rewritten or divergent history

If the stored scan watermark is no longer an ancestor of `HEAD`, the next SessionStart rescans reachable history. Existing lineage and decision links remain idempotent; the watermark advances only after the database update succeeds.

### S4: Continue when Git lineage synchronization fails

A timeout, malformed Git output, missing repository, or database error does not block SessionStart. The hook records a warning, leaves the prior watermark unchanged, and retries on a later SessionStart.

### S5: Preserve explicit unlink intent across replay

After synchronization adds `src/new.py`, a user explicitly unlinks that destination. A same-HEAD SessionStart does not restore it. Linking `src/new.py` explicitly clears the suppression; a later unlink and replay suppresses it again.

## Scope

### In

- Add schema v19 tables for committed rename edges and the repository-local scan watermark.
- Add schema v20 storage for explicit per-decision destination suppressions.
- Parse NUL-delimited `git log --name-status -M --diff-filter=R` output without flattening old/new identity.
- Scan all commits reachable from `HEAD` on first use; scan `watermark..HEAD` thereafter when the watermark remains an ancestor.
- Fall back to a full reachable-history scan after rewritten or divergent history.
- Materialize transitive destination paths into `decision_files` in one database transaction while preserving every path not explicitly suppressed.
- Make file unlink create a suppression and explicit file link clear it in the same transaction as the existing link mutation.
- Run synchronization during SessionStart before decision ranking.
- Keep PostToolUse free of Git subprocesses.
- Close `ROADMAP.md`'s decision-file rename tracking row after the measured contract passes.

### Out

- Uncommitted working-tree rename persistence.
- Copy tracking (`C` status), heuristic aliases, directory-prefix rewrites, or path inference without Git rename evidence.
- Automated rewriting or deletion of historical `decision_files` rows; explicit user unlink remains authorized.
- New CLI or MCP commands for viewing or editing lineage.
- Case-folding, symlink resolution, Unicode normalization, or changing the existing `./` and backslash normalization contract.
- Background workers, polling, or a configurable rename detector.

## Assumptions and Preconditions

| Claim | Measurement | Observed result |
|---|---|---|
| Outcomes survive independently of file paths. | Inspect `decision_outcomes` foreign keys. | Outcomes reference `decision_id`; no outcome row stores a path. |
| Current-path lookup breaks after a rename. | Link a decision to `src/old.py`, query ranking and outcome statistics for `src/new.py`. | No exact match and zero file outcome counts before lineage propagation. |
| Exact-file ranking has a stable observable metric. | `rank_related_decisions(..., file_paths=[path])`. | `score_breakdown.file_exact == 3.0` for a linked path. |
| Extraction feedback has a stable observable metric. | `get_file_outcome_stats(..., [path], 60)`. | Returns per-outcome and total counts for linked decisions. |
| PostToolUse has a strict latency boundary. | Inspect `on_post_tool_use_decisions`. | It is documented as a three-second, subprocess-free exact-match path. |

## Architecture

### Storage

Schema v19 adds:

- `decision_file_lineage(old_path, new_path, commit_sha, recorded_at)` with a unique primary key across the Git-proven edge.
- `decision_file_lineage_state(id = 1, last_scanned_commit)` as the repository-local watermark.
- Indexes on lineage `old_path` and `new_path` for propagation and future inspection.

Schema v20 adds `decision_file_lineage_suppressions(decision_id, file_path)` with a composite primary key and a cascading decision foreign key.

`decision_files` remains the read model consumed by existing ranking, hook, extraction, and outcome code. Synchronization adds unsuppressed destination rows to that table; no existing reader or public return shape changes.

### Synchronization

1. Resolve `HEAD`.
2. Read the prior watermark.
3. If no watermark exists, scan reachable `HEAD` history. If it is an ancestor, scan `watermark..HEAD`. Otherwise rescan reachable history.
4. Parse only Git `R<score>` records and retain each record's commit SHA.
5. In one transaction, insert new lineage edges, recursively propagate unsuppressed destination paths into `decision_files`, and advance the watermark.
6. On any failure, roll back database changes and let SessionStart continue through the existing warning path.

The recursive propagation starts from normalized stored decision paths, follows all persisted edges with set semantics to terminate cycles, traverses suppressed intermediate paths, and applies exact suppressions only to the final `decision_files` insertion. Remaining destinations use `INSERT OR IGNORE`. This preserves old links, supports transitive renames beyond an unlinked intermediate path, and makes replay safe.

### Explicit link and unlink

A successful file unlink deletes the exact `decision_files` row and inserts its suppression in one transaction. An explicit file link inserts the exact row and deletes its suppression in one transaction. Suppressions affect automated destination materialization only; source links and lineage provenance remain available for historical lookup.

### Hook placement

`hooks.handler._handle_session_start` invokes a fail-open lineage helper after session creation and before `on_session_start_decisions`. PostToolUse does not import or invoke the synchronizer.

## Alternatives Considered

### Add only the latest destination to `decision_files`

Rejected. It repairs the immediate query but has no provenance, cannot recover a missed intermediate rename, and cannot distinguish observed Git evidence from a manual link.

### Resolve Git history during every query

Rejected. It duplicates lineage logic across ranking and extraction, adds subprocess latency to hot paths, and violates the PostToolUse budget.

### Replace the old path in place

Rejected. It makes current lookup work by breaking historical lookup and erases the audit trail.

### Treat copies as renames

Rejected. A copy does not retire the source identity; automatically propagating all decisions to copies would broaden decision scope without evidence.

## Testing

1. `test_fresh_schema_matches_migrated_v19_objects`,
   `test_v19_accepts_matching_existing_objects`,
   `test_v19_rejects_mismatched_existing_table`,
   `test_v19_rejects_mismatched_existing_index`, and
   `test_v19_rolls_back_objects_when_version_insert_fails` cover schema v19 parity,
   canonical replay, incompatible objects, and rollback.
2. `test_v20_adds_lineage_suppression_table`,
   `test_v20_accepts_matching_existing_table`,
   `test_v20_rejects_mismatched_existing_table`,
   `test_v20_rolls_back_table_when_version_insert_fails`, and
   `test_fresh_schema_matches_migrated_v20_table` cover strict schema v20 replay,
   incompatibility rejection, rollback, and fresh/migrated parity.
3. `test_parse_rename_log_preserves_commit_and_exact_paths` and
   `test_parse_rename_log_rejects_malformed_or_unpersistable_records` cover
   multiple commits, spaces, malformed records, path encoding, and NUL framing.
4. `test_sync_preserves_ranking_outcomes_and_all_transitive_paths` commits
   `old.py -> middle.py -> new.py`, reopens the database, and verifies historical
   links, exact ranking, and unchanged outcome statistics.
5. `test_sync_uses_incremental_range_after_initial_watermark`,
   `test_sync_same_head_replays_lineage_for_later_decision`,
   `test_sync_full_rescans_when_watermark_is_not_an_ancestor`, and
   `test_db_error_rolls_back_lineage_links_and_watermark` cover incremental,
   idempotent, divergent-watermark, and transactional retry behavior.
6. `test_unlink_suppresses_lineage_replay_until_explicit_relink`,
   `test_suppressed_intermediate_does_not_block_later_destination`,
   `test_unlink_file_rolls_back_when_suppression_insert_fails`, and
   `test_relink_file_rolls_back_when_suppression_delete_fails` cover durable
   unlink, same-HEAD replay, traversal beyond a suppressed intermediate,
   explicit relink, a second unlink/replay cycle, and atomic rollback of both
   explicit link/unlink state transitions.
7. `test_syncs_rename_lineage_before_decision_ranking`,
   `test_lineage_exception_does_not_suppress_other_session_start_surfaces`,
   `test_failure_records_warning_and_closes_database`, and
   `test_post_tool_use_never_invokes_rename_synchronizer` cover ordering,
   fail-open warnings, database cleanup, and PostToolUse isolation.

## Success Criteria

1. **Exact-match preservation:** one decision linked only to `src/old.py` receives `score_breakdown.file_exact == 3.0` for `src/new.py` after two committed renames and SessionStart synchronization.
2. **Outcome preservation:** the same fixture returns identical nonzero `get_file_outcome_stats` results for `src/old.py` and `src/new.py` after database reopen.
3. **Historical preservation:** `get_decision()['files']` contains old, intermediate, and final paths; no historical path is deleted.
4. **Idempotence:** rerunning synchronization at the same `HEAD` records zero new lineage edges and zero new decision-file links.
5. **Recovery:** a non-ancestor watermark causes a full reachable-history rescan and advances only after a successful transaction.
6. **Hook isolation:** SessionStart synchronization occurs before ranking; PostToolUse performs zero rename-synchronization or Git-history calls.
7. **Schema safety:** schema v19/v20 bootstrap and v18 migration produce equivalent canonical tables/indexes; incompatible pre-existing objects fail without advancing `schema_version`.
8. **Unlink durability:** an explicitly unlinked destination remains absent after same-HEAD synchronization, does not block propagation to a later unsuppressed descendant, explicit relink restores it and clears suppression, a later unlink is durable again, and failures roll back both sides of either link/suppression transition.

## Risks

- **Large first scan:** full reachable history may exceed the Git timeout in very large repositories. Mitigation: fail open without advancing the watermark, report a hook warning, and retry; no hot-path query performs the scan.
- **Git similarity semantics:** `-M` can miss low-similarity moves or classify ambiguous changes differently. Mitigation: persist only Git-reported rename evidence; do not invent aliases.
- **Concurrent SessionStart hooks:** two sessions may scan the same range. Mitigation: unique lineage keys, `INSERT OR IGNORE`, transactional propagation, and idempotent replay.
- **History rewrites:** a stale watermark can become unreachable. Mitigation: ancestor check and full reachable-history rescan.
- **Unsupported path bytes:** SQLite text cannot represent surrogate code points. Mitigation: fail the scan rather than advancing past unpersistable evidence.
- **Stale suppression:** an old explicit unlink can continue to block automated materialization. Mitigation: explicit relink is the authoritative, atomic way to clear the exact suppression.

## Open Decisions

None. The user approved committed Git lineage, additive materialization, first-run history scanning, SessionStart placement, and additive explicit-unlink suppression on 2026-08-17.
