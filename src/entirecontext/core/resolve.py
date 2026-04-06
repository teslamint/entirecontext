"""Shared ID resolution utilities for prefix-matching database records."""

from __future__ import annotations

_ALLOWED_TABLES: frozenset[str] = frozenset({"decisions", "checkpoints", "assessments"})


def escape_like(value: str) -> str:
    """Escape LIKE metacharacters (%, _, \\) so they are treated literally in a LIKE query."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def resolve_id(conn, table: str, id_value: str) -> str | None:
    """Resolve a full or prefix ID from any table. Returns full ID or None.

    First tries an exact match, then falls back to a prefix LIKE query.
    LIKE metacharacters (%, _) in the input are escaped so they are treated literally.

    Raises ValueError if ``table`` is not in the allowed set, preventing SQL injection.
    """
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Table '{table}' is not allowed. Must be one of: {sorted(_ALLOWED_TABLES)}")
    row = conn.execute(f"SELECT id FROM {table} WHERE id = ?", (id_value,)).fetchone()
    if row is None:
        row = conn.execute(f"SELECT id FROM {table} WHERE id LIKE ? ESCAPE '\\'", (f"{escape_like(id_value)}%",)).fetchone()
    return row["id"] if row else None


def resolve_decision_id(conn, decision_id: str) -> str | None:
    return resolve_id(conn, "decisions", decision_id)


def resolve_checkpoint_id(conn, checkpoint_id: str) -> str | None:
    return resolve_id(conn, "checkpoints", checkpoint_id)


def resolve_assessment_id(conn, assessment_id: str) -> str | None:
    return resolve_id(conn, "assessments", assessment_id)
