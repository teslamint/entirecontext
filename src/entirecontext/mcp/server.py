"""MCP server for EntireContext — agent-facing search and context tools."""

from __future__ import annotations

from ..core.context import RepoContext

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None

if FastMCP:
    mcp = FastMCP("entirecontext")
else:
    mcp = None


def _get_repo_db():
    context = RepoContext.from_cwd(require_project=True)
    if not context:
        return None, None
    return context.conn, context.repo_path


def _detect_current_session(conn) -> str | None:
    row = conn.execute(
        "SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY last_activity_at DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


def _record_search_event(
    conn,
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
) -> str:
    from ..core.telemetry import detect_current_context, record_retrieval_event

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
    return event["id"]


def _record_selection(
    conn,
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
    return selection["id"]


from .tools.checkpoint import ec_checkpoint_list, ec_rewind  # noqa: E402
from .tools.decisions import ec_decision_get, ec_decision_outcome, ec_decision_related  # noqa: E402
from .tools.futures import ec_assess, ec_assess_create, ec_assess_trends, ec_feedback, ec_lessons  # noqa: E402
from .tools.misc import ec_dashboard, ec_graph  # noqa: E402
from .tools.search import ec_activate, ec_ast_search, ec_related, ec_search  # noqa: E402
from .tools.session import ec_attribution, ec_context_apply, ec_session_context, ec_turn_content  # noqa: E402

if mcp:
    from .runtime import ServiceRegistry
    from .tools import checkpoint, decisions, futures, misc, search, session

    _services = ServiceRegistry()
    for module in (search, checkpoint, session, futures, misc, decisions):
        module.register_tools(mcp, _services)


def run_server():
    """Run the MCP server (stdio transport)."""
    if mcp is None:
        print("MCP not available. Install with: pip install 'entirecontext[mcp]'")
        return
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
    "ec_decision_get",
    "ec_decision_outcome",
    "ec_decision_related",
    "run_server",
]
