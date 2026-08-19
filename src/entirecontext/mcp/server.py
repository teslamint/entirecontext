"""MCP server for EntireContext — agent-facing search and context tools."""

from __future__ import annotations

import sqlite3
from typing import Any

# Declared before the import so the ImportError fallback is an assignment to an
# existing name rather than a redefinition of the imported class.
FastMCP: Any
_FASTMCP_IMPORT_ERROR: ImportError | None = None
try:
    from mcp.server.fastmcp import FastMCP as _FastMCP

    FastMCP = _FastMCP
except ImportError as exc:
    FastMCP = None
    _FASTMCP_IMPORT_ERROR = exc

mcp: Any = FastMCP("entirecontext") if FastMCP is not None else None


def _get_repo_db() -> tuple[sqlite3.Connection, str]:
    from . import runtime

    return runtime.get_repo_db()


def _detect_current_session(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY last_activity_at DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


def _record_search_event(
    conn: sqlite3.Connection,
    *,
    query: str,
    search_type: str,
    target: str,
    result_count: int,
    latency_ms: int,
    file_filter: str | None = None,
    commit_filter: str | None = None,
    agent_filter: str | None = None,
    since: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> str:
    from ..core.telemetry import detect_current_context, record_retrieval_event

    # Fall back to auto-detection only when the caller has not supplied an
    # explicit session/turn. MCP tools that honor a caller-provided
    # ``session_id`` override (e.g. ``ec_decision_context``) must be able
    # to anchor their telemetry to that exact session, not whatever the
    # connection's currently active session happens to be.
    if session_id is None and turn_id is None:
        session_id, turn_id = detect_current_context(conn)
    event = record_retrieval_event(
        conn,
        source="mcp",
        search_type=search_type,
        target=target,
        query=query,
        result_count=result_count,
        latency_ms=latency_ms,
        session_id=session_id,
        turn_id=turn_id,
        file_filter=file_filter,
        commit_filter=commit_filter,
        agent_filter=agent_filter,
        since_filter=since,
    )
    event_id: str = event["id"]
    return event_id


def _record_selection(
    conn: sqlite3.Connection,
    *,
    retrieval_event_id: str | None,
    result_type: str,
    result_id: str,
    rank: int = 1,
) -> str | None:
    if not retrieval_event_id:
        return None

    from ..core.telemetry import record_retrieval_selection

    selection = record_retrieval_selection(
        conn,
        retrieval_event_id,
        result_type,
        result_id,
        rank=rank,
    )
    selection_id: str = selection["id"]
    return selection_id


from .tools.checkpoint import ec_checkpoint_list, ec_rewind  # noqa: E402
from .tools.decision_candidates import (  # noqa: E402
    ec_decision_candidate_confirm,
    ec_decision_candidate_get,
    ec_decision_candidate_list,
    ec_decision_candidate_reject,
)
from .tools.decisions import (  # noqa: E402
    ec_decision_context,
    ec_decision_create,
    ec_decision_get,
    ec_decision_list,
    ec_decision_outcome,
    ec_decision_related,
    ec_decision_search,
    ec_decision_stale,
)
from .tools.futures import ec_assess, ec_assess_create, ec_assess_trends, ec_feedback, ec_lessons  # noqa: E402
from .tools.misc import ec_dashboard, ec_graph  # noqa: E402
from .tools.search import ec_activate, ec_ast_search, ec_related, ec_search  # noqa: E402
from .tools.session import ec_attribution, ec_context_apply, ec_session_context, ec_turn_content  # noqa: E402

if mcp:
    from .runtime import ServiceRegistry
    from .tools import checkpoint, decision_candidates, decisions, futures, misc, search, session

    _services = ServiceRegistry()
    for module in (search, checkpoint, session, futures, misc, decisions, decision_candidates):
        module.register_tools(mcp, _services)


def run_server() -> None:
    """Run the MCP server (stdio transport)."""
    if mcp is None:
        # Keep the original ImportError, if any, in the chain for accurate
        # diagnosis. Raising (instead of print+return) gives a non-zero exit
        # code and keeps stdout clean of non-JSON-RPC text.
        raise RuntimeError(
            "MCP SDK unavailable: 'from mcp.server.fastmcp import FastMCP' failed. "
            "Install the extra: uv tool install --force 'entirecontext[mcp] @ <repo path>'"
        ) from _FASTMCP_IMPORT_ERROR
    import sys
    from entirecontext import __version__

    print(f"[ec-mcp] starting v{__version__}", file=sys.stderr, flush=True)
    mcp.run()


__all__ = [
    "ec_search",
    "ec_related",
    "ec_ast_search",
    "ec_activate",
    "ec_checkpoint_list",
    "ec_rewind",
    "ec_session_context",
    "ec_turn_content",
    "ec_attribution",
    "ec_context_apply",
    "ec_assess",
    "ec_assess_create",
    "ec_assess_trends",
    "ec_feedback",
    "ec_lessons",
    "ec_dashboard",
    "ec_graph",
    "ec_decision_context",
    "ec_decision_create",
    "ec_decision_get",
    "ec_decision_list",
    "ec_decision_outcome",
    "ec_decision_related",
    "ec_decision_search",
    "ec_decision_stale",
    "ec_decision_candidate_list",
    "ec_decision_candidate_get",
    "ec_decision_candidate_confirm",
    "ec_decision_candidate_reject",
    "run_server",
]
