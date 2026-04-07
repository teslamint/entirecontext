"""Search-oriented MCP tools."""

from __future__ import annotations

import json
import time

from .. import runtime


def _resolve_repo():
    try:
        return runtime.get_repo_db(), None
    except runtime.RepoResolutionError as exc:
        return (None, None), runtime.error_payload(str(exc))


async def ec_search(
    query: str,
    search_type: str = "regex",
    file_filter: str | None = None,
    commit_filter: str | None = None,
    agent_filter: str | None = None,
    since: str | None = None,
    limit: int = 20,
    repos: list[str] | None = None,
) -> str:
    is_cross_repo = repos is not None
    repo_names = runtime.normalize_repo_names(repos)

    if is_cross_repo:
        from ...core.cross_repo import cross_repo_search

        results = cross_repo_search(
            query,
            search_type=search_type,
            repos=repo_names,
            file_filter=file_filter,
            commit_filter=commit_filter,
            agent_filter=agent_filter,
            since=since,
            limit=limit,
        )
        retrieval_event_id = None
    else:
        (conn, repo_path), error = _resolve_repo()
        if error:
            return error

        try:
            from ...core.config import load_config

            config = load_config(repo_path)
            started_at = time.perf_counter()

            if search_type == "semantic":
                try:
                    from ...core.embedding import semantic_search
                    from ...core.search import _apply_query_redaction

                    results = semantic_search(
                        conn,
                        query,
                        file_filter=file_filter,
                        commit_filter=commit_filter,
                        agent_filter=agent_filter,
                        since=since,
                        limit=limit,
                    )
                    results = _apply_query_redaction(results, config)
                except ImportError as exc:
                    return runtime.error_payload(f"sentence-transformers is required: {exc}")
            elif search_type == "fts":
                from ...core.search import fts_search

                results = fts_search(
                    conn,
                    query,
                    file_filter=file_filter,
                    commit_filter=commit_filter,
                    agent_filter=agent_filter,
                    since=since,
                    limit=limit,
                    config=config,
                )
            elif search_type == "hybrid":
                from ...core.hybrid_search import hybrid_search

                results = hybrid_search(
                    conn,
                    query,
                    file_filter=file_filter,
                    commit_filter=commit_filter,
                    agent_filter=agent_filter,
                    since=since,
                    limit=limit,
                    config=config,
                )
            else:
                from ...core.search import regex_search

                results = regex_search(
                    conn,
                    query,
                    file_filter=file_filter,
                    commit_filter=commit_filter,
                    agent_filter=agent_filter,
                    since=since,
                    limit=limit,
                    config=config,
                )
            retrieval_event_id = runtime.record_search_event(
                conn,
                query=query,
                search_type=search_type,
                target="turn",
                result_count=len(results),
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                file_filter=file_filter,
                commit_filter=commit_filter,
                agent_filter=agent_filter,
                since=since,
            )
        finally:
            conn.close()

    formatted = []
    for result in results:
        entry = {
            "id": result.get("id", ""),
            "session_id": result.get("session_id", ""),
            "summary": result.get("assistant_summary") or result.get("user_message", ""),
            "timestamp": result.get("timestamp", ""),
        }
        if "hybrid_score" in result:
            entry["hybrid_score"] = result["hybrid_score"]
        if is_cross_repo:
            entry["repo_name"] = result.get("repo_name", "")
            entry["repo_path"] = result.get("repo_path", "")
        formatted.append(entry)
    payload = {"results": formatted, "count": len(formatted), "retrieval_event_id": retrieval_event_id}
    if is_cross_repo:
        payload["telemetry_skipped"] = "cross_repo"
    return json.dumps(payload)


async def ec_related(
    query: str | None = None,
    files: list[str] | None = None,
    limit: int = 20,
    repos: list[str] | None = None,
) -> str:
    if repos is not None:
        from ...core.cross_repo import cross_repo_related

        results, warnings = cross_repo_related(
            query=query,
            files=files,
            repos=runtime.normalize_repo_names(repos),
            limit=limit,
            include_warnings=True,
        )
        related = [
            {
                "type": "turn",
                "id": result.get("id", ""),
                "session_id": result.get("session_id", ""),
                "summary": result.get("assistant_summary") or result.get("user_message", ""),
                "timestamp": result.get("timestamp", ""),
                "repo_name": result.get("repo_name", ""),
                "repo_path": result.get("repo_path", ""),
            }
            for result in results
        ]
        return json.dumps({"related": related, "count": len(related), "warnings": warnings})

    (conn, _), error = _resolve_repo()
    if error:
        return error

    try:
        results = []
        if query:
            from ...core.search import regex_search

            for result in regex_search(conn, query, limit=10):
                results.append(
                    {
                        "type": "turn",
                        "id": result.get("id", ""),
                        "session_id": result.get("session_id", ""),
                        "summary": result.get("assistant_summary") or result.get("user_message", ""),
                        "timestamp": result.get("timestamp", ""),
                        "relevance": "query_match",
                    }
                )
        if files:
            for file_path in files[:5]:
                rows = conn.execute(
                    "SELECT id, session_id, user_message, assistant_summary, timestamp FROM turns WHERE files_touched LIKE ? ORDER BY timestamp DESC LIMIT 5",
                    (f"%{file_path}%",),
                ).fetchall()
                for row in rows:
                    results.append(
                        {
                            "type": "turn",
                            "id": row["id"],
                            "session_id": row["session_id"],
                            "summary": row["assistant_summary"] or row["user_message"] or "",
                            "timestamp": row["timestamp"],
                            "relevance": f"file:{file_path}",
                        }
                    )
        seen = set()
        unique_results = []
        for result in results:
            if result["id"] in seen:
                continue
            seen.add(result["id"])
            unique_results.append(result)
        return json.dumps({"related": unique_results[:limit], "count": len(unique_results[:limit])})
    finally:
        conn.close()


async def ec_ast_search(
    query: str,
    symbol_type: str | None = None,
    file_filter: str | None = None,
    limit: int = 20,
) -> str:
    (conn, _), error = _resolve_repo()
    if error:
        return error

    try:
        from ...core.ast_index import search_ast_symbols

        results = search_ast_symbols(conn, query, symbol_type=symbol_type, file_filter=file_filter, limit=limit)
        return json.dumps({"results": results, "count": len(results)})
    finally:
        conn.close()


async def ec_activate(
    seed_turn_id: str | None = None,
    seed_session_id: str | None = None,
    max_hops: int = 2,
    limit: int = 20,
    decay: float = 0.5,
) -> str:
    if not seed_turn_id and not seed_session_id:
        return runtime.error_payload("Either seed_turn_id or seed_session_id is required")

    (conn, _), error = _resolve_repo()
    if error:
        return error

    try:
        from ...core.activation import spread_activation

        results = spread_activation(
            conn,
            seed_turn_id=seed_turn_id,
            seed_session_id=seed_session_id,
            max_hops=max_hops,
            limit=limit,
            decay=decay,
        )
        return json.dumps({"results": results, "count": len(results)})
    finally:
        conn.close()


def register_tools(mcp, services=None) -> None:
    for tool in (ec_search, ec_related, ec_ast_search, ec_activate):
        mcp.tool()(tool)
