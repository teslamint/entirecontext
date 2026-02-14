"""Import commands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from . import app

console = Console()


@app.command("import")
def import_cmd(
    from_aline: Optional[str] = typer.Option(
        None,
        "--from-aline",
        help="Path to Aline database (default: ~/.aline/db/aline.db)",
    ),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="Filter by workspace path"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be imported without making changes"),
    skip_content: bool = typer.Option(False, "--skip-content", help="Skip importing turn content (faster)"),
):
    """Import data from external sources."""
    if from_aline is not None:
        _import_from_aline(from_aline, workspace, dry_run, skip_content)
    else:
        console.print("[yellow]Specify an import source. Available: --from-aline[/yellow]")
        raise typer.Exit(1)


def _import_from_aline(
    aline_path: str,
    workspace: str | None,
    dry_run: bool,
    skip_content: bool,
) -> None:
    from ..core.project import find_git_root, get_project
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    project = get_project(repo_path)
    if not project:
        console.print("[yellow]Not initialized. Run 'ec init'.[/yellow]")
        raise typer.Exit(1)

    db_path = aline_path or str(Path.home() / ".aline" / "db" / "aline.db")

    if dry_run:
        console.print("[bold]Dry run mode — no changes will be made[/bold]")

    console.print(f"[bold]Importing from Aline:[/bold] {db_path}")

    conn = get_db(repo_path)
    try:
        from ..core.import_aline import import_from_aline

        result = import_from_aline(
            ec_conn=conn,
            aline_db_path=db_path,
            project_id=project["id"],
            repo_path=repo_path,
            workspace_filter=workspace,
            dry_run=dry_run,
            skip_content=skip_content,
        )

        prefix = "Would import" if dry_run else "Imported"
        console.print(f"  {prefix} {result.sessions} sessions")
        console.print(f"  {prefix} {result.turns} turns")
        if not skip_content:
            console.print(f"  {prefix} {result.turn_content} turn content files")
        console.print(f"  {prefix} {result.checkpoints} checkpoints")
        console.print(f"  {prefix} {result.events} events")
        console.print(f"  {prefix} {result.event_links} event-session links")

        if result.skipped:
            console.print(f"  Skipped: {result.skipped}")

        if result.errors:
            console.print(f"\n[red]Errors ({len(result.errors)}):[/red]")
            for err in result.errors[:10]:
                console.print(f"  {err}")
            if len(result.errors) > 10:
                console.print(f"  ... and {len(result.errors) - 10} more")
            raise typer.Exit(1)

        if not dry_run:
            try:
                from ..core.indexing import rebuild_fts_indexes

                rebuild_fts_indexes(conn)
                console.print("  FTS indexes rebuilt")
            except Exception:
                pass

        console.print("[green]Import complete.[/green]")
    finally:
        conn.close()
