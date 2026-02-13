"""Checkpoint commands (Phase 2 stubs)."""

from __future__ import annotations

import typer
from rich.console import Console

from . import app

console = Console()
checkpoint_app = typer.Typer(help="Checkpoint management")
app.add_typer(checkpoint_app, name="checkpoint")


@checkpoint_app.command("list")
def checkpoint_list():
    """List checkpoints."""
    console.print("[dim]Coming in Phase 2: Git Integration[/dim]")


@checkpoint_app.command("show")
def checkpoint_show(checkpoint_id: str = typer.Argument(...)):
    """Show checkpoint details."""
    console.print("[dim]Coming in Phase 2: Git Integration[/dim]")


@checkpoint_app.command("diff")
def checkpoint_diff(
    id1: str = typer.Argument(...),
    id2: str = typer.Argument(...),
):
    """Diff between two checkpoints."""
    console.print("[dim]Coming in Phase 2: Git Integration[/dim]")
