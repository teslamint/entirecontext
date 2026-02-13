"""Session CRUD operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_session(
    conn,
    project_id: str,
    session_type: str = "claude",
    session_id: str | None = None,
    agent_id: str | None = None,
    workspace_path: str | None = None,
) -> dict:
    """Create a new session."""
    if session_id is None:
        session_id = str(uuid4())
    now = _now_iso()

    conn.execute(
        """INSERT INTO sessions
        (id, project_id, agent_id, session_type, workspace_path, started_at, last_activity_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (session_id, project_id, agent_id, session_type, workspace_path, now, now),
    )
    conn.commit()
    return {"id": session_id, "project_id": project_id, "started_at": now}


def get_session(conn, session_id: str) -> dict | None:
    """Get a session by ID."""
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def list_sessions(
    conn,
    project_id: str | None = None,
    limit: int = 20,
    include_ended: bool = True,
) -> list[dict]:
    """List sessions, optionally filtered by project."""
    query = "SELECT * FROM sessions"
    params: list[Any] = []
    conditions = []

    if project_id:
        conditions.append("project_id = ?")
        params.append(project_id)
    if not include_ended:
        conditions.append("ended_at IS NULL")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY last_activity_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_current_session(conn) -> dict | None:
    """Get the most recently active session."""
    row = conn.execute(
        "SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY last_activity_at DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def update_session(conn, session_id: str, **kwargs) -> None:
    """Update session fields."""
    if not kwargs:
        return
    kwargs["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [session_id]
    conn.execute(f"UPDATE sessions SET {set_clause} WHERE id = ?", values)
    conn.commit()
