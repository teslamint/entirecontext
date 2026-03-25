"""Migration to schema v3."""

MIGRATION_STEPS = [
    """CREATE TABLE IF NOT EXISTS assessments (
        id TEXT PRIMARY KEY,
        checkpoint_id TEXT,
        verdict TEXT NOT NULL,
        impact_summary TEXT,
        roadmap_alignment TEXT,
        tidy_suggestion TEXT,
        diff_summary TEXT,
        feedback TEXT,
        feedback_reason TEXT,
        model_name TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(id) ON DELETE SET NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_assessments_verdict ON assessments(verdict)",
    "CREATE INDEX IF NOT EXISTS idx_assessments_created ON assessments(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_assessments_checkpoint ON assessments(checkpoint_id)",
]
