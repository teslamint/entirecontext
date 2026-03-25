"""Migration to schema v9 (decision memory model)."""

MIGRATION_STEPS = [
    """CREATE TABLE IF NOT EXISTS decisions (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        rationale TEXT,
        scope TEXT,
        staleness_status TEXT NOT NULL DEFAULT 'fresh',
        rejected_alternatives TEXT,
        supporting_evidence TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_decisions_staleness ON decisions(staleness_status)",
    "CREATE INDEX IF NOT EXISTS idx_decisions_updated_at ON decisions(updated_at DESC)",
    """CREATE TABLE IF NOT EXISTS decision_commits (
        decision_id TEXT NOT NULL,
        commit_sha TEXT NOT NULL,
        added_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (decision_id, commit_sha),
        FOREIGN KEY (decision_id) REFERENCES decisions(id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_decision_commits_decision_id ON decision_commits(decision_id)",
    "CREATE INDEX IF NOT EXISTS idx_decision_commits_commit_sha ON decision_commits(commit_sha)",
    """CREATE TABLE IF NOT EXISTS decision_checkpoints (
        decision_id TEXT NOT NULL,
        checkpoint_id TEXT NOT NULL,
        added_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (decision_id, checkpoint_id),
        FOREIGN KEY (decision_id) REFERENCES decisions(id) ON DELETE CASCADE,
        FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_decision_checkpoints_decision_id ON decision_checkpoints(decision_id)",
    "CREATE INDEX IF NOT EXISTS idx_decision_checkpoints_checkpoint_id ON decision_checkpoints(checkpoint_id)",
    """CREATE TABLE IF NOT EXISTS decision_files (
        decision_id TEXT NOT NULL,
        file_path TEXT NOT NULL,
        added_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (decision_id, file_path),
        FOREIGN KEY (decision_id) REFERENCES decisions(id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_decision_files_decision_id ON decision_files(decision_id)",
    "CREATE INDEX IF NOT EXISTS idx_decision_files_file_path ON decision_files(file_path)",
    """CREATE TABLE IF NOT EXISTS decision_assessments (
        decision_id TEXT NOT NULL,
        assessment_id TEXT NOT NULL,
        relation_type TEXT NOT NULL DEFAULT 'supports',
        added_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (decision_id, assessment_id, relation_type),
        FOREIGN KEY (decision_id) REFERENCES decisions(id) ON DELETE CASCADE,
        FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_decision_assessments_decision_id ON decision_assessments(decision_id)",
    "CREATE INDEX IF NOT EXISTS idx_decision_assessments_assessment_id ON decision_assessments(assessment_id)",
]
