"""Codex notify ingestion: parse rollout session file and persist turns."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_thread_id(payload: dict[str, Any]) -> str:
    for key in ("thread_id", "threadId", "thread-id", "thread"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_cwd(payload: dict[str, Any]) -> str:
    value = payload.get("cwd")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _find_git_root(cwd: str) -> str | None:
    if not cwd:
        return None
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


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records

    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


def _extract_text_from_content(items: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            chunks.append(text)
    return "\n".join(chunks).strip()


def _parse_session_meta(records: list[dict[str, Any]]) -> dict[str, str]:
    for rec in records:
        if rec.get("type") != "session_meta":
            continue
        payload = rec.get("payload")
        if not isinstance(payload, dict):
            continue
        session_id = payload.get("id")
        if not isinstance(session_id, str) or not session_id.strip():
            continue
        cwd = payload.get("cwd")
        started_at = payload.get("timestamp")
        return {
            "session_id": session_id.strip(),
            "cwd": cwd.strip() if isinstance(cwd, str) else "",
            "started_at": started_at.strip() if isinstance(started_at, str) else _now_iso(),
        }
    return {}


def _extract_turns(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    pending_user: str | None = None

    for rec in records:
        if rec.get("type") != "response_item":
            continue

        payload = rec.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("type") != "message":
            continue

        role = payload.get("role")
        content = payload.get("content")
        if not isinstance(content, list):
            continue

        text = _extract_text_from_content(content)
        if not text:
            continue

        if role == "user":
            pending_user = text
            continue

        if role == "assistant" and pending_user is not None:
            turns.append(
                {
                    "user_message": pending_user,
                    "assistant_summary": text,
                    "timestamp": rec.get("timestamp") if isinstance(rec.get("timestamp"), str) else _now_iso(),
                }
            )
            pending_user = None

    return turns


def _ensure_project(conn, repo_path: str) -> str:
    row = conn.execute("SELECT id FROM projects WHERE repo_path = ?", (repo_path,)).fetchone()
    if row:
        return row["id"]

    project_id = str(uuid4())
    conn.execute(
        "INSERT INTO projects (id, name, repo_path) VALUES (?, ?, ?)",
        (project_id, Path(repo_path).name, repo_path),
    )
    conn.commit()
    return project_id


def _find_session_file(codex_home: Path, *, thread_id: str, cwd: str) -> Path | None:
    sessions_root = codex_home / "sessions"
    if not sessions_root.exists():
        return None

    files = sorted(
        sessions_root.rglob("rollout-*.jsonl"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )

    for file_path in files[:200]:
        records = _read_jsonl(file_path)
        meta = _parse_session_meta(records)
        if not meta:
            continue
        if thread_id and meta.get("session_id") == thread_id:
            return file_path

    for file_path in files[:200]:
        records = _read_jsonl(file_path)
        meta = _parse_session_meta(records)
        if not meta:
            continue
        if cwd and meta.get("cwd") == cwd:
            return file_path

    return files[0] if files else None


def _state_path(repo_path: str) -> Path:
    return Path(repo_path) / ".entirecontext" / "state" / "codex_notify.json"


def _load_state(repo_path: str) -> dict[str, Any]:
    path = _state_path(repo_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(repo_path: str, state: dict[str, Any]) -> None:
    path = _state_path(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _run_upstream_notify(repo_path: str, payload_text: str) -> None:
    state = _load_state(repo_path)
    upstream = state.get("upstream_notify")
    if not isinstance(upstream, list) or not upstream:
        return
    if not all(isinstance(item, str) for item in upstream):
        return

    cmd = [item for item in upstream if item]
    if payload_text.strip():
        cmd = cmd + [payload_text]

    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pass


def ingest_codex_notify_event(payload: dict[str, Any], *, payload_text: str = "") -> None:
    """Ingest a Codex notify event into EntireContext DB."""
    thread_id = _extract_thread_id(payload)
    cwd = _extract_cwd(payload)
    repo_path = _find_git_root(cwd)
    if not repo_path:
        return

    _run_upstream_notify(repo_path, payload_text)

    codex_home = Path(payload.get("codex_home")) if isinstance(payload.get("codex_home"), str) else Path.home() / ".codex"
    session_file = _find_session_file(codex_home, thread_id=thread_id, cwd=cwd)
    if not session_file:
        return

    records = _read_jsonl(session_file)
    meta = _parse_session_meta(records)
    if not meta:
        return
    turns = _extract_turns(records)
    if not turns:
        return

    from ..db import check_and_migrate, get_db
    from ..core.turn import create_turn, save_turn_content

    conn = get_db(repo_path)
    check_and_migrate(conn)

    project_id = _ensure_project(conn, repo_path)
    session_id = meta["session_id"]
    existing_session = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    now = _now_iso()
    if not existing_session:
        conn.execute(
            """INSERT INTO sessions
            (id, project_id, session_type, workspace_path, started_at, last_activity_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, project_id, "codex", meta.get("cwd") or cwd, meta.get("started_at") or now, now),
        )
        conn.commit()

    existing_turns = conn.execute("SELECT COUNT(*) FROM turns WHERE session_id = ?", (session_id,)).fetchone()[0]
    pending = turns[existing_turns:]
    turn_number = existing_turns + 1

    for turn in pending:
        created = create_turn(
            conn,
            session_id=session_id,
            turn_number=turn_number,
            user_message=turn["user_message"],
            assistant_summary=turn["assistant_summary"],
            turn_status="completed",
            model_name="codex-agent",
        )
        content_blob = json.dumps(
            {
                "user_message": turn["user_message"],
                "assistant_summary": turn["assistant_summary"],
                "timestamp": turn.get("timestamp", now),
                "source": "codex_notify",
            },
            ensure_ascii=False,
        )
        save_turn_content(repo_path, conn, created["id"], session_id, content_blob)
        turn_number += 1

    conn.execute(
        "UPDATE sessions SET total_turns = ?, last_activity_at = ?, updated_at = ? WHERE id = ?",
        (existing_turns + len(pending), now, now, session_id),
    )
    conn.commit()
    conn.close()
