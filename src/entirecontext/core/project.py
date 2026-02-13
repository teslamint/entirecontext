"""Project management — init, status, discovery."""

from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import uuid4

from ..db import get_db, get_global_db, check_and_migrate
from ..db.global_schema import init_global_schema


def find_git_root(path: str | Path = ".") -> str | None:
    """Find git repo root from given path."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def init_project(repo_path: str | Path | None = None) -> dict:
    """Initialize EntireContext in a git repo.

    Creates .entirecontext/ directory structure and initializes DB.
    Returns project info dict.
    """
    if repo_path is None:
        repo_path = find_git_root()
    if repo_path is None:
        raise RuntimeError("Not inside a git repository. Run 'git init' first.")

    repo_path = str(Path(repo_path).resolve())
    ec_dir = Path(repo_path) / ".entirecontext"
    ec_dir.mkdir(exist_ok=True)
    (ec_dir / "db").mkdir(exist_ok=True)
    (ec_dir / "content").mkdir(exist_ok=True)

    conn = get_db(repo_path)
    check_and_migrate(conn)

    row = conn.execute("SELECT id, name FROM projects WHERE repo_path = ?", (repo_path,)).fetchone()

    if row:
        project_id = row["id"]
        project_name = row["name"]
    else:
        project_id = str(uuid4())
        project_name = Path(repo_path).name

        remote_url = None
        try:
            result = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                remote_url = result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        conn.execute(
            "INSERT INTO projects (id, name, repo_path, remote_url) VALUES (?, ?, ?, ?)",
            (project_id, project_name, repo_path, remote_url),
        )
        conn.commit()

    conn.close()

    _register_in_global_db(repo_path, project_name)

    return {"id": project_id, "name": project_name, "repo_path": repo_path}


def _register_in_global_db(repo_path: str, repo_name: str) -> None:
    """Register repo in the global cross-repo index."""
    db_path = str(Path(repo_path) / ".entirecontext" / "db" / "local.db")
    try:
        gconn = get_global_db()
        init_global_schema(gconn)
        gconn.execute(
            """INSERT OR REPLACE INTO repo_index (repo_path, repo_name, db_path, last_indexed_at)
            VALUES (?, ?, ?, datetime('now'))""",
            (repo_path, repo_name, db_path),
        )
        gconn.commit()
        gconn.close()
    except Exception:
        pass


def get_project(repo_path: str | Path | None = None) -> dict | None:
    """Get project info for a repo. Returns None if not initialized."""
    if repo_path is None:
        repo_path = find_git_root()
    if repo_path is None:
        return None

    repo_path = str(Path(repo_path).resolve())
    db_path = Path(repo_path) / ".entirecontext" / "db" / "local.db"
    if not db_path.exists():
        return None

    conn = get_db(repo_path)
    row = conn.execute("SELECT * FROM projects WHERE repo_path = ?", (repo_path,)).fetchone()
    conn.close()

    if row:
        return dict(row)
    return None


def get_status(repo_path: str | Path | None = None) -> dict:
    """Get project status including session/turn counts."""
    if repo_path is None:
        repo_path = find_git_root()
    if repo_path is None:
        return {"initialized": False, "error": "Not in a git repository"}

    repo_path = str(Path(repo_path).resolve())
    project = get_project(repo_path)
    if project is None:
        return {"initialized": False, "repo_path": repo_path}

    conn = get_db(repo_path)
    session_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    turn_count = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
    checkpoint_count = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]

    active_session = conn.execute(
        "SELECT id, started_at, total_turns FROM sessions WHERE ended_at IS NULL ORDER BY last_activity_at DESC LIMIT 1"
    ).fetchone()

    conn.close()

    status = {
        "initialized": True,
        "project": project,
        "session_count": session_count,
        "turn_count": turn_count,
        "checkpoint_count": checkpoint_count,
        "active_session": dict(active_session) if active_session else None,
    }
    return status
