"""Session CRUD operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_session(
    conn,
    project_id: str,
    session_type: str = "claude",
    session_id: str | None = None,
    agent_id: str | None = None,
    workspace_path: str | None = None,
    workspace_root: str | None = None,
    worktree_git_dir: str | None = None,
    git_branch: str | None = None,
) -> dict:
    """Create a new session."""
    if session_id is None:
        session_id = str(uuid4())
    now = _now_iso()

    conn.execute(
        """INSERT INTO sessions
        (id, project_id, agent_id, session_type, workspace_path, workspace_root, worktree_git_dir, git_branch,
         started_at, last_activity_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            project_id,
            agent_id,
            session_type,
            workspace_path,
            workspace_root,
            worktree_git_dir,
            git_branch,
            now,
            now,
        ),
    )
    return {"id": session_id, "project_id": project_id, "started_at": now}


def get_session(conn, session_id: str) -> dict | None:
    """Get a session by ID."""
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def list_sessions(
    conn,
    project_id: str | None = None,
    limit: int = 20,
    include_ended: bool = True,
    workspace_root: str | None = None,
) -> list[dict]:
    """List sessions, optionally filtered by project or workspace root."""
    query = "SELECT * FROM sessions"
    params: list[Any] = []
    conditions = []

    if project_id:
        conditions.append("project_id = ?")
        params.append(project_id)
    if workspace_root:
        clause, clause_params = workspace_filter(workspace_root)
        conditions.append(clause)
        params.extend(clause_params)
    if not include_ended:
        conditions.append("ended_at IS NULL")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY last_activity_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def _is_linked_worktree(workspace_root: str) -> bool:
    from .repo_roots import is_linked_worktree_root

    try:
        return is_linked_worktree_root(workspace_root)
    except OSError:
        return False


def workspace_filter(workspace_root: str) -> tuple[str, tuple[str, ...]]:
    """SQL condition for the sessions that belong to ``workspace_root``.

    Pre-v21 rows have no workspace and were recorded in the project's own
    checkout, so they belong to that checkout but never to a linked worktree.
    """
    if _is_linked_worktree(workspace_root):
        return "workspace_root = ?", (workspace_root,)
    return "(workspace_root = ? OR workspace_root IS NULL)", (workspace_root,)


def get_current_session(conn, workspace_root: str | None = None) -> dict | None:
    """Get the most recently active session.

    With ``workspace_root``, sessions recorded for that workspace win. Legacy
    rows without a workspace (pre-v21) predate shared worktree databases, so
    they were recorded in the project's own checkout; they are the fallback
    for that checkout but never for a linked worktree.
    """
    if workspace_root is None:
        row = conn.execute(
            "SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY last_activity_at DESC LIMIT 1"
        ).fetchone()
    else:
        clause, params = workspace_filter(workspace_root)
        row = conn.execute(
            f"SELECT * FROM sessions WHERE ended_at IS NULL AND {clause} "
            "ORDER BY (workspace_root IS NULL), last_activity_at DESC LIMIT 1",
            params,
        ).fetchone()
    return dict(row) if row else None


def update_session(conn, session_id: str, **kwargs) -> None:
    """Update session fields."""
    if not kwargs:
        return
    kwargs["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [session_id]
    conn.execute(f"UPDATE sessions SET {set_clause} WHERE id = ?", values)


def close_stale_sessions(
    conn,
    idle_minutes: int = 60,
    session_type: str = "codex",
) -> int:
    rows = conn.execute(
        "SELECT id, last_activity_at FROM sessions"
        " WHERE ended_at IS NULL"
        " AND session_type = ?"
        " AND last_activity_at IS NOT NULL"
        " AND datetime(last_activity_at) < datetime('now', ?)",
        (session_type, f"-{idle_minutes} minutes"),
    ).fetchall()

    closed = 0
    for row in rows:
        cursor = conn.execute(
            "UPDATE sessions SET ended_at = last_activity_at"
            " WHERE id = ? AND ended_at IS NULL AND last_activity_at = ?",
            (row["id"], row["last_activity_at"]),
        )
        closed += cursor.rowcount
    return closed
