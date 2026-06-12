"""CLI command for database and content compaction."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import typer

from rich.console import Console

console = Console()


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    elif n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    else:
        return f"{n / (1024 * 1024 * 1024):.2f} GB"


def compact_cmd(
    execute: bool = typer.Option(False, "--execute", help="Actually compact (default is dry-run)"),
    retention_days: Optional[int] = typer.Option(
        None,
        "--retention-days",
        "-r",
        help="Keep content files newer than N days (default: from config, fallback 30)",
    ),
    limit: int = typer.Option(10000, "--limit", "-n", help="Max turns to consolidate per run"),
) -> None:
    """Compact storage: consolidate old content, remove orphans, vacuum DB.

    Runs in dry-run mode by default — use --execute to apply changes.
    """
    from ..core.compact import compact_repo
    from ..core.config import load_config
    from ..core.project import find_git_root
    from ..db import check_and_migrate, get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    if retention_days is None:
        config = load_config(repo_path)
        retention_days = config.get("capture", {}).get("content_retention_days", 30)

    db_path = Path(repo_path) / ".entirecontext" / "db" / "local.db"
    if not execute and not db_path.exists():
        console.print("[dim]No EntireContext database found — nothing to compact.[/dim]")
        return

    conn = get_db(repo_path)
    try:
        check_and_migrate(conn)
        report = compact_repo(
            conn, repo_path, retention_days=retention_days, limit=limit, dry_run=not execute
        )
    finally:
        conn.close()

    _print_report(report)


def _print_report(report: dict[str, Any]) -> None:
    before = report["before"]
    after = report["after"]
    cons = report["consolidation"]
    orphans = report["orphans"]
    vacuum = report.get("vacuum", {})
    dry = report["dry_run"]

    if dry:
        console.print("[dim]Dry-run mode — no changes made.[/dim]\n")

    console.print(f"[bold]Retention:[/bold] {report['retention_days']} days\n")

    console.print("[bold]Content files:[/bold]")
    console.print(f"  Before: {before['content_file_count']} files ({_format_bytes(before['content_bytes'])})")
    if not dry:
        console.print(f"  After:  {after['content_file_count']} files ({_format_bytes(after['content_bytes'])})")
        saved = before["content_bytes"] - after["content_bytes"]
        if saved > 0:
            console.print(f"  [green]Freed: {_format_bytes(saved)}[/green]")

    console.print(f"\n[bold]Consolidation:[/bold] {cons['candidates']} eligible, {cons['consolidated']} consolidated")

    console.print(f"[bold]Orphans:[/bold] {orphans['orphans_found']} found, {orphans['orphans_removed']} removed")
    if orphans.get("bytes_freed", 0) > 0:
        console.print(f"  [green]Freed: {_format_bytes(orphans['bytes_freed'])}[/green]")

    if vacuum:
        console.print(f"\n[bold]DB vacuum:[/bold] {_format_bytes(vacuum['db_before'])} → {_format_bytes(vacuum['db_after'])}")


def register(app: typer.Typer) -> None:
    app.command("compact")(compact_cmd)
