"""Schema migration management. Forward-only."""

from __future__ import annotations

import sqlite3

from .schema import SCHEMA_VERSION, TABLES, FTS_TABLES, FTS_TRIGGERS


def get_current_version(conn: sqlite3.Connection) -> int:
    """Get current schema version. Returns 0 if no schema exists."""
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return row[0] if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        return 0


def init_schema(conn: sqlite3.Connection) -> None:
    """Initialize the full schema from scratch."""
    for name, sql in TABLES.items():
        for statement in sql.strip().split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(statement)

    for name, sql in FTS_TABLES.items():
        conn.execute(sql.strip().rstrip(";"))

    for name, sql in FTS_TRIGGERS.items():
        conn.execute(sql.strip())

    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (SCHEMA_VERSION, "Initial schema"),
    )
    conn.commit()


def check_and_migrate(conn: sqlite3.Connection) -> None:
    """Check schema version and apply pending migrations."""
    current = get_current_version(conn)

    if current == 0:
        init_schema(conn)
        return

    if current < SCHEMA_VERSION:
        _apply_migrations(conn, current)


def _apply_migrations(conn: sqlite3.Connection, from_version: int) -> None:
    """Apply sequential migrations from from_version to SCHEMA_VERSION."""
    migrations = _get_migrations()
    for version in range(from_version + 1, SCHEMA_VERSION + 1):
        if version in migrations:
            for sql in migrations[version]:
                conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                (version, f"Migration to v{version}"),
            )
    conn.commit()


def _get_migrations() -> dict[int, list[str]]:
    """Return migration SQL for each version transition.

    Add new entries as schema evolves:
        2: ["ALTER TABLE ...", "CREATE INDEX ..."],
    """
    return {
        2: [
            "ALTER TABLE sync_metadata ADD COLUMN last_sync_error TEXT;",
            "ALTER TABLE sync_metadata ADD COLUMN last_sync_duration_ms INTEGER;",
            "ALTER TABLE sync_metadata ADD COLUMN sync_pid INTEGER;",
        ],
        3: [
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
        ],
        4: [
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
        ],
    }
