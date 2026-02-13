"""Cross-repo search orchestrator — queries multiple per-repo DBs via global index."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def list_repos(names: list[str] | None = None) -> list[dict]:
    """Return registered repos from global DB. Filter by names if given. Skip missing db_path."""
    from ..db import get_global_db
    from ..db.global_schema import init_global_schema

    gconn = get_global_db()
    init_global_schema(gconn)

    rows = gconn.execute("SELECT * FROM repo_index ORDER BY repo_name").fetchall()
    gconn.close()

    repos = []
    for row in rows:
        r = dict(row)
        if not Path(r["db_path"]).exists():
            continue
        if names and r["repo_name"] not in names:
            continue
        repos.append(r)
    return repos


def cross_repo_search(
    query: str,
    search_type: str = "regex",
    target: str = "turn",
    repos: list[str] | None = None,
    file_filter: str | None = None,
    commit_filter: str | None = None,
    agent_filter: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search across multiple repos.

    1. list_repos(repos)
    2. Each repo: open DB -> regex_search()/fts_search() (per-repo limit = limit*2)
    3. Inject repo_name/repo_path into results
    4. Sort by timestamp DESC -> apply limit
    """
    from ..db.connection import _configure_connection
    from ..db.migration import check_and_migrate
    from ..core.search import regex_search, fts_search
    import sqlite3

    repo_list = list_repos(repos)
    all_results: list[dict] = []
    per_repo_limit = limit * 2

    for repo in repo_list:
        try:
            conn = sqlite3.connect(repo["db_path"])
            _configure_connection(conn)
            check_and_migrate(conn)

            if search_type == "fts":
                results = fts_search(
                    conn,
                    query,
                    target=target,
                    file_filter=file_filter,
                    commit_filter=commit_filter,
                    agent_filter=agent_filter,
                    since=since,
                    limit=per_repo_limit,
                )
            else:
                results = regex_search(
                    conn,
                    query,
                    target=target,
                    file_filter=file_filter,
                    commit_filter=commit_filter,
                    agent_filter=agent_filter,
                    since=since,
                    limit=per_repo_limit,
                )

            conn.close()

            for r in results:
                r["repo_name"] = repo["repo_name"]
                r["repo_path"] = repo["repo_path"]
            all_results.extend(results)
        except Exception:
            logger.debug("Skipping repo %s: access error", repo["repo_path"], exc_info=True)
            continue

    sort_key = _sort_key_for_target(target)
    all_results.sort(key=lambda r: r.get(sort_key, ""), reverse=True)
    return all_results[:limit]


def cross_repo_sessions(
    repos: list[str] | None = None,
    limit: int = 20,
    include_ended: bool = True,
) -> list[dict]:
    """List sessions across multiple repos, merged by last_activity_at DESC."""
    from ..db.connection import _configure_connection
    from ..db.migration import check_and_migrate
    from ..core.session import list_sessions
    import sqlite3

    repo_list = list_repos(repos)
    all_sessions: list[dict] = []

    for repo in repo_list:
        try:
            conn = sqlite3.connect(repo["db_path"])
            _configure_connection(conn)
            check_and_migrate(conn)

            sessions = list_sessions(conn, limit=limit, include_ended=include_ended)
            conn.close()

            for s in sessions:
                s["repo_name"] = repo["repo_name"]
                s["repo_path"] = repo["repo_path"]
            all_sessions.extend(sessions)
        except Exception:
            logger.debug("Skipping repo %s: access error", repo["repo_path"], exc_info=True)
            continue

    all_sessions.sort(key=lambda s: s.get("last_activity_at", ""), reverse=True)
    return all_sessions[:limit]


def _sort_key_for_target(target: str) -> str:
    if target == "turn":
        return "timestamp"
    elif target == "session":
        return "last_activity_at"
    elif target == "event":
        return "created_at"
    return "timestamp"
