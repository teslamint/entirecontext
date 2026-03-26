"""Migration to schema v10 (decision quality outcomes)."""

MIGRATION_STEPS = [
    """CREATE TABLE IF NOT EXISTS decision_outcomes (
        id TEXT PRIMARY KEY,
        decision_id TEXT NOT NULL,
        retrieval_selection_id TEXT,
        session_id TEXT,
        turn_id TEXT,
        outcome_type TEXT NOT NULL CHECK(outcome_type IN ('accepted', 'ignored', 'contradicted')),
        note TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (decision_id) REFERENCES decisions(id) ON DELETE CASCADE,
        FOREIGN KEY (retrieval_selection_id) REFERENCES retrieval_selections(id) ON DELETE SET NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL,
        FOREIGN KEY (turn_id) REFERENCES turns(id) ON DELETE SET NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_decision_outcomes_decision_id ON decision_outcomes(decision_id)",
    "CREATE INDEX IF NOT EXISTS idx_decision_outcomes_selection_id ON decision_outcomes(retrieval_selection_id)",
    "CREATE INDEX IF NOT EXISTS idx_decision_outcomes_outcome_type ON decision_outcomes(outcome_type)",
    "CREATE INDEX IF NOT EXISTS idx_decision_outcomes_created_at ON decision_outcomes(created_at DESC)",
]
