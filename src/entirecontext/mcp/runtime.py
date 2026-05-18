"""Runtime helpers for MCP tool modules."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ServiceRegistry:
    name: str = "entirecontext"


class RepoResolutionError(RuntimeError):
    """Raised when the MCP runtime cannot resolve a target repo."""


# Repo path resolved on first successful lookup within this process.
# Avoids repeating git/filesystem discovery on every tool call in a
# long-running MCP server — especially important when the fallback path
# (`_list_valid_registered_repos`) would block on unmounted network volumes.
_cached_repo_path: str | None = None


def _path_exists_timeout(path: str, timeout: float = 1.0) -> bool:
    """Return Path(path).exists() or False if the check blocks longer than `timeout` s.

    Prevents hang on unmounted network filesystems (e.g. /Volumes/ on macOS).
    """
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; sys.exit(0 if Path(sys.argv[1]).exists() else 1)",
                path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _resolve_explicit_repo(repo_path: str, *, source_label: str) -> tuple[sqlite3.Connection, str]:
    from ..core.context import RepoContext

    context = RepoContext.from_cwd(repo_path, require_project=False)
    if context is None:
        raise RepoResolutionError(f"{source_label}={repo_path} does not exist or is not a git repo.")
    if context.project is None:
        resolved_path = context.repo_path
        context.close()
        raise RepoResolutionError(
            f"{source_label}={repo_path} points to a repo at {resolved_path} that is not initialized. Run 'ec init'."
        )
    # Caller takes ownership of conn; context is intentionally not closed here
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

    with GlobalContext.create() as global_context:
        repos = global_context.list_registered_repos()

    valid_repos: list[dict] = []
    for repo in repos:
        repo_path = repo.get("repo_path")
        if not repo_path or not _path_exists_timeout(repo_path):
            continue
        context = RepoContext.from_repo_path(repo_path, require_project=True)
        if context is None:
            continue
        context.close()
        valid_repos.append(repo)
    return valid_repos


def _open_single_registered_repo(valid_repos: list[dict]) -> tuple[sqlite3.Connection, str]:
    """Open the sole registered repo, raising on ambiguity or absence."""
    from ..core.context import RepoContext

    if len(valid_repos) == 1:
        repo_path = valid_repos[0]["repo_path"]
        context = RepoContext.from_repo_path(repo_path, require_project=True)
        if context is None:
            raise RepoResolutionError(f"Repo at {repo_path} became unavailable. Set ENTIRECONTEXT_REPO_PATH.")
        return context.conn, context.repo_path
    if len(valid_repos) > 1:
        names = ", ".join(sorted(repo.get("repo_name") or Path(repo["repo_path"]).name for repo in valid_repos))
        raise RepoResolutionError(f"Multiple repos registered. Set ENTIRECONTEXT_REPO_PATH to disambiguate: {names}")
    raise RepoResolutionError("No repo found. Run 'ec init' in your repo or set ENTIRECONTEXT_REPO_PATH.")


def get_repo_db(repo_hint: str | None = None) -> tuple[sqlite3.Connection, str]:
    global _cached_repo_path

    if repo_hint:
        return _resolve_explicit_repo(repo_hint, source_label="repo_hint")

    env_repo_path = os.environ.get("ENTIRECONTEXT_REPO_PATH")
    if env_repo_path:
        return _resolve_explicit_repo(env_repo_path, source_label="ENTIRECONTEXT_REPO_PATH")

    cwd_context = _resolve_from_cwd()
    if cwd_context is not None:
        _cached_repo_path = cwd_context[1]
        return cwd_context

    if _cached_repo_path is not None:
        try:
            return _resolve_explicit_repo(_cached_repo_path, source_label="cached_repo_path")
        except RepoResolutionError:
            _cached_repo_path = None

    valid_repos = _list_valid_registered_repos()
    result = _open_single_registered_repo(valid_repos)
    _cached_repo_path = result[1]
    return result


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


def normalize_repo_names(repos: str | list[str] | None) -> list[str] | None:
    if isinstance(repos, str):
        repos = [repos] if repos else []
    return None if not repos or repos == ["*"] else repos


def error_payload(message: str, *, warnings: list | None = None, **extra) -> str:
    payload = {"error": message}
    if warnings:
        payload["warnings"] = warnings
    payload.update(extra)
    return json.dumps(payload)
