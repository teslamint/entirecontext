"""Tests for the schema v20 to v21 worktree-identity migration."""

from __future__ import annotations

import sqlite3

import pytest

from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import apply_migrations, get_current_version, init_schema
from entirecontext.db.schema import SCHEMA_VERSION

_WORKTREE_STATE_SQL = """CREATE TABLE decision_file_lineage_worktree_state (
    worktree_git_dir TEXT PRIMARY KEY,
    last_scanned_commit TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    CHECK (last_scanned_commit IS NULL OR length(last_scanned_commit) IN (40, 64))
)"""

_NEW_SESSION_COLUMNS = {"workspace_root", "worktree_git_dir", "git_branch"}


@pytest.fixture
def v20_db():
    conn = get_memory_db()
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT, description TEXT)")
    conn.execute("INSERT INTO schema_version (version, description) VALUES (20, 'v20')")
    conn.execute(
        """CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            repo_path TEXT NOT NULL UNIQUE,
            remote_url TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            config TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            agent_id TEXT,
            session_type TEXT NOT NULL,
            workspace_path TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            last_activity_at TEXT NOT NULL,
            session_title TEXT,
            session_summary TEXT,
            summary_updated_at TEXT,
            total_turns INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            metadata TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )"""
    )
    conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'repo', '/repo')")
    conn.execute(
        "INSERT INTO sessions (id, project_id, session_type, workspace_path, started_at, last_activity_at) "
        "VALUES ('s1', 'p1', 'claude', '/repo/sub', '2026-01-01', '2026-01-01')"
    )
    yield conn
    conn.close()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _index_sql(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)).fetchone()
    return " ".join(row[0].lower().split()) if row and row[0] else None


def _table_sql(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'decision_file_lineage_worktree_state'"
    ).fetchone()
    return row[0] if row else None


def _normalized(sql: str) -> str:
    return " ".join(sql.lower().split()).replace("create table if not exists ", "create table ", 1)


def test_v21_adds_columns_index_and_table(v20_db):
    apply_migrations(v20_db, 20, 21)

    assert _NEW_SESSION_COLUMNS <= _columns(v20_db, "sessions")
    assert "git_common_dir" in _columns(v20_db, "projects")
    assert _index_sql(v20_db, "idx_sessions_workspace") is not None
    assert _index_sql(v20_db, "idx_projects_git_common_dir") is not None
    assert _table_sql(v20_db) is not None
    assert get_current_version(v20_db) == 21


def test_v21_preserves_existing_rows_with_null_new_columns(v20_db):
    apply_migrations(v20_db, 20, 21)

    session = v20_db.execute("SELECT * FROM sessions WHERE id = 's1'").fetchone()
    assert session["workspace_path"] == "/repo/sub"
    assert session["workspace_root"] is None
    assert session["worktree_git_dir"] is None
    assert session["git_branch"] is None
    project = v20_db.execute("SELECT * FROM projects WHERE id = 'p1'").fetchone()
    assert project["repo_path"] == "/repo"
    assert project["git_common_dir"] is None


def test_v21_is_idempotent_when_columns_exist(v20_db):
    for column in _NEW_SESSION_COLUMNS:
        v20_db.execute(f"ALTER TABLE sessions ADD COLUMN {column} TEXT")
    v20_db.execute("ALTER TABLE projects ADD COLUMN git_common_dir TEXT")

    apply_migrations(v20_db, 20, 21)

    assert get_current_version(v20_db) == 21


def test_v21_accepts_matching_existing_lineage_table(v20_db):
    v20_db.execute(_WORKTREE_STATE_SQL)

    apply_migrations(v20_db, 20, 21)

    assert get_current_version(v20_db) == 21


def test_v21_rejects_mismatched_lineage_table(v20_db):
    v20_db.execute("CREATE TABLE decision_file_lineage_worktree_state (worktree_git_dir TEXT PRIMARY KEY)")

    with pytest.raises(sqlite3.OperationalError, match="incompatible definition"):
        apply_migrations(v20_db, 20, 21)

    assert get_current_version(v20_db) == 20
    assert not (_NEW_SESSION_COLUMNS & _columns(v20_db, "sessions"))


def test_v21_rolls_back_when_version_insert_fails(v20_db):
    v20_db.execute(
        """CREATE TRIGGER fail_v21_schema_version
        BEFORE INSERT ON schema_version
        WHEN NEW.version = 21
        BEGIN
            SELECT RAISE(ABORT, 'forced v21 failure');
        END"""
    )

    with pytest.raises(sqlite3.IntegrityError, match="forced v21 failure"):
        apply_migrations(v20_db, 20, 21)

    assert not (_NEW_SESSION_COLUMNS & _columns(v20_db, "sessions"))
    assert "git_common_dir" not in _columns(v20_db, "projects")
    assert _table_sql(v20_db) is None
    assert get_current_version(v20_db) == 20


def test_fresh_schema_matches_migrated_v21(v20_db):
    apply_migrations(v20_db, 20, 21)

    fresh = get_memory_db()
    try:
        init_schema(fresh)

        assert _NEW_SESSION_COLUMNS <= _columns(fresh, "sessions")
        assert "git_common_dir" in _columns(fresh, "projects")
        for index in ("idx_sessions_workspace", "idx_projects_git_common_dir"):
            fresh_sql = _index_sql(fresh, index)
            assert fresh_sql is not None
            assert fresh_sql == _index_sql(v20_db, index)
        assert _normalized(_table_sql(fresh)) == _normalized(_table_sql(v20_db))
        assert get_current_version(fresh) == SCHEMA_VERSION
    finally:
        fresh.close()


def test_partial_unique_index_allows_multiple_null_common_dirs(v20_db):
    apply_migrations(v20_db, 20, 21)

    v20_db.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p2', 'other', '/other')")
    v20_db.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p3', 'third', '/third')")
    v20_db.execute("UPDATE projects SET git_common_dir = '/repo/.git' WHERE id = 'p1'")

    nulls = v20_db.execute("SELECT COUNT(*) FROM projects WHERE git_common_dir IS NULL").fetchone()[0]
    assert nulls == 2
    with pytest.raises(sqlite3.IntegrityError):
        v20_db.execute("UPDATE projects SET git_common_dir = '/repo/.git' WHERE id = 'p2'")
