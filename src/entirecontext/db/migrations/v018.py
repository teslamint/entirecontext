"""Migration to schema v18: index feedback-bearing lessons by verdict and recency."""

from __future__ import annotations

import sqlite3


_INDEX_NAME = "idx_assessments_feedback_recency"
_INDEX_SQL = f"""CREATE INDEX {_INDEX_NAME}
ON assessments(verdict, created_at DESC, id DESC)
WHERE feedback IS NOT NULL"""


def _normalized_index_sql(sql: str) -> str:
    normalized = " ".join(sql.lower().split())
    return normalized.replace("create index if not exists ", "create index ", 1)


def _create_feedback_recency_index(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
        (_INDEX_NAME,),
    ).fetchone()
    if row is None:
        conn.execute(_INDEX_SQL)
        return
    if not isinstance(row[0], str) or _normalized_index_sql(row[0]) != _normalized_index_sql(_INDEX_SQL):
        raise sqlite3.OperationalError(f"index {_INDEX_NAME} has incompatible definition")


MIGRATION_STEPS = [_create_feedback_recency_index]
