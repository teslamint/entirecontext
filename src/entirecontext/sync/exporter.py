"""Export from SQLite to shadow branch files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .security import filter_export_data


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _filter_value(value: Any, patterns: list[str] | None, *, filter_keys: bool = False) -> Any:
    if isinstance(value, str):
        return filter_export_data(value, patterns)
    if isinstance(value, list):
        return [_filter_value(item, patterns, filter_keys=filter_keys) for item in value]
    if isinstance(value, dict):
        return {
            _filter_value(key, patterns, filter_keys=filter_keys) if filter_keys else key: _filter_value(
                item, patterns, filter_keys=filter_keys
            )
            for key, item in value.items()
        }
    return value


def _filter_json_text(value: str, patterns: list[str] | None, *, filter_keys: bool = False) -> str:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return filter_export_data(value, patterns)
    filtered = _filter_value(parsed, patterns, filter_keys=filter_keys)
    return json.dumps(filtered) if filtered != parsed else value


def export_sessions(
    conn,
    repo_path: str,
    worktree_path: str,
    since: str | None = None,
    filter_enabled: bool = True,
    filter_patterns: list[str] | None = None,
) -> int:
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
        if filter_enabled:
            for field in ("session_title", "session_summary"):
                meta[field] = _filter_value(meta[field], filter_patterns)
        (session_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        turns = conn.execute(
            "SELECT * FROM turns WHERE session_id = ? ORDER BY turn_number",
            (session_id,),
        ).fetchall()

        transcript_lines = []
        for turn in turns:
            turn_dict = dict(turn)
            if filter_enabled:
                for field in ("user_message", "assistant_summary"):
                    if turn_dict.get(field):
                        turn_dict[field] = filter_export_data(turn_dict[field], filter_patterns, filter_enabled)
            transcript_lines.append(json.dumps(turn_dict))

        (session_dir / "transcript.jsonl").write_text(
            "\n".join(transcript_lines) + "\n" if transcript_lines else "",
            encoding="utf-8",
        )
        count += 1

    return count


def export_checkpoints(
    conn,
    worktree_path: str,
    since: str | None = None,
    filter_enabled: bool = True,
    filter_patterns: list[str] | None = None,
) -> int:
    """Export checkpoints to shadow branch worktree. Returns count."""
    query = "SELECT * FROM checkpoints"
    params: list[Any] = []
    cutoff = _utc_datetime(since) if since else None
    if since:
        # SQLite rounds fractional seconds; retain ties for exact comparison below.
        query += " WHERE julianday(created_at) >= julianday(?)"
        params.append(since)

    rows = conn.execute(query, params).fetchall()
    checkpoints_dir = Path(worktree_path) / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for row in rows:
        cp = dict(row)
        if cutoff is not None and _utc_datetime(cp["created_at"]) <= cutoff:
            continue
        if filter_enabled:
            cp["diff_summary"] = _filter_value(cp.get("diff_summary"), filter_patterns)
            for field in ("files_snapshot", "agent_state", "metadata"):
                if cp.get(field):
                    cp[field] = _filter_json_text(cp[field], filter_patterns, filter_keys=field == "metadata")
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
