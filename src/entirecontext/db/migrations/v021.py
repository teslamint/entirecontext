"""Migration to schema v21: logical project identity shared across Git worktrees."""

from __future__ import annotations

import sqlite3


_WORKTREE_STATE_TABLE_SQL = """CREATE TABLE decision_file_lineage_worktree_state (
    worktree_git_dir TEXT PRIMARY KEY,
    last_scanned_commit TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    CHECK (last_scanned_commit IS NULL OR length(last_scanned_commit) IN (40, 64))
)"""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_session_workspace_columns(conn: sqlite3.Connection) -> None:
    existing = _columns(conn, "sessions")
    if not existing:
        return
    for column in ("workspace_root", "worktree_git_dir", "git_branch"):
        if column not in existing:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {column} TEXT")


def _add_session_workspace_index(conn: sqlite3.Connection) -> None:
    if not {"project_id", "workspace_root"} <= _columns(conn, "sessions"):
        return
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(project_id, workspace_root)")


def _add_project_git_common_dir(conn: sqlite3.Connection) -> None:
    existing = _columns(conn, "projects")
    if not existing:
        return
    if "git_common_dir" not in existing:
        conn.execute("ALTER TABLE projects ADD COLUMN git_common_dir TEXT")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_git_common_dir "
        "ON projects(git_common_dir) WHERE git_common_dir IS NOT NULL"
    )


def _normalized_sql(sql: str) -> str:
    normalized = " ".join(sql.lower().split())
    return normalized.replace("create table if not exists ", "create table ", 1)


def _create_lineage_worktree_state(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'decision_file_lineage_worktree_state'"
    ).fetchone()
    if row is None:
        conn.execute(_WORKTREE_STATE_TABLE_SQL)
        return
    if not isinstance(row[0], str) or _normalized_sql(row[0]) != _normalized_sql(_WORKTREE_STATE_TABLE_SQL):
        raise sqlite3.OperationalError("decision_file_lineage_worktree_state has incompatible definition")


MIGRATION_STEPS = [
    _add_session_workspace_columns,
    _add_session_workspace_index,
    _add_project_git_common_dir,
    _create_lineage_worktree_state,
]
