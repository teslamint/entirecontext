"""Turn CRUD operations."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(user_message: str | None, assistant_summary: str | None) -> str:
    """MD5 hex digest of user_message + assistant_summary."""
    text = f"{user_message or ''}{assistant_summary or ''}"
    return hashlib.md5(text.encode()).hexdigest()


def create_turn(
    conn,
    session_id: str,
    turn_number: int,
    user_message: str | None = None,
    assistant_summary: str | None = None,
    **kwargs,
) -> dict:
    """Create a new turn."""
    turn_id = kwargs.pop("turn_id", None) or str(uuid4())
    now = _now_iso()
    c_hash = content_hash(user_message, assistant_summary)

    conn.execute(
        """INSERT INTO turns
        (id, session_id, turn_number, user_message, assistant_summary,
         content_hash, timestamp, turn_status, model_name, git_commit_hash,
         files_touched, tools_used)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            turn_id,
            session_id,
            turn_number,
            user_message,
            assistant_summary,
            c_hash,
            now,
            kwargs.get("turn_status", "completed"),
            kwargs.get("model_name"),
            kwargs.get("git_commit_hash"),
            kwargs.get("files_touched"),
            kwargs.get("tools_used"),
        ),
    )
    conn.commit()
    return {"id": turn_id, "session_id": session_id, "turn_number": turn_number}


def get_turn(conn, turn_id: str) -> dict | None:
    """Get a turn by ID."""
    row = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
    return dict(row) if row else None


def list_turns(conn, session_id: str, limit: int = 50) -> list[dict]:
    """List turns for a session."""
    rows = conn.execute(
        "SELECT * FROM turns WHERE session_id = ? ORDER BY turn_number ASC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def save_turn_content(
    repo_path: str,
    conn,
    turn_id: str,
    session_id: str,
    content: str,
) -> str:
    """Save turn content to external file and record in DB."""
    content_dir = Path(repo_path) / ".entirecontext" / "content" / session_id
    content_dir.mkdir(parents=True, exist_ok=True)
    file_path = content_dir / f"{turn_id}.jsonl"
    file_path.write_text(content, encoding="utf-8")

    rel_path = f"content/{session_id}/{turn_id}.jsonl"
    size = len(content.encode("utf-8"))
    file_hash = hashlib.md5(content.encode()).hexdigest()

    conn.execute(
        "INSERT OR REPLACE INTO turn_content (turn_id, content_path, content_size, content_hash) VALUES (?, ?, ?, ?)",
        (turn_id, rel_path, size, file_hash),
    )
    conn.commit()
    return rel_path
