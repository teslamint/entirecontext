"""Migration to schema v2."""

MIGRATION_STEPS = [
    "ALTER TABLE sync_metadata ADD COLUMN last_sync_error TEXT;",
    "ALTER TABLE sync_metadata ADD COLUMN last_sync_duration_ms INTEGER;",
    "ALTER TABLE sync_metadata ADD COLUMN sync_pid INTEGER;",
]
