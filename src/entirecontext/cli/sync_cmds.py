"""Sync commands."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def sync(
    no_filter: bool = typer.Option(False, "--no-filter", help="Skip secret filtering"),
    if_enabled: bool = typer.Option(False, "--if-enabled", help="Only run if auto_sync_on_push is enabled in config"),
):
    """Export to shadow branch and push."""
    from ..core.project import find_git_root, get_project
    from ..db import get_db
    from ..sync.engine import perform_sync

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    if if_enabled:
        from ..core.config import load_config

        config = load_config(repo_path)
        if not config.get("sync", {}).get("auto_sync_on_push", False):
            return

    project = get_project(repo_path)
    if not project:
        console.print("[yellow]Not initialized. Run 'ec init'.[/yellow]")
        raise typer.Exit(1)

    console.print("[bold]Syncing to shadow branch...[/bold]")

    conn = get_db(repo_path)
    try:
        config = {"security": {"filter_secrets": not no_filter}}
        result = perform_sync(conn, repo_path, config=config)

        if result["error"]:
            console.print(f"[red]Sync failed: {result['error']}[/red]")
            raise typer.Exit(1)

        console.print(f"  Exported {result['exported_sessions']} sessions")
        console.print(f"  Exported {result['exported_checkpoints']} checkpoints")
        console.print("  Updated manifest")

        if result["committed"]:
            console.print("  Committed to shadow branch")
            if result["pushed"]:
                console.print("  Pushed to remote")
            else:
                console.print("[yellow]  Push skipped (no remote or push failed)[/yellow]")
        else:
            console.print("[dim]  No changes to commit[/dim]")

        console.print("[green]Sync complete.[/green]")
    finally:
        conn.close()


def pull():
    """Fetch shadow branch and import."""
    from ..core.project import find_git_root, get_project
    from ..db import get_db
    from ..sync.engine import perform_pull

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    project = get_project(repo_path)
    if not project:
        console.print("[yellow]Not initialized. Run 'ec init'.[/yellow]")
        raise typer.Exit(1)

    console.print("[bold]Pulling from shadow branch...[/bold]")

    conn = get_db(repo_path)
    try:
        result = perform_pull(conn, repo_path, config={})

        if result["error"] == "no_shadow_branch":
            console.print("[yellow]No shadow branch found. Run 'ec sync' first.[/yellow]")
            raise typer.Exit(1)
        elif result["error"]:
            console.print(f"[red]Pull failed: {result['error']}[/red]")
            raise typer.Exit(1)

        console.print(f"  Imported {result['imported_sessions']} sessions")
        console.print(f"  Imported {result['imported_checkpoints']} checkpoints")
        console.print("[green]Pull complete.[/green]")
    finally:
        conn.close()


def register(app: typer.Typer) -> None:
    app.command("sync")(sync)
    app.command("pull")(pull)
