"""Session lifecycle management via Claude Code hooks."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_git_root(cwd: str) -> str | None:
    """Find the git repo root from cwd."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _ensure_project(conn, repo_path: str) -> str:
    """Ensure project exists, return project_id."""
    row = conn.execute("SELECT id FROM projects WHERE repo_path = ?", (repo_path,)).fetchone()
    if row:
        return row["id"]

    from pathlib import Path

    project_id = str(uuid4())
    conn.execute(
        "INSERT INTO projects (id, name, repo_path) VALUES (?, ?, ?)",
        (project_id, Path(repo_path).name, repo_path),
    )
    conn.commit()
    return project_id


def on_session_start(data: dict[str, Any]) -> None:
    """Handle SessionStart hook — create or resume a session."""
    session_id = data.get("session_id")
    cwd = data.get("cwd", ".")
    source = data.get("source", "startup")

    repo_path = _find_git_root(cwd)
    if not repo_path:
        return

    from ..db import get_db, check_and_migrate

    conn = get_db(repo_path)
    check_and_migrate(conn)

    project_id = _ensure_project(conn, repo_path)
    now = _now_iso()

    if source == "resume" and session_id:
        row = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE sessions SET last_activity_at = ?, updated_at = ? WHERE id = ?",
                (now, now, session_id),
            )
            conn.commit()
            conn.close()
            return

    if not session_id:
        session_id = str(uuid4())

    conn.execute(
        """INSERT OR IGNORE INTO sessions
        (id, project_id, session_type, workspace_path, started_at, last_activity_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, project_id, "claude", cwd, now, now),
    )
    conn.commit()
    conn.close()


def on_session_end(data: dict[str, Any]) -> None:
    """Handle SessionEnd hook — mark session as ended and update global counts."""
    session_id = data.get("session_id")
    cwd = data.get("cwd", ".")

    if not session_id:
        return

    repo_path = _find_git_root(cwd)
    if not repo_path:
        return

    from ..db import get_db

    conn = get_db(repo_path)
    now = _now_iso()
    conn.execute(
        "UPDATE sessions SET ended_at = ?, updated_at = ? WHERE id = ?",
        (now, now, session_id),
    )
    conn.commit()

    try:
        session_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        turn_count = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        conn.close()

        from ..db import get_global_db
        from ..db.global_schema import init_global_schema

        gconn = get_global_db()
        init_global_schema(gconn)
        gconn.execute(
            "UPDATE repo_index SET session_count = ?, turn_count = ? WHERE repo_path = ?",
            (session_count, turn_count, repo_path),
        )
        gconn.commit()
        gconn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
