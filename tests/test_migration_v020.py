"""Tests for schema v19 to v20 decision-file lineage suppression migration."""

from __future__ import annotations

import sqlite3

import pytest

from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import apply_migrations, get_current_version, init_schema


_SUPPRESSION_TABLE_SQL = """CREATE TABLE decision_file_lineage_suppressions (
    decision_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    suppressed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (decision_id, file_path),
    FOREIGN KEY (decision_id) REFERENCES decisions(id) ON DELETE CASCADE
)"""


@pytest.fixture
def v19_db():
    conn = get_memory_db()
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT, description TEXT)")
    conn.execute("INSERT INTO schema_version (version, description) VALUES (19, 'v19')")
    yield conn
    conn.close()


def _table_sql(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'decision_file_lineage_suppressions'"
    ).fetchone()
    return row[0] if row else None


def _normalized_sql(sql: str) -> str:
    return " ".join(sql.lower().split()).replace("create table if not exists ", "create table ", 1)


def test_v20_adds_lineage_suppression_table(v19_db):
    apply_migrations(v19_db, 19, 20)

    assert _table_sql(v19_db) is not None
    assert get_current_version(v19_db) == 20


def test_v20_accepts_matching_existing_table(v19_db):
    v19_db.execute(_SUPPRESSION_TABLE_SQL)

    apply_migrations(v19_db, 19, 20)

    assert get_current_version(v19_db) == 20


def test_v20_rejects_mismatched_existing_table(v19_db):
    v19_db.execute("CREATE TABLE decision_file_lineage_suppressions (decision_id TEXT PRIMARY KEY)")

    with pytest.raises(
        sqlite3.OperationalError,
        match="decision_file_lineage_suppressions has incompatible definition",
    ):
        apply_migrations(v19_db, 19, 20)

    assert get_current_version(v19_db) == 19


def test_v20_rolls_back_table_when_version_insert_fails(v19_db):
    v19_db.execute(
        """CREATE TRIGGER fail_v20_schema_version
        BEFORE INSERT ON schema_version
        WHEN NEW.version = 20
        BEGIN
            SELECT RAISE(ABORT, 'forced v20 failure');
        END"""
    )

    with pytest.raises(sqlite3.IntegrityError, match="forced v20 failure"):
        apply_migrations(v19_db, 19, 20)

    assert _table_sql(v19_db) is None
    assert get_current_version(v19_db) == 19


def test_fresh_schema_matches_migrated_v20_table(v19_db):
    apply_migrations(v19_db, 19, 20)

    fresh = get_memory_db()
    try:
        init_schema(fresh)

        migrated_sql = _table_sql(v19_db)
        fresh_sql = _table_sql(fresh)
        assert migrated_sql is not None
        assert fresh_sql is not None
        assert _normalized_sql(fresh_sql) == _normalized_sql(migrated_sql)
        assert get_current_version(fresh) == 20
    finally:
        fresh.close()
