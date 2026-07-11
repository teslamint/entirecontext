"""CLI command: ec archaeologize."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

console = Console()


def archaeologize(
    since: Optional[str] = typer.Option(None, "--since", help="Git ref or date (e.g., v1.0.0, 2025-01-01)"),
    until: Optional[str] = typer.Option(None, "--until", help="Git ref or date (default: HEAD)"),
    limit: int = typer.Option(100, "--limit", help="Max commits to process"),
    pr_bodies: bool = typer.Option(False, "--pr-bodies", help="Fetch merged PR bodies from GitHub API"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show commit count and cost estimate only"),
    batch_size: Optional[int] = typer.Option(None, "--batch-size", help="Override config batch_size"),
) -> None:
    """Extract decisions from git commit history."""
    from ..core.archaeology import archaeologize as do_archaeologize
    from ..core.config import load_config
    from ..core.project import find_git_root
    from ..db import check_and_migrate, get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    config = load_config(repo_path)
    arch_config = config.get("decisions", {}).get("archaeology", {})

    if not arch_config.get("enabled", True):
        console.print(
            "[yellow]Archaeology is disabled in config. Set [decisions.archaeology] enabled = true.[/yellow]"
        )
        raise typer.Exit(1)

    if limit <= 0:
        console.print("[red]--limit must be a positive integer.[/red]")
        raise typer.Exit(1)

    effective_batch_size = batch_size or arch_config.get("batch_size", 10)
    decisions_config = config.get("decisions", {})
    min_confidence = float(decisions_config.get("candidate_min_confidence", arch_config.get("min_confidence", 0.35)))

    if dry_run:
        from pathlib import Path

        db_path = Path(repo_path) / ".entirecontext" / "db" / "local.db"
        if db_path.exists():
            import sqlite3

            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
        else:
            from ..db import get_memory_db

            conn = get_memory_db()
    else:
        conn = get_db(repo_path)
    try:
        if not dry_run:
            check_and_migrate(conn)

        def _progress(msg: str) -> None:
            console.print(msg)

        result = do_archaeologize(
            conn,
            repo_path,
            since=since,
            until=until,
            limit=limit,
            pr_bodies=pr_bodies,
            dry_run=dry_run,
            batch_size=effective_batch_size,
            min_confidence=min_confidence,
            progress_callback=_progress,
        )
    finally:
        conn.close()

    if result.warnings:
        console.print(f"[yellow]Warnings: {len(result.warnings)}[/yellow]")
        for w in result.warnings[:5]:
            console.print(f"  - {w}")

    if dry_run:
        return

    console.print(
        f"\n[bold]Done.[/bold] Scanned {result.commits_scanned}, "
        f"processed {result.commits_processed}, "
        f"skipped {result.commits_skipped}, "
        f"candidates {result.candidates_generated}."
    )


def register(app: typer.Typer) -> None:
    app.command(name="archaeologize")(archaeologize)
