"""Rewind commands."""

from __future__ import annotations

import typer
from rich.console import Console

from . import app

console = Console()


@app.command("rewind")
def rewind(
    checkpoint_id: str = typer.Argument(..., help="Checkpoint ID to rewind to"),
    restore: bool = typer.Option(False, "--restore", help="Restore working tree to checkpoint state"),
):
    """Show or restore code state at a checkpoint.

    With --restore: requires clean working tree. Aborts if uncommitted changes exist.
    """
    import subprocess

    from ..core.checkpoint import get_checkpoint
    from ..core.project import find_git_root
    from ..core.session import get_session
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    cp = get_checkpoint(conn, checkpoint_id)

    if not cp:
        console.print(f"[red]Checkpoint not found:[/red] {checkpoint_id}")
        conn.close()
        raise typer.Exit(1)

    console.print(f"\n[bold]Checkpoint:[/bold] {cp['id'][:12]}")
    console.print(f"  Commit: {cp.get('git_commit_hash', '')}")
    console.print(f"  Branch: {cp.get('git_branch') or 'N/A'}")
    console.print(f"  Created: {cp.get('created_at', '')}")

    if cp.get("diff_summary"):
        console.print(f"  Diff Summary: {cp['diff_summary']}")

    session = get_session(conn, cp["session_id"])
    if session:
        console.print(f"\n[bold]Session:[/bold] {session['id'][:12]}")
        console.print(f"  Type: {session.get('session_type', '')}")
        if session.get("session_title"):
            console.print(f"  Title: {session['session_title']}")

    if cp.get("files_snapshot"):
        snapshot = cp["files_snapshot"]
        if isinstance(snapshot, dict):
            console.print(f"\n[bold]Files Snapshot ({len(snapshot)} files):[/bold]")
            for path in sorted(snapshot.keys())[:20]:
                console.print(f"  {path}")
            if len(snapshot) > 20:
                console.print(f"  ... and {len(snapshot) - 20} more")
        elif isinstance(snapshot, list):
            console.print(f"\n[bold]Files Snapshot ({len(snapshot)} files):[/bold]")
            for path in sorted(snapshot)[:20]:
                console.print(f"  {path}")
            if len(snapshot) > 20:
                console.print(f"  ... and {len(snapshot) - 20} more")

    conn.close()

    if restore:
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=repo_path,
            )
            if result.stdout.strip():
                console.print("\n[red]Working tree has uncommitted changes.[/red]")
                console.print("Commit or stash your changes first.")
                raise typer.Exit(1)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            console.print("[red]Could not check git status.[/red]")
            raise typer.Exit(1)

        commit_hash = cp["git_commit_hash"]
        console.print(f"\n[bold]Restoring working tree to commit {commit_hash[:10]}...[/bold]")

        try:
            subprocess.run(
                ["git", "checkout", commit_hash, "--", "."],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            console.print("[green]Working tree restored.[/green]")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Failed to restore: {e.stderr.strip()}[/red]")
            raise typer.Exit(1)
