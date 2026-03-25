"""Migration to schema v5."""

from __future__ import annotations


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


MIGRATION_STEPS = [
    lambda c: (None if _column_exists(c, "turns", "consolidated_at") else c.execute("ALTER TABLE turns ADD COLUMN consolidated_at TEXT")),
    "CREATE INDEX IF NOT EXISTS idx_turns_consolidated ON turns(consolidated_at);",
]
