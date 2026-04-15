"""MCP tools for decision_candidates — list / get / confirm / reject."""

from __future__ import annotations

import json

from .. import runtime


async def ec_decision_candidate_list(
    session_id: str | None = None,
    status: str | None = None,
    min_confidence: float = 0.0,
    source_type: str | None = None,
    limit: int = 50,
) -> str:
    """List candidate decisions. Filter by session, status, confidence, source type."""
    (conn, _), error = runtime.resolve_repo()
    if error:
        return error
    try:
        from ...core.decision_candidates import list_candidates

        rows = list_candidates(
            conn,
            session_id=session_id,
            status=status,
            min_confidence=min_confidence,
            source_type=source_type,
            limit=limit,
        )
        return json.dumps({"candidates": rows, "count": len(rows)})
    except Exception as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


async def ec_decision_candidate_get(candidate_id: str) -> str:
    """Get a single candidate with full breakdown."""
    (conn, _), error = runtime.resolve_repo()
    if error:
        return error
    try:
        from ...core.decision_candidates import get_candidate

        candidate = get_candidate(conn, candidate_id)
        if not candidate:
            return runtime.error_payload(f"Candidate '{candidate_id}' not found")
        return json.dumps(candidate)
    except Exception as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


async def ec_decision_candidate_confirm(
    candidate_id: str,
    scope: str | None = None,
    note: str | None = None,
) -> str:
    """Confirm a candidate: promote to a real decision with provenance links."""
    (conn, _), error = runtime.resolve_repo()
    if error:
        return error
    try:
        from ...core.decision_candidates import confirm_candidate

        result = confirm_candidate(
            conn,
            candidate_id,
            scope_override=scope,
            reviewer="mcp",
            note=note,
        )
        return json.dumps(result)
    except ValueError as exc:
        return runtime.error_payload(str(exc))
    except Exception as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


async def ec_decision_candidate_reject(candidate_id: str, reason: str | None = None) -> str:
    """Reject a candidate: leaves no trace in decisions."""
    (conn, _), error = runtime.resolve_repo()
    if error:
        return error
    try:
        from ...core.decision_candidates import reject_candidate

        result = reject_candidate(conn, candidate_id, reason=reason, reviewer="mcp")
        return json.dumps(result)
    except ValueError as exc:
        return runtime.error_payload(str(exc))
    except Exception as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


def register_tools(mcp, services=None) -> None:
    for tool in (
        ec_decision_candidate_list,
        ec_decision_candidate_get,
        ec_decision_candidate_confirm,
        ec_decision_candidate_reject,
    ):
        mcp.tool()(tool)
