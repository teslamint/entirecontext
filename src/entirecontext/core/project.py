"""Project management — init, status, discovery."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4

from .context import RepoContext
from .repo_roots import RepoRoots, resolve_repo_roots, roots_for_workspace
from ..db import db_path_for, get_db, get_global_db, check_and_migrate
from ..db.global_schema import init_global_schema


def find_git_root(path: str | Path = ".") -> str | None:
    """Find the current checkout (workspace) root from the given path.

    In a linked worktree this is the worktree's own toplevel. Use it for Git
    subprocesses and checkout-relative paths; use ``find_project_root`` for
    anything that opens the database, loads config or touches ``.entirecontext``.
    """
    roots = resolve_repo_roots(path)
    return roots.workspace_root if roots else None


def get_repo_roots(path: str | Path | None = None) -> RepoRoots | None:
    """Return the project and workspace roots for ``path`` (default: cwd)."""
    workspace_root = find_git_root() if path is None else find_git_root(path)
    if not workspace_root:
        return None
    return roots_for_workspace(workspace_root)


def find_project_root(path: str | Path | None = None) -> str | None:
    """Find the canonical project root (shared by all linked worktrees)."""
    roots = get_repo_roots(path)
    return roots.project_root if roots else None


def _read_remote_url(repo_path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def ensure_project(conn, roots: RepoRoots, *, remote_url: str | None = None) -> str:
    """Return the logical project id for ``roots``, creating the row if needed.

    The row is keyed by the canonical project root; ``git_common_dir`` is
    backfilled lazily for rows created before schema v21.
    """
    project_root = roots.project_root
    row = conn.execute("SELECT id, git_common_dir FROM projects WHERE repo_path = ?", (project_root,)).fetchone()
    if row:
        if row["git_common_dir"] is None and roots.git_common_dir:
            try:
                conn.execute(
                    "UPDATE projects SET git_common_dir = ? WHERE id = ? AND git_common_dir IS NULL",
                    (roots.git_common_dir, row["id"]),
                )
            except sqlite3.IntegrityError:
                pass
        return row["id"]

    project_id = str(uuid4())
    common_dir = roots.git_common_dir
    if common_dir is not None:
        clash = conn.execute("SELECT 1 FROM projects WHERE git_common_dir = ?", (common_dir,)).fetchone()
        if clash:
            common_dir = None
    conn.execute(
        "INSERT INTO projects (id, name, repo_path, remote_url, git_common_dir) VALUES (?, ?, ?, ?, ?)",
        (project_id, Path(project_root).name, project_root, remote_url, common_dir),
    )
    return project_id


def legacy_worktree_db_path(roots: RepoRoots) -> Path | None:
    """Return a pre-v21 per-worktree DB path when one exists for this workspace."""
    if not roots.is_linked_worktree:
        return None
    path = db_path_for(roots.workspace_root)
    return path if path.is_file() else None


def detect_legacy_worktree_db(roots: RepoRoots) -> dict | None:
    """Describe a legacy per-worktree DB using a read-only connection. Never writes."""
    path = legacy_worktree_db_path(roots)
    if path is None:
        return None
    info: dict = {"path": str(path), "session_count": None, "decision_count": None}
    try:
        from .decision_verify import open_source_db_readonly

        conn = open_source_db_readonly(path)
        try:
            for key, table in (("session_count", "sessions"), ("decision_count", "decisions")):
                try:
                    info[key] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
                except sqlite3.Error:
                    pass
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        pass
    return info


def init_project(repo_path: str | Path | None = None) -> dict:
    """Initialize EntireContext in a git repo.

    Creates .entirecontext/ under the canonical project root (the main
    worktree when run from a linked worktree) and initializes the DB.
    Returns project info dict.
    """
    if repo_path is None:
        repo_path = find_git_root()
    if repo_path is None:
        raise RuntimeError("Not inside a git repository. Run 'git init' first.")
    roots = roots_for_workspace(str(Path(repo_path).resolve()))

    project_root = roots.project_root
    ec_dir = Path(project_root) / ".entirecontext"
    existed = db_path_for(project_root).exists()
    ec_dir.mkdir(exist_ok=True)
    (ec_dir / "db").mkdir(exist_ok=True)
    (ec_dir / "content").mkdir(exist_ok=True)

    conn = get_db(project_root)
    try:
        check_and_migrate(conn)
        row = conn.execute("SELECT id FROM projects WHERE repo_path = ?", (project_root,)).fetchone()
        joined_existing = existed and row is not None
        remote_url = None if row else _read_remote_url(project_root)
        project_id = ensure_project(conn, roots, remote_url=remote_url)
        project_name = conn.execute("SELECT name FROM projects WHERE id = ?", (project_id,)).fetchone()["name"]
    finally:
        conn.close()

    _register_in_global_db(project_root, project_name)

    legacy = detect_legacy_worktree_db(roots)
    return {
        "id": project_id,
        "name": project_name,
        "repo_path": project_root,
        "workspace_root": roots.workspace_root,
        "is_linked_worktree": roots.is_linked_worktree,
        "joined_existing": joined_existing,
        "legacy_worktree_db": legacy,
    }


def _register_in_global_db(repo_path: str, repo_name: str) -> None:
    """Register repo in the global cross-repo index."""
    db_path = str(db_path_for(repo_path))
    try:
        gconn = get_global_db()
        try:
            init_global_schema(gconn)
            gconn.execute(
                """INSERT OR REPLACE INTO repo_index (repo_path, repo_name, db_path, last_indexed_at)
                VALUES (?, ?, ?, datetime('now'))""",
                (repo_path, repo_name, db_path),
            )
        finally:
            gconn.close()
    except Exception:
        pass


def get_project(repo_path: str | Path | None = None) -> dict | None:
    """Get project info for a repo. Returns None if not initialized."""
    if repo_path is None:
        context = RepoContext.from_cwd()
    else:
        context = RepoContext.from_repo_path(repo_path)
    if context is None:
        return None
    try:
        return context.project
    finally:
        context.close()


def get_status(repo_path: str | Path | None = None) -> dict:
    """Get project status including session/turn counts."""
    if repo_path is None:
        context = RepoContext.from_cwd()
    else:
        context = RepoContext.from_repo_path(repo_path)
    if context is None:
        return {"initialized": False, "error": "Not in a git repository"}
    try:
        if context.project is None:
            return {"initialized": False, "repo_path": context.repo_path}

        from .session import get_current_session, workspace_filter

        roots = context.roots or roots_for_workspace(context.repo_path)
        conn = context.conn
        session_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        turn_count = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        checkpoint_count = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
        ws_clause, ws_params = workspace_filter(roots.workspace_root)
        workspace_session_count = conn.execute(
            f"SELECT COUNT(*) FROM sessions WHERE {ws_clause}", ws_params
        ).fetchone()[0]

        current = get_current_session(conn, workspace_root=roots.workspace_root)
        active_session = (
            {"id": current["id"], "started_at": current["started_at"], "total_turns": current["total_turns"]}
            if current
            else None
        )

        project = context.project
        return {
            "initialized": True,
            "project": project,
            "logical_project": {
                "id": project["id"],
                "name": project["name"],
                "repo_path": project["repo_path"],
                "git_common_dir": project.get("git_common_dir") or roots.git_common_dir,
            },
            "workspace": {
                "root": roots.workspace_root,
                "branch": roots.branch,
                "worktree_git_dir": roots.worktree_git_dir,
                "is_linked": roots.is_linked_worktree,
            },
            "session_count": session_count,
            "workspace_session_count": workspace_session_count,
            "turn_count": turn_count,
            "checkpoint_count": checkpoint_count,
            "active_session": active_session,
            "legacy_worktree_db": detect_legacy_worktree_db(roots),
        }
    finally:
        context.close()
