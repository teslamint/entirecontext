"""Tests for schema v17 to v18 lesson-recency index migration."""

import pytest

from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import apply_migrations, init_schema


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


def test_v18_adds_ordered_feedback_recency_index(v17_db):
    apply_migrations(v17_db, 17, 18)

    index_sql = _lesson_index_sql(v17_db)

    assert index_sql is not None
    assert "assessments(verdict, created_at DESC, id DESC)" in index_sql
    assert "WHERE feedback IS NOT NULL" in index_sql


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


def test_fresh_schema_includes_ordered_feedback_recency_index():
    conn = get_memory_db()
    try:
        init_schema(conn)
        assert _lesson_index_sql(conn) is not None
    finally:
        conn.close()
