"""Global database schema for cross-repo index."""

GLOBAL_TABLES = {
    "repo_index": """
CREATE TABLE IF NOT EXISTS repo_index (
    repo_path TEXT PRIMARY KEY,
    repo_name TEXT,
    db_path TEXT NOT NULL,
    last_indexed_at TEXT,
    session_count INTEGER DEFAULT 0,
    turn_count INTEGER DEFAULT 0
);
""",
}


def init_global_schema(conn) -> None:
    """Initialize the global database schema."""
    for sql in GLOBAL_TABLES.values():
        conn.execute(sql)
    conn.commit()
