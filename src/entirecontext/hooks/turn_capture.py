"""Turn capture logic — records user prompts, assistant responses, tool usage."""

from __future__ import annotations

import hashlib
import os
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


def _sanitize_id_for_path(value: str) -> str:
    """Strip filesystem-unsafe characters from an identifier.

    Used on session and turn ids that feed into tmp-file names and the
    ``pid_name`` slot consumed by ``launch_worker``. Matches the defensive
    sanitization in ``decision_hooks._post_tool_fallback_name``.
    """
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value or "unknown")


def _maybe_launch_prompt_surfacing_worker(
    repo_path: str,
    session_id: str,
    turn_id: str,
    redacted_prompt: str,
    config: dict[str, Any],
) -> None:
    """Write the redacted prompt to a 0600 tmp file and launch the surfacing worker.

    Called from ``on_user_prompt`` only when
    ``[decisions] surface_on_user_prompt = true``. The tmp file's
    ``O_EXCL`` flag prevents symlink/race attacks: if the path exists
    (even as a symlink into a restricted location), ``os.open`` raises
    ``FileExistsError`` and we skip the launch rather than clobber or
    follow the link. Never raises — any failure is swallowed so the
    surrounding turn insert is not disrupted.
    """
    tmp_path: Path | None = None
    try:
        from ..core.async_worker import launch_worker
        from ..core.content_filter import redact_for_query
        from ..core.security import filter_secrets

        # Defense-in-depth: the prompt arriving here is already filtered by
        # the capture-time ``redact_content`` call upstream in on_user_prompt,
        # but this is the last chance before the text touches disk. Apply
        # the security module's hard secret patterns (always on) and the
        # configurable query-time redaction patterns.
        safe = filter_secrets(redacted_prompt)
        safe = redact_for_query(safe, config)

        safe_session = _sanitize_id_for_path(session_id)
        safe_turn = _sanitize_id_for_path(turn_id)
        tmp_dir = Path(repo_path) / ".entirecontext" / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"prompt-{safe_session}-{safe_turn}.txt"

        # O_EXCL guards against the file already existing (symlink/race
        # attack surface). Mode 0600 applied at creation so the payload
        # never lives on disk with broader perms.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(str(tmp_path), flags, 0o600)
        try:
            os.write(fd, safe.encode("utf-8"))
        finally:
            os.close(fd)

        # pid_name is bounded so race-prone concurrent prompts don't
        # collide on the same PID file. launch_worker writes to
        # .entirecontext/<pid_name>.pid.
        pid_name = f"prompt-{safe_session}-{safe_turn}"[:100]
        launch_worker(
            repo_path,
            [
                "ec",
                "decision",
                "surface-prompt",
                "--repo-path",
                repo_path,
                "--session",
                session_id,
                "--turn",
                turn_id,
                "--prompt-file",
                str(tmp_path),
            ],
            pid_name=pid_name,
        )
    except Exception:
        # Surfacing must never disrupt the turn insert. Best-effort tmp
        # cleanup on exception — the worker's finally block is the primary
        # cleanup path but it never runs if launch failed.
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


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

    from ..core.config import load_config
    from ..core.content_filter import redact_content, should_skip_turn

    config = load_config(repo_path)

    if not config.get("capture", {}).get("auto_capture", True):
        return

    if should_skip_turn(prompt, config):
        return

    prompt = redact_content(prompt, config)

    from ..db import get_db
    import json as _json

    conn = get_db(repo_path)
    try:
        session_row = conn.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if session_row and session_row["metadata"]:
            try:
                meta = _json.loads(session_row["metadata"])
                if meta.get("capture_disabled"):
                    return
            except (ValueError, TypeError):
                pass
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

        # F4: optional async decision surfacing against the prompt text.
        # Kept strictly after the commit so the turn row is durable before
        # the worker launches, and guarded inside the helper so a launch
        # failure cannot roll back the turn insert.
        if config.get("decisions", {}).get("surface_on_user_prompt", False):
            _maybe_launch_prompt_surfacing_worker(repo_path, session_id, turn_id, prompt, config)
    finally:
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
    try:
        now = _now_iso()

        row = conn.execute(
            "SELECT id, user_message FROM turns WHERE session_id = ? AND turn_status = 'in_progress' ORDER BY turn_number DESC LIMIT 1",
            (session_id,),
        ).fetchone()

        if not row:
            return

        turn_id = row["id"]
        user_message = row["user_message"] or ""

        summary = ""
        content = ""
        if transcript_path:
            from .transcript_parser import extract_last_response, extract_transcript_content

            summary = extract_last_response(transcript_path)
            content = extract_transcript_content(transcript_path)

        from ..core.config import load_config
        from ..core.content_filter import redact_content

        config = load_config(repo_path)
        summary = redact_content(summary, config)
        if content:
            content = redact_content(content, config)

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
    finally:
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
    try:
        row = conn.execute(
            "SELECT id, tools_used, files_touched FROM turns WHERE session_id = ? AND turn_status = 'in_progress' ORDER BY turn_number DESC LIMIT 1",
            (session_id,),
        ).fetchone()

        if not row:
            return

        turn_id = row["id"]
        tools = json.loads(row["tools_used"]) if row["tools_used"] else []
        files = json.loads(row["files_touched"]) if row["files_touched"] else []

        from ..core.config import load_config
        from ..core.content_filter import should_skip_file, should_skip_tool

        config = load_config(repo_path)

        if should_skip_tool(tool_name, config):
            return

        if tool_name not in tools:
            tools.append(tool_name)

        if isinstance(tool_input, dict):
            for key in ("file_path", "path"):
                if key in tool_input:
                    fpath = tool_input[key]
                    if should_skip_file(fpath, config):
                        continue
                    if fpath not in files:
                        files.append(fpath)

        conn.execute(
            "UPDATE turns SET tools_used = ?, files_touched = ? WHERE id = ?",
            (json.dumps(tools), json.dumps(files), turn_id),
        )
        conn.commit()
    finally:
        conn.close()
