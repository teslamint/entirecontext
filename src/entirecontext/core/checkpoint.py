"""Checkpoint CRUD operations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_checkpoint(
    conn,
    session_id: str,
    git_commit_hash: str,
    git_branch: str | None = None,
    files_snapshot: dict | list | None = None,
    diff_summary: str | None = None,
    parent_checkpoint_id: str | None = None,
    metadata: dict | None = None,
    checkpoint_id: str | None = None,
) -> dict:
    """Create a new checkpoint linked to a session and git commit."""
    if checkpoint_id is None:
        checkpoint_id = str(uuid4())

    files_snapshot_json = json.dumps(files_snapshot) if files_snapshot is not None else None
    metadata_json = json.dumps(metadata) if metadata is not None else None

    conn.execute(
        """INSERT INTO checkpoints
        (id, session_id, git_commit_hash, git_branch, parent_checkpoint_id, files_snapshot, diff_summary, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            checkpoint_id,
            session_id,
            git_commit_hash,
            git_branch,
            parent_checkpoint_id,
            files_snapshot_json,
            diff_summary,
            metadata_json,
        ),
    )
    conn.commit()
    return {
        "id": checkpoint_id,
        "session_id": session_id,
        "git_commit_hash": git_commit_hash,
        "git_branch": git_branch,
    }


def get_checkpoint(conn, checkpoint_id: str) -> dict | None:
    """Get a checkpoint by ID (supports prefix match)."""
    row = conn.execute("SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)).fetchone()
    if not row:
        row = conn.execute("SELECT * FROM checkpoints WHERE id LIKE ?", (f"{checkpoint_id}%",)).fetchone()
    if row:
        result = dict(row)
        if result.get("files_snapshot"):
            try:
                result["files_snapshot"] = json.loads(result["files_snapshot"])
            except (json.JSONDecodeError, TypeError):
                pass
        if result.get("metadata"):
            try:
                result["metadata"] = json.loads(result["metadata"])
            except (json.JSONDecodeError, TypeError):
                pass
        return result
    return None


def list_checkpoints(
    conn,
    session_id: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List checkpoints, optionally filtered by session."""
    query = "SELECT * FROM checkpoints"
    params: list[Any] = []

    if session_id:
        query += " WHERE session_id = ?"
        params.append(session_id)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def diff_checkpoints(conn, id1: str, id2: str) -> dict:
    """Compare two checkpoints by their files_snapshot."""
    cp1 = get_checkpoint(conn, id1)
    cp2 = get_checkpoint(conn, id2)

    if not cp1:
        return {"error": f"Checkpoint not found: {id1}"}
    if not cp2:
        return {"error": f"Checkpoint not found: {id2}"}

    snap1 = cp1.get("files_snapshot") or {}
    snap2 = cp2.get("files_snapshot") or {}

    if isinstance(snap1, list):
        snap1 = {f: None for f in snap1}
    if isinstance(snap2, list):
        snap2 = {f: None for f in snap2}

    all_files = set(snap1.keys()) | set(snap2.keys())
    added = sorted(f for f in all_files if f not in snap1)
    removed = sorted(f for f in all_files if f not in snap2)
    modified = sorted(f for f in all_files if f in snap1 and f in snap2 and snap1[f] != snap2[f])
    unchanged = sorted(f for f in all_files if f in snap1 and f in snap2 and snap1[f] == snap2[f])

    return {
        "checkpoint_1": {"id": cp1["id"], "commit": cp1["git_commit_hash"]},
        "checkpoint_2": {"id": cp2["id"], "commit": cp2["git_commit_hash"]},
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged": unchanged,
    }
