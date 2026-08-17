"""Migration to schema v20: persist decision-file lineage suppressions."""

from __future__ import annotations

import sqlite3


_SUPPRESSION_TABLE_SQL = """CREATE TABLE decision_file_lineage_suppressions (
    decision_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    suppressed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (decision_id, file_path),
    FOREIGN KEY (decision_id) REFERENCES decisions(id) ON DELETE CASCADE
)"""


def _normalized_sql(sql: str) -> str:
    normalized = " ".join(sql.lower().split())
    return normalized.replace("create table if not exists ", "create table ", 1)


def _create_or_validate_suppression_table(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'decision_file_lineage_suppressions'"
    ).fetchone()
    if row is None:
        conn.execute(_SUPPRESSION_TABLE_SQL)
        return
    if not isinstance(row[0], str) or _normalized_sql(row[0]) != _normalized_sql(_SUPPRESSION_TABLE_SQL):
        raise sqlite3.OperationalError("decision_file_lineage_suppressions has incompatible definition")


MIGRATION_STEPS = [_create_or_validate_suppression_table]
