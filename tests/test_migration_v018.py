"""Tests for schema v17 to v18 lesson-recency index migration."""

import sqlite3

import pytest

from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import apply_migrations, get_current_version, init_schema


@pytest.fixture
def v17_db():
    conn = get_memory_db()
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT, description TEXT)")
    conn.execute("INSERT INTO schema_version (version, description) VALUES (17, 'v17')")
    conn.execute(
        "CREATE TABLE assessments (id TEXT PRIMARY KEY, verdict TEXT NOT NULL, feedback TEXT, created_at TEXT)"
    )
    yield conn
    conn.close()


def _lesson_index_sql(conn) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
        ("idx_assessments_feedback_recency",),
    ).fetchone()
    return row[0] if row else None


def _normalized_sql(sql: str) -> str:
    normalized = " ".join(sql.lower().split())
    return normalized.replace("create index if not exists ", "create index ", 1)


def test_v18_adds_ordered_feedback_recency_index(v17_db):
    apply_migrations(v17_db, 17, 18)

    index_sql = _lesson_index_sql(v17_db)

    assert index_sql is not None
    assert "assessments(verdict, created_at DESC, id DESC)" in index_sql
    assert "WHERE feedback IS NOT NULL" in index_sql


def test_v18_rejects_mismatched_existing_index(v17_db):
    v17_db.execute("CREATE INDEX idx_assessments_feedback_recency ON assessments(id)")

    with pytest.raises(sqlite3.OperationalError, match="incompatible definition"):
        apply_migrations(v17_db, 17, 18)

    assert get_current_version(v17_db) == 17


def test_v18_accepts_matching_existing_index(v17_db):
    v17_db.execute(
        """CREATE INDEX IF NOT EXISTS idx_assessments_feedback_recency
        ON assessments(verdict, created_at DESC, id DESC)
        WHERE feedback IS NOT NULL"""
    )

    apply_migrations(v17_db, 17, 18)

    assert get_current_version(v17_db) == 18


def test_v18_rolls_back_created_index_when_version_insert_fails(v17_db):
    v17_db.execute(
        """CREATE TRIGGER fail_v18_schema_version
        BEFORE INSERT ON schema_version
        WHEN NEW.version = 18
        BEGIN
            SELECT RAISE(ABORT, 'forced v18 failure');
        END"""
    )

    with pytest.raises(sqlite3.IntegrityError, match="forced v18 failure"):
        apply_migrations(v17_db, 17, 18)

    assert _lesson_index_sql(v17_db) is None
    assert get_current_version(v17_db) == 17


def test_v18_index_serves_verdict_recency_order(v17_db):
    apply_migrations(v17_db, 17, 18)

    plan = v17_db.execute(
        """EXPLAIN QUERY PLAN
        SELECT * FROM assessments
        WHERE feedback IS NOT NULL AND verdict = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?""",
        ("neutral", 50),
    ).fetchall()
    details = [row[3] for row in plan]

    assert any("idx_assessments_feedback_recency" in detail for detail in details)
    assert not any("TEMP B-TREE" in detail for detail in details)


def test_fresh_schema_matches_migrated_feedback_recency_index(v17_db):
    apply_migrations(v17_db, 17, 18)
    migrated_sql = _lesson_index_sql(v17_db)

    conn = get_memory_db()
    try:
        init_schema(conn)
        fresh_sql = _lesson_index_sql(conn)

        assert migrated_sql is not None
        assert fresh_sql is not None
        assert _normalized_sql(fresh_sql) == _normalized_sql(migrated_sql)
        assert get_current_version(conn) == 18
    finally:
        conn.close()
