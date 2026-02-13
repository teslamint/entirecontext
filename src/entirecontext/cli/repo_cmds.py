"""Repository management commands."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import app

console = Console()
repo_app = typer.Typer(help="Repository management")
app.add_typer(repo_app, name="repo")


@repo_app.command("list")
def repo_list():
    """List registered EntireContext projects."""
    from ..core.cross_repo import list_repos

    repos = list_repos()

    if not repos:
        console.print("[dim]No registered repositories.[/dim]")
        return

    table = Table(title=f"Registered Repositories ({len(repos)})")
    table.add_column("Name")
    table.add_column("Path")
    table.add_column("DB", justify="center")
    table.add_column("Sessions", justify="right")
    table.add_column("Turns", justify="right")

    for r in repos:
        db_exists = Path(r["db_path"]).exists()
        table.add_row(
            r.get("repo_name", ""),
            r.get("repo_path", ""),
            "[green]✓[/green]" if db_exists else "[red]✗[/red]",
            str(r.get("session_count") or 0),
            str(r.get("turn_count") or 0),
        )

    console.print(table)
