"""App-level merge for shadow branch sync (NOT git 3-way merge)."""

from __future__ import annotations

import json
from pathlib import Path


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
        else:
            merged["sessions"][s_id] = s_data

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
            except json.JSONDecodeError:
                continue

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
