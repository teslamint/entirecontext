"""Event CRUD operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

VALID_EVENT_TYPES = ("task", "temporal", "milestone")
VALID_STATUSES = ("active", "frozen", "archived")
STATUS_TRANSITIONS = {
    "active": ("frozen", "archived"),
    "frozen": ("archived",),
    "archived": (),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_event(
    conn,
    title: str,
    event_type: str = "task",
    description: str | None = None,
    metadata: str | None = None,
) -> dict:
    """Create a new event."""
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Invalid event_type '{event_type}'. Must be one of: {VALID_EVENT_TYPES}")

    event_id = str(uuid4())
    now = _now_iso()

    conn.execute(
        """INSERT INTO events (id, title, description, event_type, status, start_timestamp, created_at, updated_at, metadata)
        VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
        (event_id, title, description, event_type, now, now, now, metadata),
    )
    conn.commit()
    return {"id": event_id, "title": title, "event_type": event_type, "status": "active", "created_at": now}


def get_event(conn, event_id: str) -> dict | None:
    """Get an event by ID."""
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    return dict(row) if row else None


def list_events(
    conn,
    status: str | None = None,
    event_type: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List events with optional filters."""
    query = "SELECT * FROM events"
    params: list[Any] = []
    conditions = []

    if status:
        conditions.append("status = ?")
        params.append(status)
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def update_event(conn, event_id: str, **kwargs) -> None:
    """Update event fields. Validates status transitions."""
    if not kwargs:
        return

    if "status" in kwargs:
        new_status = kwargs["status"]
        if new_status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{new_status}'. Must be one of: {VALID_STATUSES}")
        current = get_event(conn, event_id)
        if current is None:
            raise ValueError(f"Event '{event_id}' not found")
        allowed = STATUS_TRANSITIONS.get(current["status"], ())
        if new_status not in allowed:
            raise ValueError(f"Cannot transition from '{current['status']}' to '{new_status}'. Allowed: {allowed}")

    kwargs["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [event_id]
    conn.execute(f"UPDATE events SET {set_clause} WHERE id = ?", values)
    conn.commit()


def link_event_session(conn, event_id: str, session_id: str) -> None:
    """Link a session to an event."""
    conn.execute(
        "INSERT OR IGNORE INTO event_sessions (event_id, session_id) VALUES (?, ?)",
        (event_id, session_id),
    )
    conn.commit()


def link_event_checkpoint(conn, event_id: str, checkpoint_id: str) -> None:
    """Link a checkpoint to an event."""
    conn.execute(
        "INSERT OR IGNORE INTO event_checkpoints (event_id, checkpoint_id) VALUES (?, ?)",
        (event_id, checkpoint_id),
    )
    conn.commit()


def get_event_sessions(conn, event_id: str) -> list[dict]:
    """Get sessions linked to an event."""
    rows = conn.execute(
        """SELECT s.* FROM sessions s
        JOIN event_sessions es ON s.id = es.session_id
        WHERE es.event_id = ?
        ORDER BY s.last_activity_at DESC""",
        (event_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_event_checkpoints(conn, event_id: str) -> list[dict]:
    """Get checkpoints linked to an event."""
    rows = conn.execute(
        """SELECT c.* FROM checkpoints c
        JOIN event_checkpoints ec ON c.id = ec.checkpoint_id
        WHERE ec.event_id = ?
        ORDER BY c.created_at DESC""",
        (event_id,),
    ).fetchall()
    return [dict(r) for r in rows]
