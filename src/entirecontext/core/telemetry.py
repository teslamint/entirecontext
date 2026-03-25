"""Telemetry helpers for retrieval and intervention tracking."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from .session import get_current_session

VALID_APPLICATION_TYPES = ("reference", "decision_change", "code_reuse", "lesson_applied")
VALID_OPERATION_STATUSES = ("ok", "warning", "error")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def detect_current_context(conn) -> tuple[str | None, str | None]:
    """Return the active session and its latest turn, if any."""
    session = get_current_session(conn)
    if not session:
        return None, None

    turn = conn.execute(
        "SELECT id FROM turns WHERE session_id = ? ORDER BY turn_number DESC LIMIT 1",
        (session["id"],),
    ).fetchone()
    return session["id"], (turn["id"] if turn else None)


def record_retrieval_event(
    conn,
    *,
    source: str,
    search_type: str,
    target: str,
    query: str,
    result_count: int,
    latency_ms: int,
    session_id: str | None = None,
    turn_id: str | None = None,
    file_filter: str | None = None,
    commit_filter: str | None = None,
    agent_filter: str | None = None,
    since_filter: str | None = None,
) -> dict:
    event_id = str(uuid4())
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO retrieval_events (
            id, session_id, turn_id, source, search_type, target, query,
            file_filter, commit_filter, agent_filter, since_filter,
            result_count, latency_ms, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            session_id,
            turn_id,
            source,
            search_type,
            target,
            query,
            file_filter,
            commit_filter,
            agent_filter,
            since_filter,
            result_count,
            latency_ms,
            now,
        ),
    )
    conn.commit()
    return {
        "id": event_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "source": source,
        "search_type": search_type,
        "target": target,
        "query": query,
        "result_count": result_count,
        "latency_ms": latency_ms,
        "created_at": now,
    }


def get_retrieval_event(conn, retrieval_event_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM retrieval_events WHERE id = ?", (retrieval_event_id,)).fetchone()
    return dict(row) if row else None


def record_retrieval_selection(
    conn,
    retrieval_event_id: str,
    result_type: str,
    result_id: str,
    *,
    rank: int = 1,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> dict:
    event = get_retrieval_event(conn, retrieval_event_id)
    if not event:
        raise ValueError(f"Retrieval event '{retrieval_event_id}' not found")

    selection_id = str(uuid4())
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO retrieval_selections (
            id, retrieval_event_id, session_id, turn_id, result_type, result_id, rank, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            selection_id,
            retrieval_event_id,
            session_id or event.get("session_id"),
            turn_id or event.get("turn_id"),
            result_type,
            result_id,
            rank,
            now,
        ),
    )
    conn.commit()
    return {
        "id": selection_id,
        "retrieval_event_id": retrieval_event_id,
        "session_id": session_id or event.get("session_id"),
        "turn_id": turn_id or event.get("turn_id"),
        "result_type": result_type,
        "result_id": result_id,
        "rank": rank,
        "created_at": now,
    }


def get_retrieval_selection(conn, selection_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM retrieval_selections WHERE id = ?", (selection_id,)).fetchone()
    return dict(row) if row else None


def record_context_application(
    conn,
    *,
    application_type: str,
    selection_id: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    note: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> dict:
    if application_type not in VALID_APPLICATION_TYPES:
        raise ValueError(f"Invalid application_type '{application_type}'. Must be one of: {VALID_APPLICATION_TYPES}")

    selection = None
    if selection_id:
        selection = get_retrieval_selection(conn, selection_id)
        if not selection:
            raise ValueError(f"Retrieval selection '{selection_id}' not found")
        source_type = selection["result_type"]
        source_id = selection["result_id"]
        session_id = session_id or selection.get("session_id")
        turn_id = turn_id or selection.get("turn_id")
    elif not source_type or not source_id:
        raise ValueError("source_type and source_id are required when selection_id is not provided")

    application_id = str(uuid4())
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO context_applications (
            id, session_id, turn_id, retrieval_selection_id,
            source_type, source_id, application_type, note, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            application_id,
            session_id,
            turn_id,
            selection["id"] if selection else None,
            source_type,
            source_id,
            application_type,
            note,
            now,
        ),
    )
    conn.commit()
    return {
        "id": application_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "retrieval_selection_id": selection["id"] if selection else None,
        "source_type": source_type,
        "source_id": source_id,
        "application_type": application_type,
        "note": note,
        "created_at": now,
    }


def record_operation_event(
    conn,
    *,
    source: str,
    operation_name: str,
    phase: str,
    status: str,
    latency_ms: int = 0,
    session_id: str | None = None,
    turn_id: str | None = None,
    error_class: str | None = None,
    message: str | None = None,
    metadata: dict | None = None,
) -> dict:
    if status not in VALID_OPERATION_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {VALID_OPERATION_STATUSES}")

    event_id = str(uuid4())
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO operation_events (
            id, session_id, turn_id, source, operation_name, phase, status,
            latency_ms, error_class, message, metadata, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            session_id,
            turn_id,
            source,
            operation_name,
            phase,
            status,
            latency_ms,
            error_class,
            message,
            json.dumps(metadata) if metadata is not None else None,
            now,
        ),
    )
    conn.commit()
    return {
        "id": event_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "source": source,
        "operation_name": operation_name,
        "phase": phase,
        "status": status,
        "latency_ms": latency_ms,
        "error_class": error_class,
        "message": message,
        "metadata": metadata,
        "created_at": now,
    }
