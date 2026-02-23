"""Purge — hard delete turns, sessions, and matching content."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class ActiveSessionError(Exception):
    """Raised when attempting to purge an active (un-ended) session."""


def _resolve_content_path(repo_path: str, content_path: str) -> Path:
    return Path(repo_path) / ".entirecontext" / content_path


def _delete_content_file(repo_path: str, content_path: str) -> bool:
    full = _resolve_content_path(repo_path, content_path)
    if full.exists():
        full.unlink()
        parent = full.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
        return True
    return False


def _turn_preview(row: dict) -> dict:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "turn_number": row.get("turn_number"),
        "user_message": (row.get("user_message") or "")[:100],
        "timestamp": row.get("timestamp"),
    }


def purge_turns(conn, repo_path: str, turn_ids: list[str], dry_run: bool = True) -> dict[str, Any]:
    """Purge specific turns by ID."""
    if not turn_ids:
        return {"matched_turns": 0, "deleted": 0, "dry_run": dry_run, "previews": []}

    placeholders = ",".join("?" for _ in turn_ids)
    rows = conn.execute(f"SELECT * FROM turns WHERE id IN ({placeholders})", turn_ids).fetchall()

    previews = [_turn_preview(dict(r)) for r in rows]

    if dry_run:
        return {"matched_turns": len(rows), "deleted": 0, "dry_run": True, "previews": previews}

    for row in rows:
        tc = conn.execute("SELECT content_path FROM turn_content WHERE turn_id = ?", (row["id"],)).fetchone()
        if tc:
            _delete_content_file(repo_path, tc["content_path"])

    conn.execute(f"DELETE FROM turns WHERE id IN ({placeholders})", turn_ids)
    conn.commit()

    return {"matched_turns": len(rows), "deleted": len(rows), "dry_run": False, "previews": previews}


def purge_session(conn, repo_path: str, session_id: str, dry_run: bool = True) -> dict[str, Any]:
    """Purge an entire session and its turns."""
    session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not session:
        return {"matched_turns": 0, "deleted": 0, "dry_run": dry_run, "error": "Session not found"}

    if session["ended_at"] is None:
        raise ActiveSessionError(f"Cannot purge active session: {session_id}")

    turns = conn.execute("SELECT * FROM turns WHERE session_id = ?", (session_id,)).fetchall()
    previews = [_turn_preview(dict(t)) for t in turns]

    if dry_run:
        return {
            "session_id": session_id,
            "matched_turns": len(turns),
            "deleted": 0,
            "dry_run": True,
            "previews": previews,
        }

    for turn in turns:
        tc = conn.execute("SELECT content_path FROM turn_content WHERE turn_id = ?", (turn["id"],)).fetchone()
        if tc:
            _delete_content_file(repo_path, tc["content_path"])

    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()

    content_dir = Path(repo_path) / ".entirecontext" / "content" / session_id
    if content_dir.exists() and not any(content_dir.iterdir()):
        content_dir.rmdir()

    return {
        "session_id": session_id,
        "matched_turns": len(turns),
        "deleted": len(turns),
        "dry_run": False,
        "previews": previews,
    }


def purge_by_pattern(conn, repo_path: str, pattern: str, dry_run: bool = True) -> dict[str, Any]:
    """Purge turns matching a regex pattern in user_message or assistant_summary."""
    regex = re.compile(pattern, re.IGNORECASE)

    rows = conn.execute("SELECT * FROM turns").fetchall()
    matched = []
    for row in rows:
        text = f"{row['user_message'] or ''} {row['assistant_summary'] or ''}"
        if regex.search(text):
            matched.append(row)

    previews = [_turn_preview(dict(r)) for r in matched]

    if not matched:
        return {"matched_turns": 0, "deleted": 0, "dry_run": dry_run, "previews": []}

    if dry_run:
        return {"matched_turns": len(matched), "deleted": 0, "dry_run": True, "previews": previews}

    turn_ids = [r["id"] for r in matched]
    for row in matched:
        tc = conn.execute("SELECT content_path FROM turn_content WHERE turn_id = ?", (row["id"],)).fetchone()
        if tc:
            _delete_content_file(repo_path, tc["content_path"])

    placeholders = ",".join("?" for _ in turn_ids)
    conn.execute(f"DELETE FROM turns WHERE id IN ({placeholders})", turn_ids)
    conn.commit()

    return {"matched_turns": len(matched), "deleted": len(matched), "dry_run": False, "previews": previews}
