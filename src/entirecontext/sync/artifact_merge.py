"""Artifact merge helpers for shadow snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from .git_transport import read_json_file
from .merge import merge_checkpoint_files, merge_manifests, merge_session_meta, merge_transcripts


class ShadowMergeError(RuntimeError):
    pass


def iter_session_ids(*roots: Path) -> set[str]:
    session_ids: set[str] = set()
    for root in roots:
        sessions_dir = root / "sessions"
        if not sessions_dir.exists():
            continue
        for session_dir in sessions_dir.iterdir():
            if session_dir.is_dir():
                session_ids.add(session_dir.name)
    return session_ids


def merge_shadow_artifacts(local_root: Path, remote_root: Path, output_root: Path) -> None:
    try:
        local_manifest = read_json_file(local_root / "manifest.json", "manifest.json")
        remote_manifest = read_json_file(remote_root / "manifest.json", "manifest.json")
        merged_manifest = merge_manifests(local_manifest, remote_manifest)
        (output_root / "manifest.json").write_text(json.dumps(merged_manifest, indent=2), encoding="utf-8")

        session_ids = iter_session_ids(local_root, remote_root)
        session_ids.update(local_manifest.get("sessions", {}).keys())
        session_ids.update(remote_manifest.get("sessions", {}).keys())

        for session_id in session_ids:
            local_session_dir = local_root / "sessions" / session_id
            remote_session_dir = remote_root / "sessions" / session_id
            output_session_dir = output_root / "sessions" / session_id
            output_session_dir.mkdir(parents=True, exist_ok=True)

            local_meta_path = local_session_dir / "meta.json"
            remote_meta_path = remote_session_dir / "meta.json"
            if local_meta_path.exists() and remote_meta_path.exists():
                merged_meta = merge_session_meta(
                    read_json_file(local_meta_path, "sessions/<id>/meta.json"),
                    read_json_file(remote_meta_path, "sessions/<id>/meta.json"),
                )
            elif local_meta_path.exists():
                merged_meta = read_json_file(local_meta_path, "sessions/<id>/meta.json")
            elif remote_meta_path.exists():
                merged_meta = read_json_file(remote_meta_path, "sessions/<id>/meta.json")
            else:
                merged_meta = None

            if merged_meta is not None:
                (output_session_dir / "meta.json").write_text(json.dumps(merged_meta, indent=2), encoding="utf-8")

            local_transcript_path = local_session_dir / "transcript.jsonl"
            remote_transcript_path = remote_session_dir / "transcript.jsonl"
            if local_transcript_path.exists() or remote_transcript_path.exists():
                local_transcript = local_transcript_path.read_text(encoding="utf-8") if local_transcript_path.exists() else ""
                remote_transcript = (
                    remote_transcript_path.read_text(encoding="utf-8") if remote_transcript_path.exists() else ""
                )
                merged_transcript = merge_transcripts(local_transcript, remote_transcript)
                (output_session_dir / "transcript.jsonl").write_text(merged_transcript, encoding="utf-8")

        merge_checkpoint_files(local_root / "checkpoints", remote_root / "checkpoints", output_root / "checkpoints")
    except Exception as exc:
        raise ShadowMergeError(str(exc)) from exc
