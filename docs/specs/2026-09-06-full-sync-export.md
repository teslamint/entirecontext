# Complete sync export

## Contract

Every sync enumerates all sessions and checkpoints. Each exported session includes all its current turns.
The last successful export time must not filter records. Retain it for telemetry and automatic-sync debounce.
A write after export selection may miss that run. The next successful run must include it regardless of its timestamp.
Preserve secret filtering, remote merge behavior, and success-only metadata updates.
The supported export scope remains session metadata, turn transcripts, and checkpoints. No schema or dependency changes are required.

## Measurement

Use real temporary Git remotes and SQLite connections to compare stored records with published artifacts.
Before implementation, the new regression tests must fail on the existing exporter.
After implementation, all new regressions and existing sync tests must pass.
For the requested recovery export, take a SQLite backup and compare every exported identifier and turn count against that snapshot.
Measure elapsed seconds and output bytes. A live DB may receive further records after the snapshot.

## Testing

- `test_sync_recovers_records_written_during_push`: later sync includes late sessions, turns, and same-second checkpoints.
- `test_sync_exports_metadata_only_updates`: updated session metadata is exported without new activity.
- `test_sync_exports_backdated_records`: old persisted timestamps cannot exclude unexported records.
- `test_sync_exports_same_second_checkpoint_after_existing_watermark`: second-resolution timestamps cannot exclude later inserts.
