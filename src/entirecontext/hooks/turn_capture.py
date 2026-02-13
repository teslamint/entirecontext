"""Turn capture logic — records user prompts, assistant responses, tool usage."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .session_lifecycle import _find_git_root


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_hash(user_message: str, assistant_summary: str) -> str:
    """MD5 hex digest of user_message + assistant_summary."""
    text = f"{user_message or ''}{assistant_summary or ''}"
    return hashlib.md5(text.encode()).hexdigest()


def _get_next_turn_number(conn, session_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(turn_number), 0) + 1 FROM turns WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return row[0]


def _save_content_file(repo_path: str, session_id: str, turn_id: str, content: str) -> tuple[str, int]:
    """Save turn content to external file. Returns (relative_path, size)."""
    content_dir = Path(repo_path) / ".entirecontext" / "content" / session_id
    content_dir.mkdir(parents=True, exist_ok=True)
    file_path = content_dir / f"{turn_id}.jsonl"
    file_path.write_text(content, encoding="utf-8")
    rel_path = f"content/{session_id}/{turn_id}.jsonl"
    return rel_path, len(content.encode("utf-8"))


def on_user_prompt(data: dict[str, Any]) -> None:
    """Handle UserPromptSubmit — record turn start with user message."""
    session_id = data.get("session_id")
    cwd = data.get("cwd", ".")
    prompt = data.get("prompt", "")

    if not session_id:
        return

    repo_path = _find_git_root(cwd)
    if not repo_path:
        return

    from ..db import get_db

    conn = get_db(repo_path)
    now = _now_iso()
    turn_id = str(uuid4())
    turn_number = _get_next_turn_number(conn, session_id)

    conn.execute(
        """INSERT INTO turns
        (id, session_id, turn_number, user_message, content_hash, timestamp, turn_status)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (turn_id, session_id, turn_number, prompt, _content_hash(prompt, ""), now, "in_progress"),
    )
    conn.execute(
        "UPDATE sessions SET last_activity_at = ?, total_turns = total_turns + 1, updated_at = ? WHERE id = ?",
        (now, now, session_id),
    )
    conn.commit()
    conn.close()


def on_stop(data: dict[str, Any]) -> None:
    """Handle Stop — record turn end, extract summary from transcript."""
    session_id = data.get("session_id")
    cwd = data.get("cwd", ".")
    transcript_path = data.get("transcript_path")

    if not session_id:
        return

    repo_path = _find_git_root(cwd)
    if not repo_path:
        return

    from ..db import get_db

    conn = get_db(repo_path)
    now = _now_iso()

    row = conn.execute(
        "SELECT id, user_message FROM turns WHERE session_id = ? AND turn_status = 'in_progress' ORDER BY turn_number DESC LIMIT 1",
        (session_id,),
    ).fetchone()

    if not row:
        conn.close()
        return

    turn_id = row["id"]
    user_message = row["user_message"] or ""

    summary = ""
    content = ""
    if transcript_path:
        from .transcript_parser import extract_last_response, extract_transcript_content

        summary = extract_last_response(transcript_path)
        content = extract_transcript_content(transcript_path)

    c_hash = _content_hash(user_message, summary)
    conn.execute(
        "UPDATE turns SET assistant_summary = ?, content_hash = ?, turn_status = 'completed' WHERE id = ?",
        (summary, c_hash, turn_id),
    )

    if content:
        rel_path, size = _save_content_file(repo_path, session_id, turn_id, content)
        file_hash = hashlib.md5(content.encode()).hexdigest()
        conn.execute(
            "INSERT OR REPLACE INTO turn_content (turn_id, content_path, content_size, content_hash) VALUES (?, ?, ?, ?)",
            (turn_id, rel_path, size, file_hash),
        )

    conn.execute(
        "UPDATE sessions SET last_activity_at = ?, updated_at = ? WHERE id = ?",
        (now, now, session_id),
    )
    conn.commit()
    conn.close()


def on_tool_use(data: dict[str, Any]) -> None:
    """Handle PostToolUse — track tool usage on current turn."""
    session_id = data.get("session_id")
    cwd = data.get("cwd", ".")
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    if not session_id or not tool_name:
        return

    repo_path = _find_git_root(cwd)
    if not repo_path:
        return

    from ..db import get_db
    import json

    conn = get_db(repo_path)

    row = conn.execute(
        "SELECT id, tools_used, files_touched FROM turns WHERE session_id = ? AND turn_status = 'in_progress' ORDER BY turn_number DESC LIMIT 1",
        (session_id,),
    ).fetchone()

    if not row:
        conn.close()
        return

    turn_id = row["id"]
    tools = json.loads(row["tools_used"]) if row["tools_used"] else []
    files = json.loads(row["files_touched"]) if row["files_touched"] else []

    if tool_name not in tools:
        tools.append(tool_name)

    if isinstance(tool_input, dict):
        for key in ("file_path", "path"):
            if key in tool_input and tool_input[key] not in files:
                files.append(tool_input[key])

    conn.execute(
        "UPDATE turns SET tools_used = ?, files_touched = ? WHERE id = ?",
        (json.dumps(tools), json.dumps(files), turn_id),
    )
    conn.commit()
    conn.close()
