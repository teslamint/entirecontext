"""Blame/attribution commands."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import app

console = Console()


@app.command("blame")
def blame_cmd(
    file: str = typer.Argument(..., help="File path to show attribution for"),
    summary: bool = typer.Option(False, "--summary", "-s", help="Show aggregated stats only"),
    lines: Optional[str] = typer.Option(None, "-L", help="Line range (e.g. 10,20)"),
):
    """Show per-line human/agent attribution for a file."""
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)

    start_line = None
    end_line = None
    if lines:
        parts = lines.split(",")
        if len(parts) == 2:
            start_line = int(parts[0])
            end_line = int(parts[1])
        elif len(parts) == 1:
            start_line = int(parts[0])
            end_line = int(parts[0])

    if summary:
        from ..core.attribution import get_file_attribution_summary

        stats = get_file_attribution_summary(conn, file)
        conn.close()

        if stats["total_lines"] == 0:
            console.print(f"[dim]No attribution data for {file}[/dim]")
            return

        console.print(f"\n[bold]Attribution Summary: {file}[/bold]")
        console.print(f"  Total lines: {stats['total_lines']}")
        console.print(f"  Human: {stats['human_lines']} ({stats['human_pct']}%)")
        console.print(f"  Agent: {stats['agent_lines']} ({stats['agent_pct']}%)")

        if stats["agents"]:
            console.print("\n  [bold]Agent breakdown:[/bold]")
            for agent_name, line_count in stats["agents"].items():
                console.print(f"    {agent_name}: {line_count} lines")
        return

    from ..core.attribution import get_file_attributions

    attributions = get_file_attributions(conn, file, start_line=start_line, end_line=end_line)
    conn.close()

    if not attributions:
        console.print(f"[dim]No attribution data for {file}[/dim]")
        return

    table = Table(title=f"Attribution: {file}")
    table.add_column("Lines", style="dim")
    table.add_column("Type")
    table.add_column("Agent", style="cyan")
    table.add_column("Session", style="dim", max_width=12)
    table.add_column("Confidence")

    for a in attributions:
        type_style = "[green]human[/green]" if a["attribution_type"] == "human" else "[blue]agent[/blue]"
        table.add_row(
            f"{a['start_line']}-{a['end_line']}",
            type_style,
            a.get("agent_name") or "",
            (a.get("session_id") or "")[:12],
            f"{a['confidence']:.0%}" if a["confidence"] is not None else "",
        )

    console.print(table)
