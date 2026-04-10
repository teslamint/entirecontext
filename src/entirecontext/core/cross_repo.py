"""Cross-repo search orchestrator — queries multiple per-repo DBs via global index."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Callable

from .context import GlobalContext

logger = logging.getLogger(__name__)

WarningEntry = dict[str, str]


class RepoRegistry:
    def list_repos(self, names: list[str] | None = None) -> list[dict]:
        with GlobalContext.create() as context:
            repos = []
            for repo in context.list_registered_repos(names):
                if not Path(repo["db_path"]).exists():
                    continue
                repos.append(repo)
            return repos


class CrossRepoPolicy:
    SORT_KEYS = {
        "turn": "timestamp",
        "session": "last_activity_at",
        "event": "created_at",
        "checkpoint": "created_at",
        "semantic": "score",
        "hybrid": "hybrid_score",
    }

    def warning(self, repo: dict, phase: str, exc: Exception) -> WarningEntry:
        return {
            "repo_name": repo.get("repo_name", repo.get("repo_path", "?")),
            "phase": phase,
            "error": str(exc),
        }

    def lazy_pull_repos(self, repo_list: list[dict]) -> None:
        from ..core.config import load_config

        try:
            config = load_config()
            if not config.get("sync", {}).get("auto_pull", False):
                return
            from ..sync.auto_sync import run_pull, should_pull
            from ..db.connection import _configure_connection

            for repo in repo_list:
                try:
                    conn = sqlite3.connect(repo["db_path"])
                    _configure_connection(conn)
                    repo_config = load_config(repo["repo_path"]).get("sync", {})
                    if should_pull(conn, repo_config):
                        conn.close()
                        run_pull(repo["repo_path"])
                    else:
                        conn.close()
                except Exception as exc:
                    logger.debug("Lazy pull skipped for %s: %s", repo.get("repo_path"), exc, exc_info=True)
        except Exception as exc:
            logger.debug("Lazy pull setup failed: %s", exc, exc_info=True)

    def sort_and_limit(self, results: list[dict], *, sort_key: str | None, limit: int) -> list[dict]:
        if sort_key:
            results.sort(key=lambda row: row.get(sort_key, ""), reverse=True)
        return results[:limit]


class RepoExecutor:
    def __init__(self, *, registry: RepoRegistry | None = None, policy: CrossRepoPolicy | None = None):
        self.registry = registry or RepoRegistry()
        self.policy = policy or CrossRepoPolicy()

    def execute(
        self,
        fn: Callable[[sqlite3.Connection, dict], list[dict]],
        *,
        repos: list[str] | None = None,
        sort_key: str | None = None,
        limit: int = 20,
    ) -> tuple[list[dict], list[WarningEntry]]:
        from ..db.connection import _configure_connection
        from ..db.migration import check_and_migrate

        repo_list = self.registry.list_repos(repos)
        self.policy.lazy_pull_repos(repo_list)
        all_results: list[dict] = []
        warnings: list[WarningEntry] = []

        for repo in repo_list:
            try:
                conn = sqlite3.connect(repo["db_path"])
                _configure_connection(conn)
                check_and_migrate(conn)
                results = fn(conn, repo)
                conn.close()

                for result in results:
                    result["repo_name"] = repo["repo_name"]
                    result["repo_path"] = repo["repo_path"]
                all_results.extend(results)
            except Exception as exc:
                warnings.append(self.policy.warning(repo, "query", exc))
                logger.debug("Skipping repo %s", repo.get("repo_path"), exc_info=True)

        return self.policy.sort_and_limit(all_results, sort_key=sort_key, limit=limit), warnings

    def first(
        self,
        fn: Callable[[sqlite3.Connection, dict], dict | None],
        *,
        repos: list[str] | None = None,
    ) -> tuple[dict | None, list[WarningEntry]]:
        from ..db.connection import _configure_connection
        from ..db.migration import check_and_migrate

        repo_list = self.registry.list_repos(repos)
        self.policy.lazy_pull_repos(repo_list)
        warnings: list[WarningEntry] = []

        for repo in repo_list:
            try:
                conn = sqlite3.connect(repo["db_path"])
                _configure_connection(conn)
                check_and_migrate(conn)
                result = fn(conn, repo)
                conn.close()
                if result:
                    result["repo_name"] = repo["repo_name"]
                    result["repo_path"] = repo["repo_path"]
                    return result, warnings
            except Exception as exc:
                warnings.append(self.policy.warning(repo, "query", exc))
                logger.debug("Skipping repo %s", repo.get("repo_path"), exc_info=True)

        return None, warnings


def list_repos(names: list[str] | None = None) -> list[dict]:
    return RepoRegistry().list_repos(names)


def _lazy_pull_repos(repo_list: list[dict]) -> None:
    CrossRepoPolicy().lazy_pull_repos(repo_list)


def _for_each_repo(
    fn: Callable[[sqlite3.Connection, dict], list[dict]],
    repos: list[str] | None = None,
    sort_key: str | None = None,
    limit: int = 20,
) -> tuple[list[dict], list[WarningEntry]]:
    return RepoExecutor().execute(fn, repos=repos, sort_key=sort_key, limit=limit)


def _return_with_warnings(results: list[dict], warnings: list[WarningEntry], include_warnings: bool) -> Any:
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
) -> list[dict] | tuple[list[dict], list[WarningEntry]]:
    from ..core.search import fts_search, regex_search

    def fn(conn: sqlite3.Connection, repo: dict) -> list[dict]:
        per_repo_limit = limit * 2
        if search_type == "semantic":
            from ..core.embedding import semantic_search

            return semantic_search(
                conn,
                query,
                file_filter=file_filter,
                commit_filter=commit_filter,
                agent_filter=agent_filter,
                since=since,
                limit=per_repo_limit,
            )
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
        if search_type == "hybrid":
            from ..core.hybrid_search import hybrid_search

            return hybrid_search(
                conn,
                query,
                target=target,
                file_filter=file_filter,
                commit_filter=commit_filter,
                agent_filter=agent_filter,
                since=since,
                limit=per_repo_limit,
            )
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

    policy = CrossRepoPolicy()
    if search_type == "hybrid":
        sort_key = policy.SORT_KEYS["hybrid"]
    elif search_type == "semantic":
        sort_key = policy.SORT_KEYS["semantic"]
    else:
        sort_key = _sort_key_for_target(target)
    results, warnings = RepoExecutor(policy=policy).execute(fn, repos=repos, sort_key=sort_key, limit=limit)
    return _return_with_warnings(results, warnings, include_warnings)


def cross_repo_sessions(
    repos: list[str] | None = None,
    limit: int = 20,
    include_ended: bool = True,
    include_warnings: bool = False,
) -> list[dict] | tuple[list[dict], list[WarningEntry]]:
    from ..core.session import list_sessions

    def fn(conn: sqlite3.Connection, repo: dict) -> list[dict]:
        return list_sessions(conn, limit=limit, include_ended=include_ended)

    results, warnings = RepoExecutor().execute(fn, repos=repos, sort_key="last_activity_at", limit=limit)
    return _return_with_warnings(results, warnings, include_warnings)


def cross_repo_checkpoints(
    repos: list[str] | None = None,
    session_id: str | None = None,
    since: str | None = None,
    limit: int = 20,
    include_warnings: bool = False,
) -> list[dict] | tuple[list[dict], list[WarningEntry]]:
    from ..core.checkpoint import list_checkpoints

    def fn(conn: sqlite3.Connection, repo: dict) -> list[dict]:
        results = list_checkpoints(conn, session_id=session_id, limit=limit * 2)
        if since:
            results = [row for row in results if row.get("created_at", "") >= since]
        return results

    results, warnings = RepoExecutor().execute(fn, repos=repos, sort_key="created_at", limit=limit)
    return _return_with_warnings(results, warnings, include_warnings)


def cross_repo_session_detail(
    session_id: str,
    repos: list[str] | None = None,
    include_warnings: bool = False,
) -> dict | None | tuple[dict | None, list[WarningEntry]]:
    from ..core.session import get_session
    from ..core.turn import list_turns

    def fn(conn: sqlite3.Connection, repo: dict) -> dict | None:
        session = get_session(conn, session_id)
        if not session:
            return None
        session["turns"] = list_turns(conn, session_id, limit=10)
        return session

    result, warnings = RepoExecutor().first(fn, repos=repos)
    if include_warnings:
        return result, warnings
    return result


def cross_repo_events(
    repos: list[str] | None = None,
    status: str | None = None,
    event_type: str | None = None,
    limit: int = 20,
    include_warnings: bool = False,
) -> list[dict] | tuple[list[dict], list[WarningEntry]]:
    from ..core.event import list_events

    def fn(conn: sqlite3.Connection, repo: dict) -> list[dict]:
        return list_events(conn, status=status, event_type=event_type, limit=limit * 2)

    results, warnings = RepoExecutor().execute(fn, repos=repos, sort_key="created_at", limit=limit)
    return _return_with_warnings(results, warnings, include_warnings)


def cross_repo_attribution(
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    repos: list[str] | None = None,
    include_warnings: bool = False,
) -> list[dict] | tuple[list[dict], list[WarningEntry]]:
    from ..core.attribution import get_file_attributions

    def fn(conn: sqlite3.Connection, repo: dict) -> list[dict]:
        return get_file_attributions(conn, file_path, start_line, end_line)

    results, warnings = RepoExecutor().execute(fn, repos=repos, limit=20)
    return _return_with_warnings(results, warnings, include_warnings)


def cross_repo_related(
    query: str | None = None,
    files: list[str] | None = None,
    repos: list[str] | None = None,
    limit: int = 20,
    include_warnings: bool = False,
) -> list[dict] | tuple[list[dict], list[WarningEntry]]:
    from ..core.search import fts_search, regex_search

    def fn(conn: sqlite3.Connection, repo: dict) -> list[dict]:
        results: list[dict] = []
        if query:
            results.extend(fts_search(conn, query, target="turn", limit=limit * 2))
        if files:
            for file_pattern in files:
                results.extend(regex_search(conn, file_pattern, target="turn", file_filter=file_pattern, limit=limit * 2))
        return results

    results, warnings = RepoExecutor().execute(fn, repos=repos, sort_key="timestamp", limit=limit)
    return _return_with_warnings(results, warnings, include_warnings)


def cross_repo_rewind(
    checkpoint_id: str,
    repos: list[str] | None = None,
    include_warnings: bool = False,
) -> dict | None | tuple[dict | None, list[WarningEntry]]:
    from ..core.checkpoint import get_checkpoint

    def fn(conn: sqlite3.Connection, repo: dict) -> dict | None:
        return get_checkpoint(conn, checkpoint_id)

    result, warnings = RepoExecutor().first(fn, repos=repos)
    if include_warnings:
        return result, warnings
    return result


def cross_repo_turn_content(
    turn_id: str,
    repos: list[str] | None = None,
    include_warnings: bool = False,
) -> dict | None | tuple[dict | None, list[WarningEntry]]:
    from ..core.turn import get_turn

    def fn(conn: sqlite3.Connection, repo: dict) -> dict | None:
        turn = get_turn(conn, turn_id)
        if not turn:
            return None
        content_row = conn.execute("SELECT content_path FROM turn_content WHERE turn_id = ?", (turn_id,)).fetchone()
        if content_row:
            content_path = resolve_content_path(repo["repo_path"], content_row["content_path"])
            turn["content"] = content_path.read_text(encoding="utf-8") if content_path.exists() else None
            turn["content_path"] = str(content_row["content_path"])
        else:
            turn["content"] = None
        return turn

    result, warnings = RepoExecutor().first(fn, repos=repos)
    if include_warnings:
        return result, warnings
    return result


def resolve_content_path(repo_path: str, content_path: str) -> Path:
    return Path(repo_path) / ".entirecontext" / content_path


def cross_repo_assessments(
    repos: list[str] | None = None,
    verdict: str | None = None,
    since: str | None = None,
    limit: int = 50,
    include_warnings: bool = False,
) -> list[dict] | tuple[list[dict], list[WarningEntry]]:
    from ..core.futures import VALID_VERDICTS, list_assessments

    if verdict and verdict not in VALID_VERDICTS:
        raise ValueError(f"Invalid verdict '{verdict}'. Must be one of: {VALID_VERDICTS}")

    def fn(conn: sqlite3.Connection, repo: dict) -> list[dict]:
        results = list_assessments(conn, verdict=verdict, limit=limit * 2)
        if since:
            results = [row for row in results if row.get("created_at", "") >= since]
        return results

    results, warnings = RepoExecutor().execute(fn, repos=repos, sort_key="created_at", limit=limit)
    return _return_with_warnings(results, warnings, include_warnings)


def cross_repo_assessment_trends(
    repos: list[str] | None = None,
    since: str | None = None,
    include_warnings: bool = False,
) -> dict | tuple[dict, list[WarningEntry]]:
    from ..core.futures import list_assessments

    executor = RepoExecutor()
    repo_list = executor.registry.list_repos(repos)
    executor.policy.lazy_pull_repos(repo_list)

    warnings: list[WarningEntry] = []
    by_repo: dict[str, dict] = {}
    overall: dict[str, int] = {"expand": 0, "narrow": 0, "neutral": 0}
    total_count = 0
    with_feedback = 0

    from ..db.connection import _configure_connection
    from ..db.migration import check_and_migrate

    for repo in repo_list:
        try:
            conn = sqlite3.connect(repo["db_path"])
            _configure_connection(conn)
            check_and_migrate(conn)
            assessments = list_assessments(conn, limit=10000)
            conn.close()
            if since:
                assessments = [assessment for assessment in assessments if assessment.get("created_at", "") >= since]

            counts: dict[str, int] = {"expand": 0, "narrow": 0, "neutral": 0}
            repo_with_feedback = 0
            for assessment in assessments:
                verdict = assessment.get("verdict", "neutral")
                if verdict in counts:
                    counts[verdict] += 1
                    overall[verdict] = overall.get(verdict, 0) + 1
                if assessment.get("feedback"):
                    repo_with_feedback += 1
                    with_feedback += 1

            repo_total = sum(counts.values())
            total_count += repo_total
            by_repo[repo["repo_name"]] = {
                "total": repo_total,
                "expand": counts["expand"],
                "narrow": counts["narrow"],
                "neutral": counts["neutral"],
                "with_feedback": repo_with_feedback,
                "repo_path": repo["repo_path"],
            }
        except Exception as exc:
            warnings.append(executor.policy.warning(repo, "trends", exc))
            logger.debug("Skipping repo %s", repo.get("repo_path"), exc_info=True)

    result = {
        "total_count": total_count,
        "with_feedback": with_feedback,
        "overall": overall,
        "by_repo": by_repo,
    }
    if include_warnings:
        return result, warnings
    return result


def _sort_key_for_target(target: str) -> str:
    return CrossRepoPolicy.SORT_KEYS.get(target, "timestamp")
