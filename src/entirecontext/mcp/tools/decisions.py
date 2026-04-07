"""Decision MCP tools."""

from __future__ import annotations

import json
import time

from .. import runtime


def _resolve_repo():
    try:
        return runtime.get_repo_db(), None
    except runtime.RepoResolutionError as exc:
        return (None, None), runtime.error_payload(str(exc))


async def ec_decision_get(decision_id: str) -> str:
    (conn, _), error = _resolve_repo()
    if error:
        return error
    try:
        from ...core.decisions import get_decision

        decision = get_decision(conn, decision_id)
        if not decision:
            return runtime.error_payload(f"Decision '{decision_id}' not found")
        return json.dumps(decision)
    finally:
        conn.close()


async def ec_decision_related(
    files: list[str] | None = None,
    assessment_ids: list[str] | None = None,
    diff_text: str | None = None,
    limit: int = 10,
    retrieval_event_id: str | None = None,
) -> str:
    (conn, _), error = _resolve_repo()
    if error:
        return error
    try:
        from ...core.decisions import rank_related_decisions

        started_at = time.perf_counter()
        decisions = rank_related_decisions(
            conn,
            file_paths=files or [],
            assessment_ids=assessment_ids or [],
            diff_text=diff_text,
            limit=limit,
        )
        tracked_event_id = runtime.record_search_event(
            conn,
            query=diff_text or "decision-related",
            search_type="decision_related",
            target="decision",
            result_count=len(decisions),
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            file_filter=",".join(files or []) or None,
            since=None,
        )
        for idx, item in enumerate(decisions, start=1):
            runtime.record_selection(
                conn,
                retrieval_event_id=tracked_event_id or retrieval_event_id,
                result_type="decision",
                result_id=item["id"],
                rank=idx,
            )
        return json.dumps(
            {
                "decisions": decisions,
                "count": len(decisions),
                "retrieval_event_id": tracked_event_id,
            }
        )
    finally:
        conn.close()


async def ec_decision_outcome(
    decision_id: str,
    outcome_type: str,
    selection_id: str | None = None,
    note: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> str:
    """Record the outcome of a decision (accepted, ignored, or contradicted).

    Links the outcome to a retrieval selection when selection_id is provided,
    enabling quality tracking. Falls back to the current session context when
    session_id and turn_id are not explicitly provided.
    """
    (conn, _), error = _resolve_repo()
    if error:
        return error
    try:
        from ...core.decisions import record_decision_outcome
        from ...core.telemetry import detect_current_context

        current_session_id, current_turn_id = detect_current_context(conn)
        if current_turn_id is None:
            current_session_id = None
        if session_id is not None or turn_id is not None:
            effective_session_id, effective_turn_id = session_id, turn_id
        else:
            effective_session_id, effective_turn_id = current_session_id, current_turn_id
        outcome = record_decision_outcome(
            conn,
            decision_id,
            outcome_type,
            retrieval_selection_id=selection_id,
            note=note,
            session_id=effective_session_id,
            turn_id=effective_turn_id,
        )
        return json.dumps(outcome)
    except ValueError as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


async def ec_decision_create(
    title: str,
    rationale: str | None = None,
    scope: str | None = None,
    rejected_alternatives: list[str] | None = None,
    supporting_evidence: list | None = None,
) -> str:
    """Create a new decision record.

    Args:
        title: Short name for the decision
        rationale: Reasoning behind the decision
        scope: Scope or area this decision applies to
        rejected_alternatives: List of alternatives that were considered and rejected
        supporting_evidence: Evidence supporting the decision
    """
    (conn, _), error = _resolve_repo()
    if error:
        return error
    try:
        from ...core.decisions import create_decision

        d = create_decision(
            conn,
            title=title,
            rationale=rationale,
            scope=scope,
            rejected_alternatives=rejected_alternatives,
            supporting_evidence=supporting_evidence,
        )
        return json.dumps(d)
    except ValueError as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


async def ec_decision_list(
    staleness_status: str | None = None,
    file_path: str | None = None,
    limit: int = 20,
) -> str:
    """List decisions with optional filters.

    Args:
        staleness_status: Filter by status (fresh/stale/superseded/contradicted)
        file_path: Filter by linked file path
        limit: Maximum results (default 20)
    """
    (conn, _), error = _resolve_repo()
    if error:
        return error
    try:
        from ...core.decisions import list_decisions

        decisions = list_decisions(conn, staleness_status=staleness_status, file_path=file_path, limit=limit)
        return json.dumps({"decisions": decisions, "count": len(decisions)})
    except ValueError as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


async def ec_decision_stale(decision_id: str) -> str:
    """Check if a decision's linked files have changed recently (read-only).

    Returns staleness info without persisting the result. Use the CLI
    ``ec decision stale-all`` command to detect and persist staleness.

    Args:
        decision_id: Decision ID (supports prefix)
    """
    (conn, repo_path), error = _resolve_repo()
    if error:
        return error
    try:
        from ...core.decisions import check_staleness

        result = check_staleness(conn, decision_id, repo_path)
        return json.dumps(result)
    except ValueError as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


def register_tools(mcp, services=None) -> None:
    for tool in (
        ec_decision_get,
        ec_decision_related,
        ec_decision_outcome,
        ec_decision_create,
        ec_decision_list,
        ec_decision_stale,
    ):
        mcp.tool()(tool)
