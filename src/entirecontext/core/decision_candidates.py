"""CRUD + confirmation flow for decision_candidates.

Public API consumed by cli/decisions_cmds.py and mcp/tools/decision_candidates.py.
Every confirmation promotes the candidate's provenance into the canonical
decision_* join tables via existing helpers in core/decisions.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .context import transaction


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

    Three independent commit boundaries cooperate to give both concurrency
    safety and atomic promotion. Under autocommit, each DML self-commits
    unless wrapped in `transaction()`, so the boundaries are implicit:

      1. CAS-claim the candidate with
         `UPDATE ... WHERE id=? AND review_status='pending'` (self-commits
         under autocommit). Only one caller sees rowcount=1; everyone else
         raises. The claim must persist before promotion starts so
         concurrent callers see the gate flipped.
      2. Inside a single `BEGIN IMMEDIATE` (via `core/context.transaction`),
         create the decision, link provenance, and store the
         `promoted_decision_id` back-pointer. If anything in this block
         raises, the entire promotion rolls back atomically — no orphan
         `decisions` row, no orphan join rows.
      3. On Step-2 failure, an outer-except conditional UPDATE rolls the
         claim back to `pending` so the candidate can be retried. This
         compensating UPDATE is independent of Step 2's wrapped tx because
         Step 1 already self-committed; SQLite ROLLBACK cannot reach across
         that boundary.

    The only mid-flight stuck state remaining is "claim committed, Step 2
    not started" (process crash between Step 1's UPDATE and Step 2 BEGIN).
    The v0.2.0 gap — `decisions` row durable but candidate back-pointer
    missing — is closed.
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

    # Step 2: create the decision and link provenance inside a single
    # BEGIN IMMEDIATE (via transaction()). Helpers defer to the outer
    # transaction owner when the per-conn depth counter is non-zero.
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
        with transaction(conn):
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

            # Step 3: store the decision back-pointer. Wrapped together with
            # Step 2's create + links in a single BEGIN IMMEDIATE so any
            # failure here rolls back the decision row + join rows atomically.
            conn.execute(
                "UPDATE decision_candidates SET promoted_decision_id=?, updated_at=? WHERE id=?",
                (decision_id, _now_iso(), candidate["id"]),
            )
    except Exception:
        # Roll the claim back to pending so the candidate can be retried.
        # The wrapped Step 2 transaction has already rolled back its DML;
        # this UPDATE addresses Step 1's separately-committed claim, which
        # SQLite ROLLBACK cannot reach. Conditioned on
        # (confirmed + promoted_decision_id IS NULL) to avoid racing a
        # later successful confirm.
        conn.execute(
            "UPDATE decision_candidates SET review_status='pending', reviewed_at=NULL, "
            "reviewed_by=NULL, review_note=NULL, updated_at=? "
            "WHERE id=? AND review_status='confirmed' AND promoted_decision_id IS NULL",
            (_now_iso(), candidate["id"]),
        )
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
    """Reject a candidate with the same atomic-claim pattern as confirm.

    Without the conditional UPDATE, a concurrent confirm_candidate could
    CAS-claim and promote the candidate between our Python-level pending
    check and the UPDATE, resulting in a 'rejected' candidate whose
    promoted_decision_id still points at a committed `decisions` row —
    a dangling invariant we cannot recover from.
    """
    candidate = get_candidate(conn, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate '{candidate_id}' not found")

    now = _now_iso()
    cursor = conn.execute(
        "UPDATE decision_candidates SET review_status='rejected', reviewed_at=?, "
        "reviewed_by=?, review_note=?, updated_at=? "
        "WHERE id=? AND review_status='pending'",
        (now, reviewer, reason, now, candidate["id"]),
    )
    if cursor.rowcount == 0:
        fresh = get_candidate(conn, candidate["id"])
        status = fresh.get("review_status") if fresh else "unknown"
        raise ValueError(f"Candidate '{candidate['id']}' is already {status}")

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
