"""CRUD + confirmation flow for decision_candidates.

Public API consumed by cli/decisions_cmds.py and mcp/tools/decision_candidates.py.
Every confirmation promotes the candidate's provenance into the canonical
decision_* join tables via existing helpers in core/decisions.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    result: dict[str, Any] = dict(row)
    for field_name in ("rejected_alternatives", "supporting_evidence", "files", "confidence_breakdown"):
        raw = result.get(field_name)
        if not raw:
            result[field_name] = [] if field_name != "confidence_breakdown" else {}
            continue
        try:
            result[field_name] = json.loads(raw)
        except (ValueError, TypeError):
            result[field_name] = [] if field_name != "confidence_breakdown" else {}
    return result


def _resolve_candidate_id(conn, candidate_id: str) -> str | None:
    if not candidate_id:
        return None
    row = conn.execute("SELECT id FROM decision_candidates WHERE id = ?", (candidate_id,)).fetchone()
    if row is not None:
        return row["id"]
    row = conn.execute(
        "SELECT id FROM decision_candidates WHERE id LIKE ? LIMIT 2",
        (f"{candidate_id}%",),
    ).fetchall()
    if len(row) == 1:
        return row[0]["id"]
    return None


def list_candidates(
    conn,
    *,
    session_id: str | None = None,
    status: str | None = None,
    min_confidence: float = 0.0,
    source_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if status:
        clauses.append("review_status = ?")
        params.append(status)
    if source_type:
        clauses.append("source_type = ?")
        params.append(source_type)
    if min_confidence > 0:
        clauses.append("confidence >= ?")
        params.append(float(min_confidence))
    # clauses contains literal column comparison fragments authored above
    # (e.g. "session_id = ?"). All user-supplied values flow through params
    # via ? bindings, never into the SQL text.
    where_clause = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    query = (  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
        f"SELECT * FROM decision_candidates{where_clause} ORDER BY confidence DESC, created_at DESC LIMIT ?"
    )
    params.append(int(limit))
    rows = conn.execute(query, params).fetchall()
    return [r for r in (_row_to_dict(row) for row in rows) if r is not None]


def get_candidate(conn, candidate_id: str) -> dict[str, Any] | None:
    resolved = _resolve_candidate_id(conn, candidate_id)
    if resolved is None:
        return None
    row = conn.execute("SELECT * FROM decision_candidates WHERE id = ?", (resolved,)).fetchone()
    return _row_to_dict(row)


def confirm_candidate(
    conn,
    candidate_id: str,
    *,
    scope_override: str | None = None,
    reviewer: str = "cli",
    note: str | None = None,
) -> dict[str, Any]:
    candidate = get_candidate(conn, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate '{candidate_id}' not found")
    if candidate.get("review_status") != "pending":
        raise ValueError(f"Candidate '{candidate['id']}' is already {candidate.get('review_status')}")

    from .decisions import (
        create_decision,
        link_decision_to_assessment,
        link_decision_to_checkpoint,
        link_decision_to_file,
    )

    rejected = candidate.get("rejected_alternatives") or []
    supporting = candidate.get("supporting_evidence") or []
    scope = scope_override if scope_override is not None else candidate.get("scope")

    decision = create_decision(
        conn,
        title=candidate["title"],
        rationale=candidate.get("rationale"),
        scope=scope,
        rejected_alternatives=rejected,
        supporting_evidence=supporting,
    )
    decision_id = decision["id"]

    files = candidate.get("files") or []
    for file_path in files:
        if isinstance(file_path, str) and file_path:
            try:
                link_decision_to_file(conn, decision_id, file_path)
            except Exception:
                continue

    if candidate.get("checkpoint_id"):
        try:
            link_decision_to_checkpoint(conn, decision_id, candidate["checkpoint_id"])
        except Exception:
            pass

    if candidate.get("assessment_id"):
        try:
            link_decision_to_assessment(
                conn,
                decision_id,
                candidate["assessment_id"],
                relation_type="informed_by",
            )
        except Exception:
            pass

    now = _now_iso()
    conn.execute(
        "UPDATE decision_candidates SET review_status='confirmed', reviewed_at=?, "
        "reviewed_by=?, review_note=?, promoted_decision_id=?, updated_at=? WHERE id=?",
        (now, reviewer, note, decision_id, now, candidate["id"]),
    )
    conn.commit()

    _record_event(
        conn,
        source=reviewer,
        phase="confirm",
        status="ok",
        session_id=candidate.get("session_id"),
        message=None,
    )
    return {
        "candidate_id": candidate["id"],
        "decision_id": decision_id,
        "promoted": True,
    }


def reject_candidate(
    conn,
    candidate_id: str,
    *,
    reason: str | None = None,
    reviewer: str = "cli",
) -> dict[str, Any]:
    candidate = get_candidate(conn, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate '{candidate_id}' not found")
    if candidate.get("review_status") != "pending":
        raise ValueError(f"Candidate '{candidate['id']}' is already {candidate.get('review_status')}")

    now = _now_iso()
    conn.execute(
        "UPDATE decision_candidates SET review_status='rejected', reviewed_at=?, "
        "reviewed_by=?, review_note=?, updated_at=? WHERE id=?",
        (now, reviewer, reason, now, candidate["id"]),
    )
    conn.commit()

    _record_event(
        conn,
        source=reviewer,
        phase="reject",
        status="ok",
        session_id=candidate.get("session_id"),
        message=None,
    )
    return {
        "candidate_id": candidate["id"],
        "rejected": True,
    }


def _record_event(
    conn,
    *,
    source: str,
    phase: str,
    status: str,
    session_id: str | None = None,
    message: str | None = None,
) -> None:
    try:
        from .telemetry import record_operation_event

        record_operation_event(
            conn,
            source=source,
            operation_name="decision_candidate_extract",
            phase=phase,
            status=status,
            session_id=session_id,
            message=message,
        )
    except Exception:
        return
