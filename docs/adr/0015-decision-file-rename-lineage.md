# 0015. Persist Committed Rename Lineage and Materialize Destination Links

**Status:** accepted
**Date:** 2026-08-17
**EC Decisions:** `235ba317-fd3b-4682-b8c9-52fccf0ba78c`, `841ee79c-f7d3-4c10-b39e-2e72cb8ce10d`

## Context

`decision_files` associates a decision with path text, while ranking, SessionStart and PostToolUse surfacing, staleness checks, auto-apply inference, and extraction outcome feedback discover decisions from current paths. A committed rename leaves the outcomes attached to the decision but removes the current path-to-decision lookup unless a user manually adds the destination.

Git already detects renames, but EntireContext's rename-aware uncommitted-diff parser flattens old and new names into an unordered path list and does not retain commit provenance. Resolving history in each reader would add subprocess work to hot paths, especially the three-second PostToolUse path.

## Decision

Add repository-local schema v19 storage for Git-proven committed rename edges and a scan watermark. At SessionStart, before decision ranking, scan reachable Git history incrementally with NUL-delimited `--name-status -M --diff-filter=R` output. Persist each `(old_path, new_path, commit_sha)` edge, recursively materialize all reachable destination paths into `decision_files`, preserve historical links, and advance the watermark in the same transaction.

Schema v20 adds per-decision path suppressions. A successful explicit file unlink deletes the requested `decision_files` row and records its suppression atomically. Propagation still traverses suppressed intermediate paths but excludes each exact suppressed destination from final materialization; an explicit link clears the matching suppression atomically. Same-HEAD replay remains enabled so decisions linked after an earlier history scan still receive known destinations.

The first synchronization scans history reachable from `HEAD`. Later synchronizations scan `watermark..HEAD` when the watermark remains an ancestor; rewritten or divergent history triggers an idempotent full rescan. Synchronization failures use the existing fail-open hook warning path and do not advance the watermark.

PostToolUse and query-time readers remain unchanged and perform no Git-history subprocesses. Copies, uncommitted renames, heuristic aliases, and new public lineage-management commands are outside this decision.

## Options Considered

### Persist lineage and materialize the existing read model

- Keeps existing CLI, MCP, ranking, hook, and extraction contracts unchanged.
- Preserves provenance and supports replay, transitive moves, and history rewrites.
- Adds one SessionStart Git scan and two schema tables.

### Add destination rows without lineage

- Smaller schema change.
- Rejected because missed or transitive renames cannot be audited or replayed, and manual links are indistinguishable from observed rename evidence.

### Resolve rename history in every reader

- Avoids materialized state.
- Rejected because it duplicates behavior, raises latency, and violates the PostToolUse boundary.

### Replace old links in place

- Keeps only current paths.
- Rejected because historical lookup and auditability would be lost.

### Skip same-HEAD replay after the first scan

- Avoids re-adding an explicitly removed destination.
- Rejected because decisions linked after the scan would never receive already-known rename destinations.

### Delete source and derived links during unlink

- Needs no suppression state.
- Rejected because a destination unlink would erase unrelated historical lookup and outcome evidence.

## Consequences

- Decisions and their outcome history remain discoverable through old, intermediate, and current committed paths.
- Existing public string-list contracts and query code continue to use `decision_files` without a compatibility layer.
- The local database retains an auditable record of Git-reported rename edges and the commit that supplied each edge.
- Explicit unlink remains durable across SessionStart replay, explicit relink restores normal propagation, and transactional failures preserve the prior link/suppression pair.
- Schema v20 adds one internal suppression table without changing CLI, MCP, or decision return shapes.
- The first SessionStart after migration can perform a full-history metadata scan; failure delays lineage repair but does not block the session or corrupt the watermark.
- Git's `-M` similarity decision is authoritative. EntireContext does not infer moves that Git does not report.
- Old path links intentionally accumulate. A future pruning policy would require a separate decision because it changes historical lookup semantics.

## References

- Spec: [`docs/specs/2026-08-17-decision-file-rename-lineage-design.md`](../specs/2026-08-17-decision-file-rename-lineage-design.md)
- Plan: [`docs/superpowers/plans/2026-08-17-007-decision-file-rename-lineage-plan.md`](../superpowers/plans/2026-08-17-007-decision-file-rename-lineage-plan.md)
- Roadmap: [`ROADMAP.md`](../../ROADMAP.md)
- Prior deferral: EC decision `dde7d5a6-dc51-4de8-854b-bd7ee5d6989c`
