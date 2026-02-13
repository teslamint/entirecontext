"""Sync commands."""

from __future__ import annotations

import typer
from rich.console import Console

from . import app

console = Console()


@app.command("sync")
def sync(
    no_filter: bool = typer.Option(False, "--no-filter", help="Skip secret filtering"),
):
    """Export to shadow branch and push."""
    import subprocess
    import tempfile

    from ..core.project import find_git_root, get_project
    from ..db import get_db
    from ..sync.exporter import export_checkpoints, export_sessions, update_manifest
    from ..sync.shadow_branch import SHADOW_BRANCH, init_shadow_branch, shadow_branch_exists

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    project = get_project(repo_path)
    if not project:
        console.print("[yellow]Not initialized. Run 'ec init'.[/yellow]")
        raise typer.Exit(1)

    console.print("[bold]Syncing to shadow branch...[/bold]")

    if not shadow_branch_exists(repo_path):
        console.print("  Initializing shadow branch...")
        init_shadow_branch(repo_path)

    conn = get_db(repo_path)

    last_export = None
    row = conn.execute("SELECT last_export_at FROM sync_metadata WHERE id = 1").fetchone()
    if row:
        last_export = row["last_export_at"]

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
        console.print(f"  Exported {session_count} sessions")

        cp_count = export_checkpoints(conn, worktree_path, since=last_export)
        console.print(f"  Exported {cp_count} checkpoints")

        update_manifest(conn, worktree_path)
        console.print("  Updated manifest")

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
            console.print("  Committed to shadow branch")

            push_result = subprocess.run(
                ["git", "push", "origin", SHADOW_BRANCH],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if push_result.returncode == 0:
                console.print("  Pushed to remote")
            else:
                console.print("[yellow]  Push skipped (no remote or push failed)[/yellow]")
        else:
            console.print("[dim]  No changes to commit[/dim]")

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO sync_metadata (id, last_export_at, sync_status) VALUES (1, ?, 'idle')",
            (now,),
        )
        conn.commit()

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Sync failed: {e.stderr.strip() if e.stderr else str(e)}[/red]")
        raise typer.Exit(1)
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", worktree_path],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        conn.close()

    console.print("[green]Sync complete.[/green]")


@app.command("pull")
def pull():
    """Fetch shadow branch and import."""
    import json
    import subprocess
    import tempfile
    from pathlib import Path

    from ..core.project import find_git_root, get_project
    from ..core.session import create_session, get_session
    from ..db import get_db
    from ..sync.shadow_branch import SHADOW_BRANCH, shadow_branch_exists

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    project = get_project(repo_path)
    if not project:
        console.print("[yellow]Not initialized. Run 'ec init'.[/yellow]")
        raise typer.Exit(1)

    if not shadow_branch_exists(repo_path):
        console.print("[yellow]No shadow branch found. Run 'ec sync' first.[/yellow]")
        raise typer.Exit(1)

    console.print("[bold]Pulling from shadow branch...[/bold]")

    subprocess.run(
        ["git", "fetch", "origin", SHADOW_BRANCH],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    worktree_path = tempfile.mkdtemp(prefix="ec-pull-")
    conn = get_db(repo_path)

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
                            project_id=meta.get("project_id", project["id"]),
                            session_type=meta.get("session_type", "claude"),
                            session_id=session_id,
                        )
                        session_count += 1
                except (json.JSONDecodeError, KeyError):
                    continue

        checkpoints_dir = Path(worktree_path) / "checkpoints"
        cp_count = 0
        if checkpoints_dir.exists():
            from ..core.checkpoint import create_checkpoint, get_checkpoint

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

        console.print(f"  Imported {session_count} sessions")
        console.print(f"  Imported {cp_count} checkpoints")

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO sync_metadata (id, last_import_at, sync_status) VALUES (1, ?, 'idle')",
            (now,),
        )
        conn.commit()

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Pull failed: {e.stderr.strip() if e.stderr else str(e)}[/red]")
        raise typer.Exit(1)
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", worktree_path],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        conn.close()

    console.print("[green]Pull complete.[/green]")
