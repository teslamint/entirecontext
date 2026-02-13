"""Rewind commands (Phase 2 stubs)."""

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
    if restore:
        import subprocess

        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.stdout.strip():
                console.print("[red]Working tree has uncommitted changes.[/red]")
                console.print("Commit or stash your changes first.")
                raise typer.Exit(1)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    console.print("[dim]Coming in Phase 2: Git Integration[/dim]")
