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
from entirecontext.sync.shadow_branch import SHADOW_BRANCH, init_shadow_branch, shadow_branch_exists


def perform_sync(conn, repo_path: str, config: dict, quiet: bool = False) -> dict:
    """Export sessions/checkpoints to shadow branch.

    Returns dict with: exported_sessions, exported_checkpoints, duration_ms, pushed, committed, error
    """
    start = time.monotonic()
    result: dict = {
        "exported_sessions": 0,
        "exported_checkpoints": 0,
        "duration_ms": 0,
        "committed": False,
        "pushed": False,
        "error": None,
    }

    if not shadow_branch_exists(repo_path):
        init_shadow_branch(repo_path)

    row = conn.execute("SELECT last_export_at FROM sync_metadata WHERE id = 1").fetchone()
    last_export = row["last_export_at"] if row else None

    worktree_path = tempfile.mkdtemp(prefix="ec-sync-")
    try:
        subprocess.run(
            ["git", "worktree", "add", worktree_path, SHADOW_BRANCH],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )

        session_count = export_sessions(conn, repo_path, worktree_path, since=last_export)
        result["exported_sessions"] = session_count

        cp_count = export_checkpoints(conn, worktree_path, since=last_export)
        result["exported_checkpoints"] = cp_count

        update_manifest(conn, worktree_path)

        subprocess.run(
            ["git", "add", "-A"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=5,
        )

        if status.stdout.strip():
            subprocess.run(
                ["git", "commit", "-m", f"ec sync: {session_count} sessions, {cp_count} checkpoints"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            result["committed"] = True

            push_on_sync = config.get("push_on_sync", True)
            if push_on_sync:
                push_result = subprocess.run(
                    ["git", "push", "origin", SHADOW_BRANCH],
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                result["pushed"] = push_result.returncode == 0

        now = datetime.now(timezone.utc).isoformat()
        duration_ms = int((time.monotonic() - start) * 1000)
        result["duration_ms"] = duration_ms
        conn.execute(
            "INSERT OR REPLACE INTO sync_metadata (id, last_export_at, last_sync_duration_ms, sync_status) "
            "VALUES (1, ?, ?, 'idle')",
            (now, duration_ms),
        )
        conn.commit()

    except subprocess.CalledProcessError as e:
        result["error"] = e.stderr.strip() if e.stderr else str(e)
    except Exception as e:
        result["error"] = str(e)
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", worktree_path],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
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

    if not shadow_branch_exists(repo_path):
        result["error"] = "no_shadow_branch"
        return result

    subprocess.run(
        ["git", "fetch", "origin", SHADOW_BRANCH],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    project_row = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
    project_id = project_row["id"] if project_row else None

    worktree_path = tempfile.mkdtemp(prefix="ec-pull-")
    try:
        subprocess.run(
            ["git", "worktree", "add", worktree_path, SHADOW_BRANCH],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )

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
        subprocess.run(
            ["git", "worktree", "remove", "--force", worktree_path],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    return result
