"""Migration to schema v17: track PR-body archaeology processing."""

from __future__ import annotations

import sqlite3


def _add_pr_body_processed(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(archaeology_processed)")}
    if "pr_body_processed" not in columns:
        conn.execute(
            "ALTER TABLE archaeology_processed "
            "ADD COLUMN pr_body_processed INTEGER NOT NULL DEFAULT 0"
        )


MIGRATION_STEPS = [_add_pr_body_processed]
