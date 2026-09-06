# Full sync export plan

Specification: [Complete sync export](../specs/2026-09-06-full-sync-export.md).
Decision: [ADR 0020](../adr/0020-full-sync-export.md).

## Steps

1. Add real Git and SQLite regression tests and observe failures.
2. Remove timestamp filtering from the sync flow and remove its unused boundary argument.
3. Update the current sync contract and verify affected modules, full tests, and package builds.
4. Export a database snapshot with filtering enabled and verify every supported record.

## Spec Test Disposition

| Spec test | Disposition | Plan test(s) | Rationale |
| --- | --- | --- | --- |
| `test_sync_recovers_records_written_during_push` | retained | `test_sync_recovers_records_written_during_push` | Protect complete export. |
| `test_sync_exports_metadata_only_updates` | retained | `test_sync_exports_metadata_only_updates` | Protect complete export. |
| `test_sync_exports_backdated_records` | retained | `test_sync_exports_backdated_records` | Protect complete export. |
| `test_sync_exports_same_second_checkpoint_after_existing_watermark` | retained | `test_sync_exports_same_second_checkpoint_after_existing_watermark` | Protect timestamp precision boundary. |

## Existing infrastructure

```bash plan-check id=sync-baseline expected-status=0 evidence=docs/plans/evidence/2026-09-06-full-sync-export-c363b0ad4109/sync-baseline.json
set -euo pipefail
UV_CACHE_DIR=/tmp/ec-audit-uv-cache .venv/bin/pytest tests/test_sync.py tests/test_sync_engine.py -q
```
