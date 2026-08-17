"""Migration to schema v19: persist committed decision-file rename lineage."""

from __future__ import annotations

import sqlite3


_OBJECTS: tuple[tuple[str, str, str], ...] = (
    (
        "table",
        "decision_file_lineage",
        """CREATE TABLE decision_file_lineage (
    old_path TEXT NOT NULL,
    new_path TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (old_path, new_path, commit_sha),
    CHECK (old_path <> new_path),
    CHECK (length(commit_sha) IN (40, 64))
)""",
    ),
    (
        "table",
        "decision_file_lineage_state",
        """CREATE TABLE decision_file_lineage_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_scanned_commit TEXT,
    CHECK (last_scanned_commit IS NULL OR length(last_scanned_commit) IN (40, 64))
)""",
    ),
    (
        "index",
        "idx_decision_file_lineage_old_path",
        "CREATE INDEX idx_decision_file_lineage_old_path ON decision_file_lineage(old_path)",
    ),
    (
        "index",
        "idx_decision_file_lineage_new_path",
        "CREATE INDEX idx_decision_file_lineage_new_path ON decision_file_lineage(new_path)",
    ),
)


def _normalized_sql(sql: str) -> str:
    normalized = " ".join(sql.lower().split())
    normalized = normalized.replace("create table if not exists ", "create table ", 1)
    return normalized.replace("create index if not exists ", "create index ", 1)


def _create_or_validate_lineage_objects(conn: sqlite3.Connection) -> None:
    for object_type, name, sql in _OBJECTS:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?",
            (object_type, name),
        ).fetchone()
        if row is None:
            conn.execute(sql)
            continue
        if not isinstance(row[0], str) or _normalized_sql(row[0]) != _normalized_sql(sql):
            raise sqlite3.OperationalError(f"{name} has incompatible definition")


MIGRATION_STEPS = [_create_or_validate_lineage_objects]
