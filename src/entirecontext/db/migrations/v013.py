"""Migration to schema v13 — decision_candidates table for candidate extraction pipeline."""

from __future__ import annotations


def _create_decision_candidates_table(conn):
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='decision_candidates'").fetchone()
    if row is not None:
        return
    conn.execute(
        """
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
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL,
            FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(id) ON DELETE SET NULL,
            FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE SET NULL,
            FOREIGN KEY (promoted_decision_id) REFERENCES decisions(id) ON DELETE SET NULL
        )
        """
    )


def _create_decision_candidates_indexes(conn):
    conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_candidates_review ON decision_candidates(review_status)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_candidates_source ON decision_candidates(source_type, source_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_candidates_confidence ON decision_candidates(confidence DESC)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_candidates_dedup ON decision_candidates(dedup_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_candidates_session ON decision_candidates(session_id)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uniq_decision_candidates_source_dedup "
        "ON decision_candidates(source_type, source_id, dedup_key)"
    )


def _create_fts_decision_candidates(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='fts_decision_candidates'"
    ).fetchone()
    if row is not None:
        return
    conn.execute(
        """
        CREATE VIRTUAL TABLE fts_decision_candidates USING fts5(
            title,
            rationale,
            content='decision_candidates',
            content_rowid='rowid'
        )
        """
    )


def _create_fts_decision_candidates_triggers(conn):
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_decision_candidates_ai
        AFTER INSERT ON decision_candidates BEGIN
          INSERT INTO fts_decision_candidates(rowid, title, rationale)
          VALUES (new.rowid, new.title, new.rationale);
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_decision_candidates_ad
        AFTER DELETE ON decision_candidates BEGIN
          INSERT INTO fts_decision_candidates(fts_decision_candidates, rowid, title, rationale)
          VALUES ('delete', old.rowid, old.title, old.rationale);
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_decision_candidates_au
        AFTER UPDATE ON decision_candidates BEGIN
          INSERT INTO fts_decision_candidates(fts_decision_candidates, rowid, title, rationale)
          VALUES ('delete', old.rowid, old.title, old.rationale);
          INSERT INTO fts_decision_candidates(rowid, title, rationale)
          VALUES (new.rowid, new.title, new.rationale);
        END
        """
    )


MIGRATION_STEPS = [
    _create_decision_candidates_table,
    _create_decision_candidates_indexes,
    _create_fts_decision_candidates,
    _create_fts_decision_candidates_triggers,
]
