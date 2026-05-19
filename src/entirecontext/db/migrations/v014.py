"""Migration to schema v14 — widen decision_outcomes.outcome_type CHECK to include 'refined', 'replaced'."""

from __future__ import annotations

import sqlite3


_WIDENED_DDL = """
        CREATE TABLE decision_outcomes_new (
            id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL,
            retrieval_selection_id TEXT,
            session_id TEXT,
            turn_id TEXT,
            outcome_type TEXT NOT NULL CHECK(outcome_type IN ('accepted', 'ignored', 'contradicted', 'refined', 'replaced')),
            note TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (decision_id) REFERENCES decisions(id) ON DELETE CASCADE,
            FOREIGN KEY (retrieval_selection_id) REFERENCES retrieval_selections(id) ON DELETE SET NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL,
            FOREIGN KEY (turn_id) REFERENCES turns(id) ON DELETE SET NULL
        )
"""


def _rebuild_decision_outcomes(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='decision_outcomes'").fetchone()

    if existing is None:
        conn.execute(_WIDENED_DDL.replace("decision_outcomes_new", "decision_outcomes"))
        conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_outcomes_decision_id ON decision_outcomes(decision_id)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_decision_outcomes_selection_id ON decision_outcomes(retrieval_selection_id)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_outcomes_outcome_type ON decision_outcomes(outcome_type)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_decision_outcomes_created_at ON decision_outcomes(created_at DESC)"
        )
        return

    conn.execute(_WIDENED_DDL)
    conn.execute(
        "INSERT INTO decision_outcomes_new SELECT id, decision_id, retrieval_selection_id, session_id, turn_id, outcome_type, note, created_at FROM decision_outcomes"
    )
    conn.execute("DROP TABLE decision_outcomes")
    conn.execute("ALTER TABLE decision_outcomes_new RENAME TO decision_outcomes")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_outcomes_decision_id ON decision_outcomes(decision_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_outcomes_selection_id ON decision_outcomes(retrieval_selection_id)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_outcomes_outcome_type ON decision_outcomes(outcome_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_outcomes_created_at ON decision_outcomes(created_at DESC)")


MIGRATION_STEPS = [
    _rebuild_decision_outcomes,
]
