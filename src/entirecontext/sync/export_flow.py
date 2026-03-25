"""Export flow helpers."""

from __future__ import annotations

from dataclasses import dataclass

from entirecontext.sync.exporter import export_checkpoints, export_sessions, update_manifest

from .git_transport import commit_if_changed
from .security import get_security_config


@dataclass(slots=True)
class ExportResult:
    exported_sessions: int
    exported_checkpoints: int
    committed: bool


def run_export(conn, repo_path: str, worktree_path: str, *, last_export: str | None, config: dict) -> ExportResult:
    filter_enabled, filter_patterns = get_security_config(config)
    session_count = export_sessions(
        conn,
        repo_path,
        worktree_path,
        since=last_export,
        filter_enabled=filter_enabled,
        filter_patterns=filter_patterns,
    )
    checkpoint_count = export_checkpoints(conn, worktree_path, since=last_export)
    update_manifest(conn, worktree_path)
    committed = commit_if_changed(
        worktree_path,
        f"ec sync: {session_count} sessions, {checkpoint_count} checkpoints",
    )
    return ExportResult(
        exported_sessions=session_count,
        exported_checkpoints=checkpoint_count,
        committed=committed,
    )
