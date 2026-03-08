"""Reusable sync engine: export/import logic decoupled from CLI."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from entirecontext.core.checkpoint import create_checkpoint, get_checkpoint
from entirecontext.core.session import create_session, get_session
from entirecontext.sync.exporter import export_checkpoints, export_sessions, update_manifest
from entirecontext.sync.merge import (
    merge_checkpoint_files,
    merge_manifests,
    merge_session_meta,
    merge_transcripts,
)
from entirecontext.sync.security import get_security_config
from entirecontext.sync.shadow_branch import SHADOW_BRANCH, init_shadow_branch, shadow_branch_exists

REMOTE_SHADOW_REF = f"origin/{SHADOW_BRANCH}"


def _run_git(args: list[str], cwd: str, *, check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def _create_worktree(repo_path: str, ref: str, prefix: str, *, detach: bool = False) -> str:
    worktree_path = tempfile.mkdtemp(prefix=prefix)
    command = ["worktree", "add"]
    if detach:
        command.append("--detach")
    command.extend([worktree_path, ref])
    _run_git(command, cwd=repo_path, check=True)
    return worktree_path


def _remove_worktree(repo_path: str, worktree_path: str) -> None:
    _run_git(["worktree", "remove", "--force", worktree_path], cwd=repo_path, check=False, timeout=10)


def _remote_shadow_ref_exists(repo_path: str) -> bool:
    result = _run_git(
        ["rev-parse", "--verify", f"refs/remotes/{REMOTE_SHADOW_REF}"],
        cwd=repo_path,
        check=False,
    )
    return result.returncode == 0


def _fetch_shadow_branch(repo_path: str) -> subprocess.CompletedProcess:
    return _run_git(["fetch", "origin", SHADOW_BRANCH], cwd=repo_path, check=False, timeout=60)


def _read_json_file(path: Path, artifact_name: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing {artifact_name}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed {artifact_name}: {path}") from exc


def _iter_session_ids(*roots: Path) -> set[str]:
    session_ids: set[str] = set()
    for root in roots:
        sessions_dir = root / "sessions"
        if not sessions_dir.exists():
            continue
        for session_dir in sessions_dir.iterdir():
            if session_dir.is_dir():
                session_ids.add(session_dir.name)
    return session_ids


def _merge_shadow_artifacts(local_root: Path, remote_root: Path, output_root: Path) -> None:
    local_manifest = _read_json_file(local_root / "manifest.json", "manifest.json")
    remote_manifest = _read_json_file(remote_root / "manifest.json", "manifest.json")
    merged_manifest = merge_manifests(local_manifest, remote_manifest)
    (output_root / "manifest.json").write_text(json.dumps(merged_manifest, indent=2), encoding="utf-8")

    session_ids = _iter_session_ids(local_root, remote_root)
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
                _read_json_file(local_meta_path, "sessions/<id>/meta.json"),
                _read_json_file(remote_meta_path, "sessions/<id>/meta.json"),
            )
        elif local_meta_path.exists():
            merged_meta = _read_json_file(local_meta_path, "sessions/<id>/meta.json")
        elif remote_meta_path.exists():
            merged_meta = _read_json_file(remote_meta_path, "sessions/<id>/meta.json")
        else:
            merged_meta = None

        if merged_meta is not None:
            (output_session_dir / "meta.json").write_text(json.dumps(merged_meta, indent=2), encoding="utf-8")

        local_transcript_path = local_session_dir / "transcript.jsonl"
        remote_transcript_path = remote_session_dir / "transcript.jsonl"
        if local_transcript_path.exists() or remote_transcript_path.exists():
            local_transcript = local_transcript_path.read_text(encoding="utf-8") if local_transcript_path.exists() else ""
            remote_transcript = remote_transcript_path.read_text(encoding="utf-8") if remote_transcript_path.exists() else ""
            merged_transcript = merge_transcripts(local_transcript, remote_transcript)
            (output_session_dir / "transcript.jsonl").write_text(merged_transcript, encoding="utf-8")

    merge_checkpoint_files(local_root / "checkpoints", remote_root / "checkpoints", output_root / "checkpoints")


def _commit_if_changed(worktree_path: str, message: str) -> bool:
    _run_git(["add", "-A"], cwd=worktree_path, check=True, timeout=10)
    status = _run_git(["status", "--porcelain"], cwd=worktree_path, check=False, timeout=5)
    if not status.stdout.strip():
        return False
    _run_git(["commit", "-m", message], cwd=worktree_path, check=True)
    return True


def _is_non_fast_forward_push(push_result: subprocess.CompletedProcess) -> bool:
    output = f"{push_result.stdout}\n{push_result.stderr}".lower()
    return push_result.returncode != 0 and (
        "non-fast-forward" in output or "fetch first" in output or "failed to push some refs" in output
    )


def perform_sync(conn, repo_path: str, config: dict, quiet: bool = False) -> dict:
    """Export sessions/checkpoints to shadow branch.

    Returns dict with: exported_sessions, exported_checkpoints, duration_ms, pushed, committed,
    merge_applied, retry_count, error
    """
    start = time.monotonic()
    result: dict = {
        "exported_sessions": 0,
        "exported_checkpoints": 0,
        "duration_ms": 0,
        "committed": False,
        "pushed": False,
        "merge_applied": False,
        "retry_count": 0,
        "error": None,
    }
    should_update_metadata = False
    worktrees_to_remove: list[str] = []

    if not shadow_branch_exists(repo_path):
        init_shadow_branch(repo_path)

    row = conn.execute("SELECT last_export_at FROM sync_metadata WHERE id = 1").fetchone()
    last_export = row["last_export_at"] if row else None

    try:
        worktree_path = _create_worktree(repo_path, SHADOW_BRANCH, "ec-sync-")
        worktrees_to_remove.append(worktree_path)

        filter_enabled, filter_patterns = get_security_config(config)
        session_count = export_sessions(
            conn,
            repo_path,
            worktree_path,
            since=last_export,
            filter_enabled=filter_enabled,
            filter_patterns=filter_patterns,
        )
        result["exported_sessions"] = session_count

        cp_count = export_checkpoints(conn, worktree_path, since=last_export)
        result["exported_checkpoints"] = cp_count

        update_manifest(conn, worktree_path)
        result["committed"] = _commit_if_changed(
            worktree_path,
            f"ec sync: {session_count} sessions, {cp_count} checkpoints",
        )

        push_on_sync = config.get("push_on_sync", True)
        if result["committed"] and push_on_sync:
            push_result = _run_git(["push", "origin", SHADOW_BRANCH], cwd=worktree_path, check=False, timeout=60)
            result["pushed"] = push_result.returncode == 0

            if not result["pushed"] and _is_non_fast_forward_push(push_result):
                result["retry_count"] = 1
                _fetch_shadow_branch(repo_path)
                if not _remote_shadow_ref_exists(repo_path):
                    raise ValueError(f"remote shadow snapshot not found: {REMOTE_SHADOW_REF}")

                local_snapshot_path = _create_worktree(repo_path, "HEAD", "ec-sync-local-", detach=True)
                remote_snapshot_path = _create_worktree(repo_path, REMOTE_SHADOW_REF, "ec-sync-remote-", detach=True)
                worktrees_to_remove.extend([local_snapshot_path, remote_snapshot_path])

                _run_git(["reset", "--hard", REMOTE_SHADOW_REF], cwd=worktree_path, check=True)
                _merge_shadow_artifacts(Path(local_snapshot_path), Path(remote_snapshot_path), Path(worktree_path))
                result["merge_applied"] = True
                _commit_if_changed(
                    worktree_path,
                    f"ec sync merge: {session_count} sessions, {cp_count} checkpoints",
                )

                retry_push = _run_git(["push", "origin", SHADOW_BRANCH], cwd=worktree_path, check=False, timeout=60)
                result["pushed"] = retry_push.returncode == 0
                if not result["pushed"]:
                    retry_error = retry_push.stderr.strip() or retry_push.stdout.strip() or "git push retry failed"
                    raise RuntimeError(f"git push retry failed: {retry_error}")

        should_update_metadata = result["error"] is None and (not push_on_sync or result["pushed"] or not result["committed"])

    except subprocess.CalledProcessError as e:
        result["error"] = e.stderr.strip() if e.stderr else str(e)
    except Exception as e:
        result["error"] = str(e)
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        result["duration_ms"] = result["duration_ms"] or duration_ms
        if should_update_metadata:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO sync_metadata (id, last_export_at, last_sync_duration_ms, sync_status) "
                "VALUES (1, ?, ?, 'idle')",
                (now, result["duration_ms"]),
            )
            conn.commit()

        for worktree_path in reversed(worktrees_to_remove):
            _remove_worktree(repo_path, worktree_path)

        result["duration_ms"] = result["duration_ms"] or int((time.monotonic() - start) * 1000)

    return result


def perform_pull(conn, repo_path: str, config: dict, quiet: bool = False) -> dict:
    """Import sessions/checkpoints from shadow branch.

    Returns dict with: imported_sessions, imported_checkpoints, error
    """
    result: dict = {
        "imported_sessions": 0,
        "imported_checkpoints": 0,
        "error": None,
    }
    worktree_path: str | None = None

    _fetch_shadow_branch(repo_path)
    if not _remote_shadow_ref_exists(repo_path):
        result["error"] = "no_shadow_branch"
        return result

    project_row = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
    project_id = project_row["id"] if project_row else None

    try:
        worktree_path = _create_worktree(repo_path, REMOTE_SHADOW_REF, "ec-pull-", detach=True)

        sessions_dir = Path(worktree_path) / "sessions"
        session_count = 0
        if sessions_dir.exists():
            for session_dir in sessions_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                meta_path = session_dir / "meta.json"
                if not meta_path.exists():
                    continue
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    session_id = meta["id"]
                    existing = get_session(conn, session_id)
                    if not existing:
                        create_session(
                            conn,
                            project_id=meta.get("project_id", project_id),
                            session_type=meta.get("session_type", "claude"),
                            session_id=session_id,
                        )
                        session_count += 1
                except (json.JSONDecodeError, KeyError):
                    continue
        result["imported_sessions"] = session_count

        checkpoints_dir = Path(worktree_path) / "checkpoints"
        cp_count = 0
        if checkpoints_dir.exists():
            for cp_file in checkpoints_dir.glob("*.json"):
                try:
                    cp_data = json.loads(cp_file.read_text(encoding="utf-8"))
                    cp_id = cp_data["id"]
                    existing = get_checkpoint(conn, cp_id)
                    if not existing:
                        files_snapshot = cp_data.get("files_snapshot")
                        if isinstance(files_snapshot, str):
                            try:
                                files_snapshot = json.loads(files_snapshot)
                            except json.JSONDecodeError:
                                pass
                        metadata = cp_data.get("metadata")
                        if isinstance(metadata, str):
                            try:
                                metadata = json.loads(metadata)
                            except json.JSONDecodeError:
                                pass
                        create_checkpoint(
                            conn,
                            session_id=cp_data["session_id"],
                            git_commit_hash=cp_data["git_commit_hash"],
                            git_branch=cp_data.get("git_branch"),
                            files_snapshot=files_snapshot,
                            diff_summary=cp_data.get("diff_summary"),
                            parent_checkpoint_id=cp_data.get("parent_checkpoint_id"),
                            metadata=metadata,
                            checkpoint_id=cp_id,
                        )
                        cp_count += 1
                except (json.JSONDecodeError, KeyError):
                    continue
        result["imported_checkpoints"] = cp_count

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO sync_metadata (id, last_import_at, sync_status) VALUES (1, ?, 'idle')",
            (now,),
        )
        conn.commit()

    except subprocess.CalledProcessError as e:
        result["error"] = e.stderr.strip() if e.stderr else str(e)
    except Exception as e:
        result["error"] = str(e)
    finally:
        if worktree_path:
            _remove_worktree(repo_path, worktree_path)

    return result
