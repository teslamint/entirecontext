"""App-level merge for shadow branch sync (NOT git 3-way merge)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _is_non_null(value) -> bool:
    return value is not None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def merge_session_meta(local: dict, remote: dict) -> dict:
    """Merge session meta.json using artifact-level precedence rules."""
    local_turns = local.get("total_turns")
    remote_turns = remote.get("total_turns")

    if (remote_turns or 0) > (local_turns or 0):
        merged = dict(remote)
        other = local
        turns_tied = False
    else:
        merged = dict(local)
        other = remote
        turns_tied = (local_turns or 0) == (remote_turns or 0)

    if turns_tied:
        for key, value in other.items():
            if _is_non_null(value) and not _is_non_null(merged.get(key)):
                merged[key] = value

    local_started = _parse_datetime(local.get("started_at"))
    remote_started = _parse_datetime(remote.get("started_at"))
    if local_started and remote_started:
        merged["started_at"] = local["started_at"] if local_started <= remote_started else remote["started_at"]
    elif _is_non_null(local.get("started_at")) or _is_non_null(remote.get("started_at")):
        merged["started_at"] = local.get("started_at") or remote.get("started_at")

    local_ended = _parse_datetime(local.get("ended_at"))
    remote_ended = _parse_datetime(remote.get("ended_at"))
    if local_ended and remote_ended:
        merged["ended_at"] = local["ended_at"] if local_ended >= remote_ended else remote["ended_at"]
    elif _is_non_null(local.get("ended_at")) or _is_non_null(remote.get("ended_at")):
        merged["ended_at"] = local.get("ended_at") or remote.get("ended_at")

    return merged


def merge_manifests(local: dict, remote: dict) -> dict:
    """Merge two manifest.json files by key union."""
    merged = {
        "version": max(local.get("version", 1), remote.get("version", 1)),
        "checkpoints": {},
        "sessions": {},
    }

    for cp_id, cp_data in local.get("checkpoints", {}).items():
        merged["checkpoints"][cp_id] = cp_data
    for cp_id, cp_data in remote.get("checkpoints", {}).items():
        merged["checkpoints"][cp_id] = cp_data

    for s_id, s_data in local.get("sessions", {}).items():
        merged["sessions"][s_id] = s_data
    for s_id, s_data in remote.get("sessions", {}).items():
        if s_id in merged["sessions"]:
            existing = merged["sessions"][s_id]
            if s_data.get("total_turns", 0) > existing.get("total_turns", 0):
                merged["sessions"][s_id] = s_data
            elif s_data.get("total_turns", 0) == existing.get("total_turns", 0):
                merged["sessions"][s_id] = merge_session_meta(existing, s_data)
        else:
            merged["sessions"][s_id] = s_data

    if local.get("updated_at") or remote.get("updated_at"):
        local_updated = _parse_datetime(local.get("updated_at"))
        remote_updated = _parse_datetime(remote.get("updated_at"))
        if local_updated and remote_updated:
            merged["updated_at"] = local["updated_at"] if local_updated >= remote_updated else remote["updated_at"]
        else:
            merged["updated_at"] = local.get("updated_at") or remote.get("updated_at")

    return merged


def merge_transcripts(local_content: str, remote_content: str) -> str:
    """Merge two JSONL transcript files by turn_id dedup."""
    seen_ids: set[str] = set()
    merged_lines: list[str] = []

    for content in [local_content, remote_content]:
        for line in content.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                turn_id = entry.get("id", "")
                if turn_id and turn_id not in seen_ids:
                    seen_ids.add(turn_id)
                    merged_lines.append(line)
            except json.JSONDecodeError as exc:
                raise ValueError("malformed transcript.jsonl entry") from exc

    return "\n".join(merged_lines) + "\n" if merged_lines else ""


def merge_checkpoint_files(local_path: Path, remote_path: Path, output_path: Path) -> None:
    """Merge checkpoint directories — file-level, same ID = skip (idempotent)."""
    output_path.mkdir(parents=True, exist_ok=True)

    for source_dir in [local_path, remote_path]:
        if not source_dir.exists():
            continue
        for f in source_dir.glob("*.json"):
            dest = output_path / f.name
            if not dest.exists():
                dest.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
