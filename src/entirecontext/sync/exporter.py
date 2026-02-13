"""Export from SQLite to shadow branch files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def export_sessions(conn, repo_path: str, worktree_path: str, since: str | None = None) -> int:
    """Export sessions to shadow branch worktree. Returns count of exported sessions."""
    query = "SELECT * FROM sessions"
    params: list[Any] = []
    if since:
        query += " WHERE last_activity_at > ?"
        params.append(since)

    rows = conn.execute(query, params).fetchall()
    count = 0

    for row in rows:
        session = dict(row)
        session_id = session["id"]
        session_dir = Path(worktree_path) / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "id": session_id,
            "project_id": session.get("project_id"),
            "session_type": session.get("session_type"),
            "started_at": session.get("started_at"),
            "ended_at": session.get("ended_at"),
            "session_title": session.get("session_title"),
            "session_summary": session.get("session_summary"),
            "total_turns": session.get("total_turns"),
        }
        (session_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        turns = conn.execute(
            "SELECT * FROM turns WHERE session_id = ? ORDER BY turn_number",
            (session_id,),
        ).fetchall()

        transcript_lines = []
        for turn in turns:
            turn_dict = dict(turn)
            transcript_lines.append(json.dumps(turn_dict))

        (session_dir / "transcript.jsonl").write_text(
            "\n".join(transcript_lines) + "\n" if transcript_lines else "",
            encoding="utf-8",
        )
        count += 1

    return count


def export_checkpoints(conn, worktree_path: str, since: str | None = None) -> int:
    """Export checkpoints to shadow branch worktree. Returns count."""
    query = "SELECT * FROM checkpoints"
    params: list[Any] = []
    if since:
        query += " WHERE created_at > ?"
        params.append(since)

    rows = conn.execute(query, params).fetchall()
    checkpoints_dir = Path(worktree_path) / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for row in rows:
        cp = dict(row)
        cp_path = checkpoints_dir / f"{cp['id']}.json"
        cp_path.write_text(json.dumps(cp, indent=2), encoding="utf-8")
        count += 1

    return count


def update_manifest(conn, worktree_path: str) -> None:
    """Update manifest.json with current data."""
    manifest_path = Path(worktree_path) / "manifest.json"

    manifest: dict = {"version": 1, "checkpoints": {}, "sessions": {}}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    sessions = conn.execute("SELECT id, session_type, started_at, total_turns FROM sessions").fetchall()
    for s in sessions:
        manifest["sessions"][s["id"]] = {
            "session_type": s["session_type"],
            "started_at": s["started_at"],
            "total_turns": s["total_turns"],
        }

    checkpoints = conn.execute("SELECT id, session_id, git_commit_hash, created_at FROM checkpoints").fetchall()
    for cp in checkpoints:
        manifest["checkpoints"][cp["id"]] = {
            "session_id": cp["session_id"],
            "commit_hash": cp["git_commit_hash"],
            "created_at": cp["created_at"],
        }

    manifest["updated_at"] = _now_iso()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
