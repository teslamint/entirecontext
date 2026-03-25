"""Decision MCP tools."""

from __future__ import annotations

import json

from .. import runtime


async def ec_decision_get(decision_id: str) -> str:
    conn, _ = runtime.get_repo_db()
    if not conn:
        return runtime.error_payload("Not in an EntireContext-initialized repo")
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
    conn, _ = runtime.get_repo_db()
    if not conn:
        return runtime.error_payload("Not in an EntireContext-initialized repo")
    try:
        from ...core.search import rank_related_decisions

        decisions = rank_related_decisions(
            conn,
            file_paths=files or [],
            assessment_ids=assessment_ids or [],
            diff_text=diff_text,
            limit=limit,
        )
        for idx, item in enumerate(decisions, start=1):
            runtime.record_selection(
                conn,
                retrieval_event_id=retrieval_event_id,
                result_type="decision",
                result_id=item["id"],
                rank=idx,
            )
        return json.dumps({"decisions": decisions, "count": len(decisions)})
    finally:
        conn.close()


def register_tools(mcp, services=None) -> None:
    for tool in (ec_decision_get, ec_decision_related):
        mcp.tool()(tool)
