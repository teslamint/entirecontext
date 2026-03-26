"""Sync coordinator."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from entirecontext.core.session import create_session, get_session
from entirecontext.core.checkpoint import create_checkpoint
from entirecontext.core.telemetry import detect_current_context, record_operation_event

from .artifact_merge import ShadowMergeError, merge_shadow_artifacts
from .export_flow import run_export
from .git_transport import (
    REMOTE_SHADOW_REF,
    GitCommandError,
    create_worktree,
    fetch_shadow_branch,
    push_shadow_branch,
    remote_shadow_ref_exists,
    remove_worktree,
    reset_hard,
    run_git,
    is_non_fast_forward_push,
)
from .shadow_branch import SHADOW_BRANCH, init_shadow_branch, shadow_branch_exists


class SyncMetadataError(RuntimeError):
    pass


@dataclass(slots=True)
class SyncResult:
    exported_sessions: int = 0
    exported_checkpoints: int = 0
    imported_sessions: int = 0
    imported_checkpoints: int = 0
    duration_ms: int = 0
    committed: bool = False
    pushed: bool = False
    merge_applied: bool = False
    retry_count: int = 0
    error: str | None = None
    warnings: list[dict] = field(default_factory=list)
    phases: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = {
            "exported_sessions": self.exported_sessions,
            "exported_checkpoints": self.exported_checkpoints,
            "imported_sessions": self.imported_sessions,
            "imported_checkpoints": self.imported_checkpoints,
            "duration_ms": self.duration_ms,
            "committed": self.committed,
            "pushed": self.pushed,
            "merge_applied": self.merge_applied,
            "retry_count": self.retry_count,
            "error": self.error,
        }
        if self.warnings:
            data["warnings"] = self.warnings
        if self.phases:
            data["phases"] = self.phases
        return data


def _record_phase(conn, *, source: str, operation_name: str, phase: str, status: str, started_at: float, error: Exception | None = None) -> dict:
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    session_id, turn_id = detect_current_context(conn)
    event = record_operation_event(
        conn,
        source=source,
        operation_name=operation_name,
        phase=phase,
        status=status,
        latency_ms=latency_ms,
        session_id=session_id,
        turn_id=turn_id,
        error_class=type(error).__name__ if error else None,
        message=str(error) if error else None,
    )
    return {"phase": phase, "status": status, "latency_ms": latency_ms, "event_id": event["id"]}


def _update_sync_metadata(conn, *, last_export_at: str | None = None, last_import_at: str | None = None, duration_ms: int | None = None) -> None:
    try:
        conn.execute(
            """
            INSERT INTO sync_metadata (id, last_export_at, last_import_at, sync_status, last_sync_duration_ms)
            VALUES (1, ?, ?, 'idle', ?)
            ON CONFLICT(id) DO UPDATE SET
                last_export_at = COALESCE(excluded.last_export_at, sync_metadata.last_export_at),
                last_import_at = COALESCE(excluded.last_import_at, sync_metadata.last_import_at),
                sync_status = 'idle',
                last_sync_duration_ms = COALESCE(excluded.last_sync_duration_ms, sync_metadata.last_sync_duration_ms)
            """,
            (last_export_at, last_import_at, duration_ms),
        )
        conn.commit()
    except Exception as exc:
        raise SyncMetadataError(str(exc)) from exc


def _checkpoint_exists_exact(conn, checkpoint_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM checkpoints WHERE id = ?", (checkpoint_id,)).fetchone()
    return row is not None


def perform_sync(conn, repo_path: str, config: dict, quiet: bool = False) -> dict:
    start = time.monotonic()
    result = SyncResult()
    should_update_metadata = False
    worktrees_to_remove: list[str] = []

    if not shadow_branch_exists(repo_path):
        init_shadow_branch(repo_path)

    row = conn.execute("SELECT last_export_at FROM sync_metadata WHERE id = 1").fetchone()
    last_export = row["last_export_at"] if row else None

    try:
        phase_start = time.perf_counter()
        worktree_path = create_worktree(repo_path, SHADOW_BRANCH, "ec-sync-")
        worktrees_to_remove.append(worktree_path)
        result.phases.append(_record_phase(conn, source="sync", operation_name="perform_sync", phase="prepare", status="ok", started_at=phase_start))

        phase_start = time.perf_counter()
        export_result = run_export(conn, repo_path, worktree_path, last_export=last_export, config=config)
        result.exported_sessions = export_result.exported_sessions
        result.exported_checkpoints = export_result.exported_checkpoints
        result.committed = export_result.committed
        result.phases.append(_record_phase(conn, source="sync", operation_name="perform_sync", phase="export", status="ok", started_at=phase_start))

        push_on_sync = config.get("push_on_sync", True)
        if result.committed and push_on_sync:
            phase_start = time.perf_counter()
            push_result = push_shadow_branch(worktree_path)
            result.pushed = push_result.returncode == 0
            if result.pushed:
                result.phases.append(_record_phase(conn, source="sync", operation_name="perform_sync", phase="push", status="ok", started_at=phase_start))
            elif is_non_fast_forward_push(push_result):
                result.retry_count = 1
                fetch_shadow_branch(repo_path)
                if not remote_shadow_ref_exists(repo_path):
                    raise ShadowMergeError(f"remote shadow snapshot not found: {REMOTE_SHADOW_REF}")

                local_snapshot_path = create_worktree(repo_path, SHADOW_BRANCH, "ec-sync-local-", detach=True)
                remote_snapshot_path = create_worktree(repo_path, REMOTE_SHADOW_REF, "ec-sync-remote-", detach=True)
                worktrees_to_remove.extend([local_snapshot_path, remote_snapshot_path])

                reset_hard(worktree_path, REMOTE_SHADOW_REF)

                retry_start = time.perf_counter()
                merge_shadow_artifacts(Path(local_snapshot_path), Path(remote_snapshot_path), Path(worktree_path))
                result.merge_applied = True
                run_git(
                    ["add", "-A"],
                    cwd=worktree_path,
                    check=True,
                    timeout=10,
                )
                from .git_transport import commit_if_changed

                commit_if_changed(
                    worktree_path,
                    f"ec sync merge: {result.exported_sessions} sessions, {result.exported_checkpoints} checkpoints",
                )
                retry_push = push_shadow_branch(worktree_path)
                result.pushed = retry_push.returncode == 0
                if not result.pushed:
                    retry_error = retry_push.stderr.strip() or retry_push.stdout.strip() or "git push retry failed"
                    raise GitCommandError(f"git push retry failed: {retry_error}")
                result.phases.append(
                    _record_phase(conn, source="sync", operation_name="perform_sync", phase="retry_merge", status="ok", started_at=retry_start)
                )
            else:
                result.phases.append(
                    _record_phase(
                        conn,
                        source="sync",
                        operation_name="perform_sync",
                        phase="push",
                        status="warning",
                        started_at=phase_start,
                        error=GitCommandError(push_result.stderr.strip() or push_result.stdout.strip() or "push failed"),
                    )
                )

        should_update_metadata = result.error is None and (
            not push_on_sync or result.pushed or not result.committed
        )
    except (GitCommandError, ShadowMergeError, SyncMetadataError, ValueError) as exc:
        result.error = str(exc)
        result.phases.append(
            _record_phase(conn, source="sync", operation_name="perform_sync", phase="finalize", status="error", started_at=time.perf_counter(), error=exc)
        )
    except Exception as exc:
        result.error = str(exc)
        result.phases.append(
            _record_phase(conn, source="sync", operation_name="perform_sync", phase="finalize", status="error", started_at=time.perf_counter(), error=exc)
        )
    finally:
        result.duration_ms = int((time.monotonic() - start) * 1000)
        if should_update_metadata:
            now = datetime.now(timezone.utc).isoformat()
            _update_sync_metadata(conn, last_export_at=now, duration_ms=result.duration_ms)

        for worktree_path in reversed(worktrees_to_remove):
            remove_worktree(repo_path, worktree_path)

    return result.to_dict()


def perform_pull(conn, repo_path: str, config: dict, quiet: bool = False) -> dict:
    result = SyncResult()
    worktree_path: str | None = None

    fetch_shadow_branch(repo_path)
    if not remote_shadow_ref_exists(repo_path):
        result.error = "no_shadow_branch"
        return result.to_dict()

    project_row = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
    project_id = project_row["id"] if project_row else None

    try:
        worktree_path = create_worktree(repo_path, REMOTE_SHADOW_REF, "ec-pull-", detach=True)

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
        result.imported_sessions = session_count

        checkpoints_dir = Path(worktree_path) / "checkpoints"
        checkpoint_count = 0
        if checkpoints_dir.exists():
            # Phase 1: Load all new checkpoint data
            pending: dict[str, dict] = {}
            for checkpoint_file in checkpoints_dir.glob("*.json"):
                try:
                    checkpoint_data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
                    checkpoint_id = checkpoint_data["id"]
                    if not _checkpoint_exists_exact(conn, checkpoint_id):
                        pending[checkpoint_id] = checkpoint_data
                except (json.JSONDecodeError, KeyError):
                    continue

            # Phase 2: Topological sort — parents before children
            ordered: list[dict] = []
            states: dict[str, int] = {}

            for cid in pending:
                if states.get(cid) == 2:
                    continue

                stack: list[tuple[str, bool]] = [(cid, False)]
                while stack:
                    current_id, expanded = stack.pop()
                    if current_id not in pending:
                        continue

                    state = states.get(current_id, 0)
                    if expanded:
                        if state != 2:
                            states[current_id] = 2
                            ordered.append(pending[current_id])
                        continue
                    if state == 2:
                        continue
                    if state == 1:
                        continue

                    states[current_id] = 1
                    stack.append((current_id, True))

                    parent_id = pending[current_id].get("parent_checkpoint_id")
                    if parent_id and parent_id in pending and states.get(parent_id) != 2:
                        stack.append((parent_id, False))

            # Phase 3: Insert in dependency order
            for checkpoint_data in ordered:
                try:
                    files_snapshot = checkpoint_data.get("files_snapshot")
                    if isinstance(files_snapshot, str):
                        try:
                            files_snapshot = json.loads(files_snapshot)
                        except json.JSONDecodeError:
                            pass
                    metadata = checkpoint_data.get("metadata")
                    if isinstance(metadata, str):
                        try:
                            metadata = json.loads(metadata)
                        except json.JSONDecodeError:
                            pass
                    parent_id = checkpoint_data.get("parent_checkpoint_id")
                    if parent_id and parent_id not in pending and not _checkpoint_exists_exact(conn, parent_id):
                        parent_id = None
                    create_checkpoint(
                        conn,
                        session_id=checkpoint_data["session_id"],
                        git_commit_hash=checkpoint_data["git_commit_hash"],
                        git_branch=checkpoint_data.get("git_branch"),
                        files_snapshot=files_snapshot,
                        diff_summary=checkpoint_data.get("diff_summary"),
                        parent_checkpoint_id=parent_id,
                        metadata=metadata,
                        checkpoint_id=checkpoint_data["id"],
                    )
                    checkpoint_count += 1
                except (json.JSONDecodeError, KeyError):
                    continue
        result.imported_checkpoints = checkpoint_count

        now = datetime.now(timezone.utc).isoformat()
        _update_sync_metadata(conn, last_import_at=now)
    except (GitCommandError, SyncMetadataError) as exc:
        result.error = str(exc)
    except Exception as exc:
        result.error = str(exc)
    finally:
        if worktree_path:
            remove_worktree(repo_path, worktree_path)

    return result.to_dict()
