"""Migration to schema v16 — add archaeology_processed table, widen decision_candidates.source_type."""

from __future__ import annotations

import sqlite3


def _create_archaeology_processed(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='archaeology_processed'"
    ).fetchone()
    if row is not None:
        return
    conn.execute(
        """
        CREATE TABLE archaeology_processed (
            commit_sha TEXT PRIMARY KEY,
            candidate_count INTEGER NOT NULL DEFAULT 0,
            processed_at TEXT DEFAULT (datetime('now'))
        )
        """
    )


_WIDENED_DDL = """
CREATE TABLE decision_candidates_new (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    rationale TEXT,
    scope TEXT,
    rejected_alternatives TEXT,
    supporting_evidence TEXT,
    source_type TEXT NOT NULL CHECK(source_type IN ('session','checkpoint','assessment','archaeology')),
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
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL,
    FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(id) ON DELETE SET NULL,
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE SET NULL,
    FOREIGN KEY (promoted_decision_id) REFERENCES decisions(id) ON DELETE SET NULL
)
"""

_COLUMNS = (
    "id, title, rationale, scope, rejected_alternatives, supporting_evidence, "
    "source_type, source_id, session_id, checkpoint_id, assessment_id, "
    "files, confidence, confidence_breakdown, review_status, "
    "reviewed_at, reviewed_by, review_note, promoted_decision_id, "
    "dedup_key, created_at, updated_at"
)


def _rebuild_decision_candidates(conn: sqlite3.Connection) -> None:
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='decision_candidates'"
    ).fetchone()

    if existing is None:
        conn.execute(_WIDENED_DDL.replace("decision_candidates_new", "decision_candidates"))
        _create_indexes(conn)
        _create_fts(conn)
        return

    conn.execute("DROP TRIGGER IF EXISTS fts_decision_candidates_ai")
    conn.execute("DROP TRIGGER IF EXISTS fts_decision_candidates_ad")
    conn.execute("DROP TRIGGER IF EXISTS fts_decision_candidates_au")
    conn.execute("DROP TABLE IF EXISTS fts_decision_candidates")

    conn.execute(_WIDENED_DDL)
    conn.execute(
        f"INSERT INTO decision_candidates_new SELECT {_COLUMNS} FROM decision_candidates"
    )
    conn.execute("DROP TABLE decision_candidates")
    conn.execute("ALTER TABLE decision_candidates_new RENAME TO decision_candidates")

    _create_indexes(conn)
    _create_fts(conn)


def _create_indexes(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_candidates_review ON decision_candidates(review_status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_candidates_source ON decision_candidates(source_type, source_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_candidates_confidence ON decision_candidates(confidence DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_candidates_dedup ON decision_candidates(dedup_key)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_candidates_session ON decision_candidates(session_id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uniq_decision_candidates_source_dedup "
        "ON decision_candidates(source_type, source_id, dedup_key)"
    )


def _create_fts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_decision_candidates USING fts5(
            title, rationale,
            content='decision_candidates',
            content_rowid='rowid'
        )
        """
    )
    conn.execute(
        "INSERT INTO fts_decision_candidates(rowid, title, rationale) "
        "SELECT rowid, title, COALESCE(rationale, '') FROM decision_candidates"
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_decision_candidates_ai AFTER INSERT ON decision_candidates BEGIN
          INSERT INTO fts_decision_candidates(rowid, title, rationale)
          VALUES (new.rowid, new.title, COALESCE(new.rationale, ''));
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_decision_candidates_ad AFTER DELETE ON decision_candidates BEGIN
          INSERT INTO fts_decision_candidates(fts_decision_candidates, rowid, title, rationale)
          VALUES ('delete', old.rowid, old.title, COALESCE(old.rationale, ''));
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_decision_candidates_au AFTER UPDATE ON decision_candidates BEGIN
          INSERT INTO fts_decision_candidates(fts_decision_candidates, rowid, title, rationale)
          VALUES ('delete', old.rowid, old.title, COALESCE(old.rationale, ''));
          INSERT INTO fts_decision_candidates(rowid, title, rationale)
          VALUES (new.rowid, new.title, COALESCE(new.rationale, ''));
        END
        """
    )


MIGRATION_STEPS = [
    _create_archaeology_processed,
    _rebuild_decision_candidates,
]
