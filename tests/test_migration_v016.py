"""Tests for schema v15 → v16 migration."""

import sqlite3

import pytest

from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import apply_migrations

# Narrow (v15) decision_candidates CHECK constraint — does NOT accept 'archaeology'.
_V15_DECISION_CANDIDATES_DDL = """
CREATE TABLE decision_candidates (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    rationale TEXT,
    scope TEXT,
    rejected_alternatives TEXT,
    supporting_evidence TEXT,
    source_type TEXT NOT NULL CHECK(source_type IN ('session','checkpoint','assessment')),
    source_id TEXT NOT NULL,
    session_id TEXT,
    checkpoint_id TEXT,
    assessment_id TEXT,
    files TEXT,
    confidence REAL NOT NULL DEFAULT 0.0,
    confidence_breakdown TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(review_status IN ('pending','confirmed','rejected')),
    reviewed_at TEXT,
    reviewed_by TEXT,
    review_note TEXT,
    promoted_decision_id TEXT,
    dedup_key TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
"""


@pytest.fixture
def v15_db():
    """A genuine schema-v15 database: narrow decision_candidates CHECK, no archaeology_processed."""
    conn = get_memory_db()
    conn.execute(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT, description TEXT)"
    )
    conn.execute("INSERT INTO schema_version (version, description) VALUES (15, 'v15')")

    # FK targets referenced by decision_candidates (foreign_keys=ON requires them to exist).
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE checkpoints (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE assessments (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE decisions (id TEXT PRIMARY KEY)")

    conn.execute(_V15_DECISION_CANDIDATES_DDL)
    conn.execute(
        "CREATE INDEX idx_decision_candidates_review ON decision_candidates(review_status)"
    )
    conn.execute(
        "CREATE INDEX idx_decision_candidates_source ON decision_candidates(source_type, source_id)"
    )
    conn.execute(
        "CREATE INDEX idx_decision_candidates_confidence ON decision_candidates(confidence DESC)"
    )
    conn.execute("CREATE INDEX idx_decision_candidates_dedup ON decision_candidates(dedup_key)")
    conn.execute("CREATE INDEX idx_decision_candidates_session ON decision_candidates(session_id)")
    conn.execute(
        "CREATE UNIQUE INDEX uniq_decision_candidates_source_dedup "
        "ON decision_candidates(source_type, source_id, dedup_key)"
    )

    conn.execute(
        """
        CREATE VIRTUAL TABLE fts_decision_candidates USING fts5(
            title, rationale,
            content='decision_candidates',
            content_rowid='rowid'
        )
        """
    )
    conn.execute(
        """
        CREATE TRIGGER fts_decision_candidates_ai AFTER INSERT ON decision_candidates BEGIN
          INSERT INTO fts_decision_candidates(rowid, title, rationale)
          VALUES (new.rowid, new.title, new.rationale);
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER fts_decision_candidates_ad AFTER DELETE ON decision_candidates BEGIN
          INSERT INTO fts_decision_candidates(fts_decision_candidates, rowid, title, rationale)
          VALUES ('delete', old.rowid, old.title, old.rationale);
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER fts_decision_candidates_au AFTER UPDATE ON decision_candidates BEGIN
          INSERT INTO fts_decision_candidates(fts_decision_candidates, rowid, title, rationale)
          VALUES ('delete', old.rowid, old.title, old.rationale);
          INSERT INTO fts_decision_candidates(rowid, title, rationale)
          VALUES (new.rowid, new.title, new.rationale);
        END
        """
    )

    yield conn
    conn.close()


def test_archaeology_processed_table_exists(v15_db):
    apply_migrations(v15_db, 15, 16)
    row = v15_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='archaeology_processed'"
    ).fetchone()
    assert row is not None


def test_source_type_accepts_archaeology(v15_db):
    apply_migrations(v15_db, 15, 16)
    v15_db.execute(
        "INSERT INTO decision_candidates "
        "(id, title, source_type, source_id, confidence, dedup_key) "
        "VALUES ('test1', 'Test', 'archaeology', 'abc123', 0.5, 'dk1')"
    )
    row = v15_db.execute(
        "SELECT source_type FROM decision_candidates WHERE id = 'test1'"
    ).fetchone()
    assert row["source_type"] == "archaeology"


def test_source_type_rejects_invalid(v15_db):
    apply_migrations(v15_db, 15, 16)
    with pytest.raises(sqlite3.IntegrityError):
        v15_db.execute(
            "INSERT INTO decision_candidates "
            "(id, title, source_type, source_id, confidence, dedup_key) "
            "VALUES ('test2', 'Test', 'bogus', 'abc123', 0.5, 'dk2')"
        )


def test_existing_candidates_preserved(v15_db):
    v15_db.execute(
        "INSERT INTO decision_candidates "
        "(id, title, source_type, source_id, confidence, dedup_key, rationale) "
        "VALUES ('pre1', 'Existing', 'session', 's1', 0.7, 'dk0', 'reason')"
    )
    apply_migrations(v15_db, 15, 16)
    row = v15_db.execute(
        "SELECT title, source_type, rationale FROM decision_candidates WHERE id = 'pre1'"
    ).fetchone()
    assert row["title"] == "Existing"
    assert row["source_type"] == "session"
    assert row["rationale"] == "reason"


def test_fts_triggers_work_after_migration(v15_db):
    apply_migrations(v15_db, 15, 16)
    v15_db.execute(
        "INSERT INTO decision_candidates "
        "(id, title, source_type, source_id, confidence, dedup_key, rationale) "
        "VALUES ('fts1', 'Archaeology FTS Test', 'archaeology', 'abc', 0.5, 'dk3', 'test rationale')"
    )
    rows = v15_db.execute(
        "SELECT * FROM fts_decision_candidates WHERE fts_decision_candidates MATCH 'Archaeology'"
    ).fetchall()
    assert len(rows) >= 1


def test_archaeology_processed_schema(v15_db):
    apply_migrations(v15_db, 15, 16)
    v15_db.execute(
        "INSERT INTO archaeology_processed (commit_sha, candidate_count) VALUES ('abc123', 3)"
    )
    row = v15_db.execute(
        "SELECT commit_sha, candidate_count, processed_at FROM archaeology_processed WHERE commit_sha = 'abc123'"
    ).fetchone()
    assert row["commit_sha"] == "abc123"
    assert row["candidate_count"] == 3
    assert row["processed_at"] is not None
