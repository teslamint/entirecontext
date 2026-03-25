"""Migration to schema v4."""

MIGRATION_STEPS = [
    """CREATE TABLE IF NOT EXISTS assessment_relationships (
        id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        relationship_type TEXT NOT NULL,
        note TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        CHECK (source_id != target_id),
        UNIQUE(source_id, target_id, relationship_type),
        FOREIGN KEY (source_id) REFERENCES assessments(id) ON DELETE CASCADE,
        FOREIGN KEY (target_id) REFERENCES assessments(id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_assessment_rel_source ON assessment_relationships(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_assessment_rel_target ON assessment_relationships(target_id)",
]
