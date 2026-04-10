"""Decision MCP tools."""

from __future__ import annotations

import json
import time

from .. import runtime


async def ec_decision_get(decision_id: str) -> str:
    (conn, _), error = runtime.resolve_repo()
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
    (conn, _), error = runtime.resolve_repo()
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
    (conn, _), error = runtime.resolve_repo()
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
    (conn, _), error = runtime.resolve_repo()
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
    (conn, _), error = runtime.resolve_repo()
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
    (conn, repo_path), error = runtime.resolve_repo()
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


async def ec_decision_search(
    query: str,
    search_type: str = "fts",
    since: str | None = None,
    limit: int = 20,
    repos: list[str] | None = None,
) -> str:
    """Search decisions by keyword using FTS5 full-text search.

    Searches decision title and rationale fields. Use this when you need to find
    decisions by keyword rather than by file/assessment context.

    Args:
        query: FTS5 search query (supports AND, OR, NOT, prefix*, "phrase")
        search_type: "fts" for relevance-ranked or "hybrid" for relevance+recency
        since: ISO date filter — only return decisions updated after this date
        limit: Maximum results (default 20)
        repos: Repo filter — null for current repo, ["*"] for all repos
    """
    if search_type not in ("fts", "hybrid"):
        return runtime.error_payload(f"Invalid search_type '{search_type}'. Use 'fts' or 'hybrid'.")

    is_cross_repo = repos is not None
    if is_cross_repo:
        repo_names = runtime.normalize_repo_names(repos)
        from ...core.cross_repo import _for_each_repo
        from ...core.decisions import fts_search_decisions, hybrid_search_decisions

        def _query(conn, _repo):
            if search_type == "hybrid":
                return hybrid_search_decisions(conn, query, since=since, limit=limit)
            return fts_search_decisions(conn, query, since=since, limit=limit)

        cross_sort_key = "hybrid_score" if search_type == "hybrid" else "relevance_score"
        all_results, _warnings = _for_each_repo(_query, repos=repo_names, sort_key=cross_sort_key, limit=limit)
        formatted = _format_decision_results(all_results)
        return json.dumps({"decisions": formatted, "count": len(formatted), "retrieval_event_id": None})

    (conn, _), error = runtime.resolve_repo()
    if error:
        return error
    try:
        from ...core.decisions import fts_search_decisions, hybrid_search_decisions

        started_at = time.perf_counter()
        if search_type == "hybrid":
            results = hybrid_search_decisions(conn, query, since=since, limit=limit)
        else:
            results = fts_search_decisions(conn, query, since=since, limit=limit)

        tracked_event_id = runtime.record_search_event(
            conn,
            query=query,
            search_type=f"decision_{search_type}",
            target="decision",
            result_count=len(results),
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            since=since,
        )
        for idx, item in enumerate(results, start=1):
            runtime.record_selection(
                conn,
                retrieval_event_id=tracked_event_id,
                result_type="decision",
                result_id=item["id"],
                rank=idx,
            )
        formatted = _format_decision_results(results)
        return json.dumps(
            {
                "decisions": formatted,
                "count": len(formatted),
                "retrieval_event_id": tracked_event_id,
            }
        )
    except Exception as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len] + "…"


def _format_decision_results(results: list[dict]) -> list[dict]:
    formatted = []
    for r in results:
        entry: dict = {
            "id": r.get("id", ""),
            "title": r.get("title", ""),
            "rationale_excerpt": _truncate(r.get("rationale") or "", 200),
            "scope": r.get("scope", ""),
            "staleness_status": r.get("staleness_status", ""),
            "updated_at": r.get("updated_at", ""),
        }
        if "hybrid_score" in r:
            entry["hybrid_score"] = r["hybrid_score"]
        if "rank" in r:
            entry["rank"] = r["rank"]
        if "repo_name" in r:
            entry["repo_name"] = r["repo_name"]
        formatted.append(entry)
    return formatted


def register_tools(mcp, services=None) -> None:
    for tool in (
        ec_decision_get,
        ec_decision_related,
        ec_decision_outcome,
        ec_decision_create,
        ec_decision_list,
        ec_decision_stale,
        ec_decision_search,
    ):
        mcp.tool()(tool)
