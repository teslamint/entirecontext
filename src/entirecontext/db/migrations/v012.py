"""Migration to schema v12 (decision_relationships table + backfill from superseded_by_id)."""


def _backfill_superseded_relationships(conn):
    """Create decision_relationships rows from existing superseded_by_id values."""
    import uuid

    rows = conn.execute("SELECT id, superseded_by_id FROM decisions WHERE superseded_by_id IS NOT NULL").fetchall()
    for row in rows:
        rel_id = str(uuid.uuid4())
        conn.execute(
            "INSERT OR IGNORE INTO decision_relationships (id, source_id, target_id, relationship_type, confidence) "
            "VALUES (?, ?, ?, 'supersedes', 1.0)",
            (rel_id, row["superseded_by_id"], row["id"]),
        )


MIGRATION_STEPS = [
    """CREATE TABLE IF NOT EXISTS decision_relationships (
        id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        relationship_type TEXT NOT NULL CHECK(relationship_type IN ('contradicts', 'supersedes', 'related_to')),
        confidence REAL NOT NULL DEFAULT 1.0,
        note TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        CHECK (source_id != target_id),
        UNIQUE(source_id, target_id, relationship_type),
        FOREIGN KEY (source_id) REFERENCES decisions(id) ON DELETE CASCADE,
        FOREIGN KEY (target_id) REFERENCES decisions(id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_decision_rel_source ON decision_relationships(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_decision_rel_target ON decision_relationships(target_id)",
    "CREATE INDEX IF NOT EXISTS idx_decision_rel_type ON decision_relationships(relationship_type)",
    _backfill_superseded_relationships,
]
