"""Checkpoint commands."""

from __future__ import annotations

from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from . import app

console = Console()
checkpoint_app = typer.Typer(help="Checkpoint management")
app.add_typer(checkpoint_app, name="checkpoint")


@checkpoint_app.command("list")
def checkpoint_list(
    session: str | None = typer.Option(None, "--session", "-s", help="Filter by session ID"),
    limit: int = typer.Option(20, "--limit", "-n"),
    global_search: bool = typer.Option(False, "--global", "-g", help="List checkpoints across all registered repos"),
    repo: Optional[List[str]] = typer.Option(None, "--repo", "-r", help="Filter by repo name (repeatable)"),
):
    """List checkpoints."""
    is_cross_repo = global_search or repo

    if is_cross_repo:
        from ..core.cross_repo import cross_repo_checkpoints

        checkpoints, warnings = cross_repo_checkpoints(
            repos=repo, session_id=session, limit=limit, include_warnings=True
        )

        if not checkpoints:
            console.print("[dim]No checkpoints found.[/dim]")
            return

        table = Table(title=f"Checkpoints ({len(checkpoints)})")
        table.add_column("Repo", style="cyan", max_width=15)
        table.add_column("ID", style="dim", max_width=12)
        table.add_column("Commit", style="cyan", max_width=10)
        table.add_column("Branch")
        table.add_column("Created")
        table.add_column("Diff Summary", max_width=40)

        for cp in checkpoints:
            table.add_row(
                cp.get("repo_name", ""),
                cp["id"][:12],
                (cp.get("git_commit_hash") or "")[:10],
                cp.get("git_branch") or "",
                cp.get("created_at") or "",
                (cp.get("diff_summary") or "")[:40],
            )

        console.print(table)
        for w in warnings:
            console.print(f"[dim]{w}[/dim]")
        return

    from ..core.checkpoint import list_checkpoints
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    checkpoints = list_checkpoints(conn, session_id=session, limit=limit)
    conn.close()

    if not checkpoints:
        console.print("[dim]No checkpoints found.[/dim]")
        return

    table = Table(title=f"Checkpoints ({len(checkpoints)})")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Commit", style="cyan", max_width=10)
    table.add_column("Branch")
    table.add_column("Created")
    table.add_column("Diff Summary", max_width=40)

    for cp in checkpoints:
        table.add_row(
            cp["id"][:12],
            (cp.get("git_commit_hash") or "")[:10],
            cp.get("git_branch") or "",
            cp.get("created_at") or "",
            (cp.get("diff_summary") or "")[:40],
        )

    console.print(table)


@checkpoint_app.command("show")
def checkpoint_show(
    checkpoint_id: str = typer.Argument(...),
    global_search: bool = typer.Option(False, "--global", "-g", help="Search across all registered repos"),
    repo: Optional[List[str]] = typer.Option(None, "--repo", "-r", help="Filter by repo name (repeatable)"),
):
    """Show checkpoint details."""
    is_cross_repo = global_search or repo

    if is_cross_repo:
        from ..core.cross_repo import cross_repo_rewind

        result, warnings = cross_repo_rewind(checkpoint_id, repos=repo, include_warnings=True)

        if not result:
            console.print(f"[red]Checkpoint not found:[/red] {checkpoint_id}")
            raise typer.Exit(1)

        cp = result
        console.print(f"\n[bold]Checkpoint:[/bold] {cp['id']}")
        console.print(f"  Repo: {cp.get('repo_name', '')}")
        console.print(f"  Commit: {cp.get('git_commit_hash', '')}")
        console.print(f"  Branch: {cp.get('git_branch') or 'N/A'}")
        console.print(f"  Created: {cp.get('created_at', '')}")
        if cp.get("diff_summary"):
            console.print(f"  Diff Summary: {cp['diff_summary']}")
        if cp.get("parent_checkpoint_id"):
            console.print(f"  Parent: {cp['parent_checkpoint_id'][:12]}")

        if cp.get("files_snapshot"):
            snapshot = cp["files_snapshot"]
            if isinstance(snapshot, dict):
                console.print(f"\n[bold]Files Snapshot ({len(snapshot)} files):[/bold]")
                for path in sorted(snapshot.keys())[:50]:
                    console.print(f"  {path}")
                if len(snapshot) > 50:
                    console.print(f"  ... and {len(snapshot) - 50} more")
            elif isinstance(snapshot, list):
                console.print(f"\n[bold]Files Snapshot ({len(snapshot)} files):[/bold]")
                for path in sorted(snapshot)[:50]:
                    console.print(f"  {path}")
                if len(snapshot) > 50:
                    console.print(f"  ... and {len(snapshot) - 50} more")

        for w in warnings:
            console.print(f"[dim]{w}[/dim]")
        return

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

    console.print(f"\n[bold]Checkpoint:[/bold] {cp['id']}")
    console.print(f"  Commit: {cp.get('git_commit_hash', '')}")
    console.print(f"  Branch: {cp.get('git_branch') or 'N/A'}")
    console.print(f"  Created: {cp.get('created_at', '')}")
    if cp.get("diff_summary"):
        console.print(f"  Diff Summary: {cp['diff_summary']}")
    if cp.get("parent_checkpoint_id"):
        console.print(f"  Parent: {cp['parent_checkpoint_id'][:12]}")

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
            for path in sorted(snapshot.keys())[:50]:
                console.print(f"  {path}")
            if len(snapshot) > 50:
                console.print(f"  ... and {len(snapshot) - 50} more")
        elif isinstance(snapshot, list):
            console.print(f"\n[bold]Files Snapshot ({len(snapshot)} files):[/bold]")
            for path in sorted(snapshot)[:50]:
                console.print(f"  {path}")
            if len(snapshot) > 50:
                console.print(f"  ... and {len(snapshot) - 50} more")

    conn.close()


@checkpoint_app.command("diff")
def checkpoint_diff(
    id1: str = typer.Argument(...),
    id2: str = typer.Argument(...),
):
    """Diff between two checkpoints."""
    from ..core.checkpoint import diff_checkpoints
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    result = diff_checkpoints(conn, id1, id2)
    conn.close()

    if "error" in result:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(1)

    cp1 = result["checkpoint_1"]
    cp2 = result["checkpoint_2"]
    console.print(
        f"\n[bold]Comparing:[/bold] {cp1['id'][:12]} ({cp1['commit'][:10]}) vs {cp2['id'][:12]} ({cp2['commit'][:10]})"
    )

    if result["added"]:
        console.print(f"\n[green]Added ({len(result['added'])}):[/green]")
        for f in result["added"]:
            console.print(f"  + {f}")

    if result["removed"]:
        console.print(f"\n[red]Removed ({len(result['removed'])}):[/red]")
        for f in result["removed"]:
            console.print(f"  - {f}")

    if result["modified"]:
        console.print(f"\n[yellow]Modified ({len(result['modified'])}):[/yellow]")
        for f in result["modified"]:
            console.print(f"  ~ {f}")

    if not result["added"] and not result["removed"] and not result["modified"]:
        console.print("\n[dim]No differences in files_snapshot.[/dim]")
