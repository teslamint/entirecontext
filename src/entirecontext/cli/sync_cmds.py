"""Sync commands (Phase 2 stubs)."""

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
    console.print("[dim]Coming in Phase 2: Git Integration[/dim]")


@app.command("pull")
def pull():
    """Fetch shadow branch and import."""
    console.print("[dim]Coming in Phase 2: Git Integration[/dim]")
