"""Cross-repo search orchestrator — queries multiple per-repo DBs via global index."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Callable

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


def _lazy_pull_repos(repo_list: list[dict]) -> None:
    """Pull stale repos before cross-repo query if auto_pull is enabled."""
    from ..core.config import load_config

    try:
        config = load_config()
        if not config.get("sync", {}).get("auto_pull", False):
            return
        from ..sync.auto_sync import run_pull, should_pull

        for repo in repo_list:
            try:
                from ..db.connection import _configure_connection

                conn = sqlite3.connect(repo["db_path"])
                _configure_connection(conn)
                repo_config = load_config(repo["repo_path"]).get("sync", {})
                if should_pull(conn, repo_config):
                    conn.close()
                    run_pull(repo["repo_path"])
                else:
                    conn.close()
            except Exception:
                logger.debug("Lazy pull skipped for %s", repo.get("repo_path"), exc_info=True)
    except Exception:
        logger.debug("Lazy pull setup failed", exc_info=True)


def _for_each_repo(
    fn: Callable[[sqlite3.Connection, dict], list[dict]],
    repos: list[str] | None = None,
    sort_key: str | None = None,
    limit: int = 20,
) -> tuple[list[dict], list[str]]:
    """Execute fn against each repo DB, merge results.

    fn: callable(conn, repo_info) -> list[dict]
    Returns: (results, warnings) tuple
    """
    from ..db.connection import _configure_connection
    from ..db.migration import check_and_migrate

    repo_list = list_repos(repos)
    _lazy_pull_repos(repo_list)
    all_results: list[dict] = []
    warnings: list[str] = []

    for repo in repo_list:
        try:
            conn = sqlite3.connect(repo["db_path"])
            _configure_connection(conn)
            check_and_migrate(conn)

            results = fn(conn, repo)
            conn.close()

            for r in results:
                r["repo_name"] = repo["repo_name"]
                r["repo_path"] = repo["repo_path"]
            all_results.extend(results)
        except Exception as exc:
            warnings.append(f"Repo '{repo.get('repo_name', repo.get('repo_path', '?'))}': {exc}")
            logger.debug("Skipping repo %s: access error", repo.get("repo_path"), exc_info=True)
            continue

    if sort_key:
        all_results.sort(key=lambda r: r.get(sort_key, ""), reverse=True)

    all_results = all_results[:limit]
    return all_results, warnings


def _return_with_warnings(results: list[dict], warnings: list[str], include_warnings: bool) -> Any:
    """Return results with or without warnings based on flag."""
    if include_warnings:
        return results, warnings
    return results


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
    include_warnings: bool = False,
) -> list[dict] | tuple[list[dict], list[str]]:
    """Search across multiple repos."""
    from ..core.search import fts_search, regex_search

    def fn(conn: sqlite3.Connection, repo: dict) -> list[dict]:
        per_repo_limit = limit * 2
        if search_type == "fts":
            return fts_search(
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
            return regex_search(
                conn,
                query,
                target=target,
                file_filter=file_filter,
                commit_filter=commit_filter,
                agent_filter=agent_filter,
                since=since,
                limit=per_repo_limit,
            )

    sort_key = _sort_key_for_target(target)
    results, warnings = _for_each_repo(fn, repos=repos, sort_key=sort_key, limit=limit)
    return _return_with_warnings(results, warnings, include_warnings)


def cross_repo_sessions(
    repos: list[str] | None = None,
    limit: int = 20,
    include_ended: bool = True,
    include_warnings: bool = False,
) -> list[dict] | tuple[list[dict], list[str]]:
    """List sessions across multiple repos, merged by last_activity_at DESC."""
    from ..core.session import list_sessions

    def fn(conn: sqlite3.Connection, repo: dict) -> list[dict]:
        return list_sessions(conn, limit=limit, include_ended=include_ended)

    results, warnings = _for_each_repo(fn, repos=repos, sort_key="last_activity_at", limit=limit)
    return _return_with_warnings(results, warnings, include_warnings)


def cross_repo_checkpoints(
    repos: list[str] | None = None,
    session_id: str | None = None,
    since: str | None = None,
    limit: int = 20,
    include_warnings: bool = False,
) -> list[dict] | tuple[list[dict], list[str]]:
    """List checkpoints across multiple repos."""
    from ..core.checkpoint import list_checkpoints

    def fn(conn: sqlite3.Connection, repo: dict) -> list[dict]:
        results = list_checkpoints(conn, session_id=session_id, limit=limit * 2)
        if since:
            results = [r for r in results if r.get("created_at", "") >= since]
        return results

    results, warnings = _for_each_repo(fn, repos=repos, sort_key="created_at", limit=limit)
    return _return_with_warnings(results, warnings, include_warnings)


def cross_repo_session_detail(
    session_id: str,
    repos: list[str] | None = None,
    include_warnings: bool = False,
) -> dict | None | tuple[dict | None, list[str]]:
    """Find a session by ID across repos, returning session with turns attached."""
    from ..core.session import get_session
    from ..core.turn import list_turns

    def fn(conn: sqlite3.Connection, repo: dict) -> list[dict]:
        session = get_session(conn, session_id)
        if session:
            turns = list_turns(conn, session_id, limit=10)
            session["turns"] = turns
            return [session]
        return []

    results, warnings = _for_each_repo(fn, repos=repos, limit=1)
    result = results[0] if results else None
    if include_warnings:
        return result, warnings
    return result


def cross_repo_events(
    repos: list[str] | None = None,
    status: str | None = None,
    event_type: str | None = None,
    limit: int = 20,
    include_warnings: bool = False,
) -> list[dict] | tuple[list[dict], list[str]]:
    """List events across multiple repos."""
    from ..core.event import list_events

    def fn(conn: sqlite3.Connection, repo: dict) -> list[dict]:
        return list_events(conn, status=status, event_type=event_type, limit=limit * 2)

    results, warnings = _for_each_repo(fn, repos=repos, sort_key="created_at", limit=limit)
    return _return_with_warnings(results, warnings, include_warnings)


def cross_repo_attribution(
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    repos: list[str] | None = None,
    include_warnings: bool = False,
) -> list[dict] | tuple[list[dict], list[str]]:
    """Get file attributions across multiple repos."""
    from ..core.attribution import get_file_attributions

    def fn(conn: sqlite3.Connection, repo: dict) -> list[dict]:
        return get_file_attributions(conn, file_path, start_line, end_line)

    results, warnings = _for_each_repo(fn, repos=repos)
    return _return_with_warnings(results, warnings, include_warnings)


def cross_repo_related(
    query: str | None = None,
    files: list[str] | None = None,
    repos: list[str] | None = None,
    limit: int = 20,
    include_warnings: bool = False,
) -> list[dict] | tuple[list[dict], list[str]]:
    """Find related sessions/turns across repos by query or file patterns."""
    from ..core.search import fts_search, regex_search

    def fn(conn: sqlite3.Connection, repo: dict) -> list[dict]:
        results: list[dict] = []
        if query:
            results.extend(fts_search(conn, query, target="turn", limit=limit * 2))
        if files:
            for file_pattern in files:
                results.extend(
                    regex_search(conn, file_pattern, target="turn", file_filter=file_pattern, limit=limit * 2)
                )
        return results

    sort_key = "timestamp"
    results, warnings = _for_each_repo(fn, repos=repos, sort_key=sort_key, limit=limit)
    return _return_with_warnings(results, warnings, include_warnings)


def cross_repo_rewind(
    checkpoint_id: str,
    repos: list[str] | None = None,
    include_warnings: bool = False,
) -> dict | None | tuple[dict | None, list[str]]:
    """Find a checkpoint by ID across repos (returns first found)."""
    from ..db.connection import _configure_connection
    from ..db.migration import check_and_migrate
    from ..core.checkpoint import get_checkpoint

    repo_list = list_repos(repos)
    warnings: list[str] = []

    for repo in repo_list:
        try:
            conn = sqlite3.connect(repo["db_path"])
            _configure_connection(conn)
            check_and_migrate(conn)

            checkpoint = get_checkpoint(conn, checkpoint_id)
            conn.close()

            if checkpoint:
                checkpoint["repo_name"] = repo["repo_name"]
                checkpoint["repo_path"] = repo["repo_path"]
                if include_warnings:
                    return checkpoint, warnings
                return checkpoint
        except Exception as exc:
            warnings.append(f"Repo '{repo.get('repo_name', repo.get('repo_path', '?'))}': {exc}")
            logger.debug("Skipping repo %s: access error", repo.get("repo_path"), exc_info=True)
            continue

    if include_warnings:
        return None, warnings
    return None


def cross_repo_turn_content(
    turn_id: str,
    repos: list[str] | None = None,
    include_warnings: bool = False,
) -> dict | None | tuple[dict | None, list[str]]:
    """Find a turn by ID across repos and read its content file."""
    from ..db.connection import _configure_connection
    from ..db.migration import check_and_migrate
    from ..core.turn import get_turn

    repo_list = list_repos(repos)
    warnings: list[str] = []

    for repo in repo_list:
        try:
            conn = sqlite3.connect(repo["db_path"])
            _configure_connection(conn)
            check_and_migrate(conn)

            turn = get_turn(conn, turn_id)
            if turn:
                content_row = conn.execute(
                    "SELECT content_path FROM turn_content WHERE turn_id = ?", (turn_id,)
                ).fetchone()
                conn.close()

                if content_row:
                    content_path = resolve_content_path(repo["repo_path"], content_row["content_path"])
                    if content_path.exists():
                        turn["content"] = content_path.read_text(encoding="utf-8")
                    else:
                        turn["content"] = None
                    turn["content_path"] = str(content_row["content_path"])
                else:
                    turn["content"] = None

                turn["repo_name"] = repo["repo_name"]
                turn["repo_path"] = repo["repo_path"]
                if include_warnings:
                    return turn, warnings
                return turn
            else:
                conn.close()
        except Exception as exc:
            warnings.append(f"Repo '{repo.get('repo_name', repo.get('repo_path', '?'))}': {exc}")
            logger.debug("Skipping repo %s: access error", repo.get("repo_path"), exc_info=True)
            continue

    if include_warnings:
        return None, warnings
    return None


def resolve_content_path(repo_path: str, content_path: str) -> Path:
    """Resolve a relative content path to an absolute path within the repo's .entirecontext dir."""
    return Path(repo_path) / ".entirecontext" / content_path


def _sort_key_for_target(target: str) -> str:
    if target == "turn":
        return "timestamp"
    elif target == "session":
        return "last_activity_at"
    elif target == "event":
        return "created_at"
    return "timestamp"
