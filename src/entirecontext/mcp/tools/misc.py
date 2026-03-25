"""Miscellaneous MCP tools."""

from __future__ import annotations

import json

from .. import runtime


async def ec_graph(session_id: str | None = None, since: str | None = None, limit: int = 200) -> str:
    conn, _ = runtime.get_repo_db()
    if not conn:
        return runtime.error_payload("Not in an EntireContext-initialized repo")
    try:
        from ...core.knowledge_graph import build_knowledge_graph, get_graph_stats

        graph = build_knowledge_graph(conn, session_id=session_id, since=since, limit=limit)
        stats = get_graph_stats(graph)
        return json.dumps({"nodes": graph["nodes"], "edges": graph["edges"], "stats": stats})
    finally:
        conn.close()


async def ec_dashboard(since: str | None = None, limit: int = 10) -> str:
    conn, _ = runtime.get_repo_db()
    if not conn:
        return runtime.error_payload("Not in an EntireContext-initialized repo")
    try:
        from ...core.dashboard import get_dashboard_stats

        stats = get_dashboard_stats(conn, since=since, limit=limit)
        return json.dumps(stats)
    finally:
        conn.close()


def register_tools(mcp, services=None) -> None:
    for tool in (ec_graph, ec_dashboard):
        mcp.tool()(tool)
