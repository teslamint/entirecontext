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
    query = f"SELECT * FROM decision_candidates{where_clause} ORDER BY confidence DESC, created_at DESC LIMIT ?"
    params.append(int(limit))
    # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
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
    """Promote a candidate to a real decision with atomic concurrency safety.

    The confirm flow is NOT wrapped in a single transaction because
    `create_decision` and `link_decision_to_*` in core/decisions.py each
    commit internally. To prevent (a) concurrent double-confirm via CLI +
    MCP and (b) duplicate decision creation on process crash mid-flight,
    the flow uses an atomic conditional UPDATE as a lock:

      1. CAS-claim the candidate with
         `UPDATE ... WHERE id=? AND review_status='pending'`.
         Only one caller sees rowcount=1; everyone else raises.
      2. Create the decision and link provenance (each auto-commits).
      3. Second UPDATE stores `promoted_decision_id`.

    If step 2 or 3 raises, the claim is rolled back to `pending` so the
    candidate can be retried. A crash between step 2 and 3 leaves the
    candidate in `confirmed` state with `promoted_decision_id IS NULL`
    — detectable and recoverable via a follow-up, and far better than
    silently creating a duplicate decision.
    """
    candidate = get_candidate(conn, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate '{candidate_id}' not found")

    # Step 1: atomic claim. The pending → confirmed transition is the
    # concurrency gate; no caller can successfully claim this row twice,
    # even across connections, because the UPDATE sees the committed
    # state at the time it runs.
    now = _now_iso()
    cursor = conn.execute(
        "UPDATE decision_candidates SET review_status='confirmed', reviewed_at=?, "
        "reviewed_by=?, review_note=?, updated_at=? "
        "WHERE id=? AND review_status='pending'",
        (now, reviewer, note, now, candidate["id"]),
    )
    if cursor.rowcount == 0:
        # Someone else won the race, or the candidate was already
        # confirmed/rejected. Re-read to give the caller an accurate reason.
        fresh = get_candidate(conn, candidate["id"])
        status = fresh.get("review_status") if fresh else "unknown"
        raise ValueError(f"Candidate '{candidate['id']}' is already {status}")
    conn.commit()

    # Step 2: create the decision and link provenance. Each helper below
    # auto-commits, so every write after this point is durable.
    from .decisions import (
        create_decision,
        link_decision_to_assessment,
        link_decision_to_checkpoint,
        link_decision_to_file,
    )

    rejected = candidate.get("rejected_alternatives") or []
    supporting = candidate.get("supporting_evidence") or []
    scope = scope_override if scope_override is not None else candidate.get("scope")

    try:
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

        # Step 3: store the decision back-pointer. The earlier claim
        # UPDATE already committed so we are guaranteed the row is ours.
        conn.execute(
            "UPDATE decision_candidates SET promoted_decision_id=?, updated_at=? WHERE id=?",
            (decision_id, _now_iso(), candidate["id"]),
        )
        conn.commit()
    except Exception:
        # Roll the claim back to pending so the candidate can be retried.
        # Conditioned on (confirmed + promoted_decision_id IS NULL) to
        # avoid racing a later successful confirm.
        conn.execute(
            "UPDATE decision_candidates SET review_status='pending', reviewed_at=NULL, "
            "reviewed_by=NULL, review_note=NULL, updated_at=? "
            "WHERE id=? AND review_status='confirmed' AND promoted_decision_id IS NULL",
            (_now_iso(), candidate["id"]),
        )
        conn.commit()
        raise

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
