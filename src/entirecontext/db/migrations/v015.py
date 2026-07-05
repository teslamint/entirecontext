"""Migration to schema v15 — add ranking_snapshots table for hypothesis validation."""

from __future__ import annotations

import sqlite3


def _create_ranking_snapshots(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ranking_snapshots'").fetchone()
    if row is not None:
        return
    conn.execute(
        """
        CREATE TABLE ranking_snapshots (
            id TEXT PRIMARY KEY,
            retrieval_event_id TEXT,
            input_files TEXT,
            input_diff_text TEXT,
            input_commits TEXT,
            input_assessment_ids TEXT,
            scored_candidates TEXT NOT NULL,
            effective_limit INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (retrieval_event_id) REFERENCES retrieval_events(id) ON DELETE SET NULL
        )
        """
    )


def _create_ranking_snapshots_indexes(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ranking_snapshots_event_id ON ranking_snapshots(retrieval_event_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ranking_snapshots_created_at ON ranking_snapshots(created_at DESC)"
    )


MIGRATION_STEPS = [
    _create_ranking_snapshots,
    _create_ranking_snapshots_indexes,
]
