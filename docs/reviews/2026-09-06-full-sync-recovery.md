# Full sync export recovery

## Change

The sync coordinator no longer reads an export cutoff. The export flow enumerates all sessions and checkpoints on every run.
Each session export contains all current turns. The last successful sync timestamp still controls automatic-sync cooldown and telemetry.
Secret filters and push-retry behavior remain unchanged.

Source files: `src/entirecontext/sync/coordinator.py`, `src/entirecontext/sync/export_flow.py`.
Tests: `tests/test_sync_integration.py`, with the internal-call update in `tests/test_sync.py`.
Contract: [ADR 0020](../adr/0020-full-sync-export.md), [specification](../specs/2026-09-06-full-sync-export.md), and [validated plan](../plans/2026-09-06-full-sync-export.md).

## Regression evidence

Four new real-Git regressions failed before the correction. All six integration tests passed afterward.
The regressions cover writes during push, same-second checkpoints, metadata-only changes, and delayed records with older timestamps.
The affected sync and automatic-sync suites passed 98 tests.

## Recovery artifact

Snapshot completed at 2026-09-06T13:48:46.485837+00:00.
Output: `.entirecontext/exports/full-20260906T134846Z/`.

- Sessions: 2,209.
- Turns: 3,653.
- Checkpoints: 2,000.
- Export bytes: 19,917,167, excluding the verification report.
- Snapshot, export, and verification duration: 1.818 seconds.
- Secret filters: enabled.

Every exported session, turn, and checkpoint identifier matches the SQLite snapshot.
Each session transcript has the expected turn count and session references. The manifest covers all exported sessions and checkpoints.
See the output directory's `verification.json` for machine-readable evidence.
The temporary database snapshot was removed after validation.

## Validation status

Lint, format, type checks, and both distribution builds passed.
The wheel and source archive each match all 126 runtime Python source files.
The build-provenance suite passed 12 tests using cached dependencies in offline mode.
Final full suite: 2,398 passed, one optional performance-recording test skipped, and one existing fixture warning, in 117.12 seconds.
Command: `UV_CACHE_DIR=/tmp/ec-audit-uv-cache UV_OFFLINE=true .venv/bin/pytest -q`.

## Boundaries

This recovery artifact is local. No remote push or installed CLI replacement occurred.
The recovery run preceded the implementation commits. Earlier unrelated working-tree changes are preserved.
Future syncs must run this updated checkout or an installation rebuilt from it.
Writes after a particular export selection are recovered by the next successful full sync.
Historical Git commits are not rewritten.

Decisions dc9460a0 and ce7c276c received accepted outcomes. Assessment 55e70f0c received agreement with the regression and recovery evidence.
