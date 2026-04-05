"""Shared ID resolution utilities for prefix-matching database records."""

from __future__ import annotations


def resolve_id(conn, table: str, id_value: str) -> str | None:
    """Resolve a full or prefix ID from any table. Returns full ID or None.

    First tries an exact match, then falls back to a prefix LIKE query.
    LIKE metacharacters (%, _) in the input are escaped so they are treated literally.
    """
    row = conn.execute(f"SELECT id FROM {table} WHERE id = ?", (id_value,)).fetchone()
    if row is None:
        escaped = id_value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        row = conn.execute(f"SELECT id FROM {table} WHERE id LIKE ? ESCAPE '\\'", (f"{escaped}%",)).fetchone()
    return row["id"] if row else None


def resolve_decision_id(conn, decision_id: str) -> str | None:
    return resolve_id(conn, "decisions", decision_id)


def resolve_checkpoint_id(conn, checkpoint_id: str) -> str | None:
    return resolve_id(conn, "checkpoints", checkpoint_id)


def resolve_assessment_id(conn, assessment_id: str) -> str | None:
    return resolve_id(conn, "assessments", assessment_id)
