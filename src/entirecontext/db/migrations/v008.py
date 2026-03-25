"""Migration to schema v8."""

MIGRATION_STEPS = [
    """CREATE TABLE IF NOT EXISTS operation_events (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        turn_id TEXT,
        source TEXT NOT NULL,
        operation_name TEXT NOT NULL,
        phase TEXT NOT NULL,
        status TEXT NOT NULL,
        latency_ms INTEGER NOT NULL DEFAULT 0,
        error_class TEXT,
        message TEXT,
        metadata TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL,
        FOREIGN KEY (turn_id) REFERENCES turns(id) ON DELETE SET NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_operation_events_session ON operation_events(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_operation_events_created ON operation_events(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_operation_events_status ON operation_events(status)",
]
