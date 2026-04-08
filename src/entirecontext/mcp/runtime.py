"""Runtime helpers for MCP tool modules."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ServiceRegistry:
    name: str = "entirecontext"


class RepoResolutionError(RuntimeError):
    """Raised when the MCP runtime cannot resolve a target repo."""


def _resolve_explicit_repo(repo_path: str, *, source_label: str) -> tuple[sqlite3.Connection, str]:
    from ..core.context import RepoContext

    # from_cwd accepts an explicit path argument; here it opens a repo at the given path, not necessarily the process cwd
    context = RepoContext.from_cwd(repo_path, require_project=False)
    if context is None:
        raise RepoResolutionError(f"{source_label}={repo_path} does not exist or is not a git repo.")
    if context.project is None:
        resolved_path = context.repo_path
        context.close()
        raise RepoResolutionError(f"{source_label}={repo_path} points to a repo at {resolved_path} that is not initialized. Run 'ec init'.")
    return context.conn, context.repo_path


def _resolve_from_cwd() -> tuple[sqlite3.Connection, str] | None:
    from ..core.context import RepoContext

    context = RepoContext.from_cwd(require_project=False)
    if context is None:
        return None
    if context.project is None:
        context.close()
        return None
    return context.conn, context.repo_path


def _list_valid_registered_repos() -> list[dict]:
    from ..core.context import GlobalContext, RepoContext

    global_context = GlobalContext.create()
    try:
        repos = global_context.list_registered_repos()
    finally:
        global_context.close()

    valid_repos: list[dict] = []
    for repo in repos:
        repo_path = repo.get("repo_path")
        if not repo_path or not Path(repo_path).exists():
            continue
        context = RepoContext.from_repo_path(repo_path, require_project=True)
        if context is None:
            continue
        context.close()
        valid_repos.append(repo)
    return valid_repos


def get_repo_db(repo_hint: str | None = None) -> tuple[sqlite3.Connection, str]:
    if repo_hint:
        return _resolve_explicit_repo(repo_hint, source_label="repo_hint")

    env_repo_path = os.environ.get("ENTIRECONTEXT_REPO_PATH")
    if env_repo_path:
        return _resolve_explicit_repo(env_repo_path, source_label="ENTIRECONTEXT_REPO_PATH")

    cwd_context = _resolve_from_cwd()
    if cwd_context is not None:
        return cwd_context

    valid_repos = _list_valid_registered_repos()
    if len(valid_repos) == 1:
        from ..core.context import RepoContext

        repo_path = valid_repos[0]["repo_path"]
        context = RepoContext.from_repo_path(repo_path, require_project=True)
        if context is None:
            raise RepoResolutionError(f"Repo at {repo_path} became unavailable. Set ENTIRECONTEXT_REPO_PATH.")
        return context.conn, context.repo_path
    if len(valid_repos) > 1:
        names = ", ".join(sorted(repo.get("repo_name") or Path(repo["repo_path"]).name for repo in valid_repos))
        raise RepoResolutionError(f"Multiple repos registered. Set ENTIRECONTEXT_REPO_PATH to disambiguate: {names}")

    raise RepoResolutionError("No repo found. Run 'ec init' in your repo or set ENTIRECONTEXT_REPO_PATH.")


def resolve_repo():
    try:
        return get_repo_db(), None
    except RepoResolutionError as exc:
        return (None, None), error_payload(str(exc))


def detect_current_session(conn):
    from . import server

    return server._detect_current_session(conn)


def record_search_event(conn, **kwargs):
    from . import server

    return server._record_search_event(conn, **kwargs)


def record_selection(conn, **kwargs):
    from . import server

    return server._record_selection(conn, **kwargs)


def normalize_repo_names(repos: list[str] | None) -> list[str] | None:
    return None if not repos or repos == ["*"] else repos


def error_payload(message: str, *, warnings: list | None = None, **extra) -> str:
    payload = {"error": message}
    if warnings:
        payload["warnings"] = warnings
    payload.update(extra)
    return json.dumps(payload)
