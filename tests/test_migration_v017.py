"""Tests for schema v16 to v17 migration."""

import pytest

from entirecontext.core.archaeology import _ProcessingState, _get_processing_state
from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import apply_migrations


@pytest.fixture
def v16_db():
    conn = get_memory_db()
    conn.execute(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT, description TEXT)"
    )
    conn.execute("INSERT INTO schema_version (version, description) VALUES (16, 'v16')")
    conn.execute(
        "CREATE TABLE archaeology_processed ("
        "commit_sha TEXT PRIMARY KEY, "
        "candidate_count INTEGER NOT NULL DEFAULT 0, "
        "processed_at TEXT DEFAULT (datetime('now')))"
    )
    yield conn
    conn.close()


def test_v16_rows_default_to_pr_incomplete(v16_db):
    v16_db.execute(
        "INSERT INTO archaeology_processed (commit_sha, candidate_count) VALUES ('abc', 2)"
    )
    apply_migrations(v16_db, 16, 17)
    row = v16_db.execute(
        "SELECT candidate_count, pr_body_processed FROM archaeology_processed"
    ).fetchone()
    assert tuple(row) == (2, 0)


def test_v16_read_only_state_fallback(v16_db):
    v16_db.execute(
        "INSERT INTO archaeology_processed (commit_sha, candidate_count) VALUES ('abc', 2)"
    )
    state = _get_processing_state(v16_db, "abc")
    assert state == _ProcessingState(True, False, 2)
