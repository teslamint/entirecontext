"""Tests for schema v18 to v19 decision-file rename lineage migration."""

from __future__ import annotations

import sqlite3

import pytest

from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import apply_migrations, get_current_version, init_schema


_LINEAGE_TABLE_SQL = """CREATE TABLE decision_file_lineage (
    old_path TEXT NOT NULL,
    new_path TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (old_path, new_path, commit_sha),
    CHECK (old_path <> new_path),
    CHECK (length(commit_sha) IN (40, 64))
)"""
_STATE_TABLE_SQL = """CREATE TABLE decision_file_lineage_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_scanned_commit TEXT,
    CHECK (last_scanned_commit IS NULL OR length(last_scanned_commit) IN (40, 64))
)"""
_INDEX_SQL = {
    "idx_decision_file_lineage_old_path": "CREATE INDEX idx_decision_file_lineage_old_path ON decision_file_lineage(old_path)",
    "idx_decision_file_lineage_new_path": "CREATE INDEX idx_decision_file_lineage_new_path ON decision_file_lineage(new_path)",
}


@pytest.fixture
def v18_db():
    conn = get_memory_db()
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT, description TEXT)")
    conn.execute("INSERT INTO schema_version (version, description) VALUES (18, 'v18')")
    yield conn
    conn.close()


def _object_sql(conn: sqlite3.Connection, object_type: str, name: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?",
        (object_type, name),
    ).fetchone()
    return row[0] if row else None


def _normalized_sql(sql: str) -> str:
    normalized = " ".join(sql.lower().split())
    normalized = normalized.replace("create table if not exists ", "create table ", 1)
    return normalized.replace("create index if not exists ", "create index ", 1)


def _create_canonical_objects(conn: sqlite3.Connection) -> None:
    conn.execute(_LINEAGE_TABLE_SQL)
    conn.execute(_STATE_TABLE_SQL)
    for sql in _INDEX_SQL.values():
        conn.execute(sql)


def test_v19_adds_lineage_tables_and_indexes(v18_db):
    apply_migrations(v18_db, 18, 19)

    assert _object_sql(v18_db, "table", "decision_file_lineage") is not None
    assert _object_sql(v18_db, "table", "decision_file_lineage_state") is not None
    assert _object_sql(v18_db, "index", "idx_decision_file_lineage_old_path") is not None
    assert _object_sql(v18_db, "index", "idx_decision_file_lineage_new_path") is not None
    assert get_current_version(v18_db) == 19


def test_v19_accepts_matching_existing_objects(v18_db):
    _create_canonical_objects(v18_db)

    apply_migrations(v18_db, 18, 19)

    assert get_current_version(v18_db) == 19


def test_v19_rejects_mismatched_existing_table(v18_db):
    v18_db.execute("CREATE TABLE decision_file_lineage (old_path TEXT PRIMARY KEY)")

    with pytest.raises(sqlite3.OperationalError, match="decision_file_lineage has incompatible definition"):
        apply_migrations(v18_db, 18, 19)

    assert get_current_version(v18_db) == 18
    assert _object_sql(v18_db, "table", "decision_file_lineage_state") is None


def test_v19_rejects_mismatched_existing_index(v18_db):
    v18_db.execute(_LINEAGE_TABLE_SQL)
    v18_db.execute("CREATE INDEX idx_decision_file_lineage_old_path ON decision_file_lineage(new_path)")

    with pytest.raises(
        sqlite3.OperationalError, match="idx_decision_file_lineage_old_path has incompatible definition"
    ):
        apply_migrations(v18_db, 18, 19)

    assert get_current_version(v18_db) == 18
    assert _object_sql(v18_db, "table", "decision_file_lineage_state") is None


def test_v19_rolls_back_objects_when_version_insert_fails(v18_db):
    v18_db.execute(
        """CREATE TRIGGER fail_v19_schema_version
        BEFORE INSERT ON schema_version
        WHEN NEW.version = 19
        BEGIN
            SELECT RAISE(ABORT, 'forced v19 failure');
        END"""
    )

    with pytest.raises(sqlite3.IntegrityError, match="forced v19 failure"):
        apply_migrations(v18_db, 18, 19)

    assert _object_sql(v18_db, "table", "decision_file_lineage") is None
    assert _object_sql(v18_db, "table", "decision_file_lineage_state") is None
    assert get_current_version(v18_db) == 18


def test_fresh_schema_matches_migrated_v19_objects(v18_db):
    apply_migrations(v18_db, 18, 19)

    fresh = get_memory_db()
    try:
        init_schema(fresh)

        for object_type, name in (
            ("table", "decision_file_lineage"),
            ("table", "decision_file_lineage_state"),
            ("index", "idx_decision_file_lineage_old_path"),
            ("index", "idx_decision_file_lineage_new_path"),
        ):
            migrated_sql = _object_sql(v18_db, object_type, name)
            fresh_sql = _object_sql(fresh, object_type, name)
            assert migrated_sql is not None
            assert fresh_sql is not None
            assert _normalized_sql(fresh_sql) == _normalized_sql(migrated_sql)

        assert get_current_version(fresh) == 19
    finally:
        fresh.close()
