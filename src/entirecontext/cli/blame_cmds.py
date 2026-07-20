"""Blame/attribution commands."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def blame_cmd(
    file: str = typer.Argument(..., help="File path to show attribution for"),
    summary: bool = typer.Option(False, "--summary", "-s", help="Show aggregated stats only"),
    lines: Optional[str] = typer.Option(None, "-L", help="Line range (e.g. 10,20)"),
    decisions: bool = typer.Option(False, "--decisions", help="Annotate with decision history"),
):
    """Show per-line human/agent attribution for a file."""
    from ..core.project import find_git_root
    from ..db import check_and_migrate, get_db

    if decisions and summary:
        console.print("[red]--summary and --decisions are mutually exclusive.[/red]")
        raise typer.Exit(1)

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        if decisions:
            check_and_migrate(conn)

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
        else:
            from ..core.attribution import get_file_attributions

            attributions = get_file_attributions(conn, file, start_line=start_line, end_line=end_line)

            decision_result = None
            if decisions:
                from ..core.blame_decisions import annotate_file

                try:
                    decision_result = annotate_file(conn, repo_path, file, start_line=start_line, end_line=end_line)
                except ValueError as exc:
                    console.print(f"[red]{exc}[/red]")
                    raise typer.Exit(1) from exc
    finally:
        conn.close()

    if summary:
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

    if not attributions:
        console.print(f"[dim]No attribution data for {file}[/dim]")
    else:
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

    if decisions and decision_result is not None:
        _render_decision_annotations(file, decision_result)


def _render_decision_annotations(file: str, decision_result: dict) -> None:
    annotations = decision_result["annotations"]
    unlinked_ranges = decision_result.get("unlinked_ranges", [])
    uncommitted_ranges = decision_result["uncommitted_ranges"]

    console.print(f"\n[bold]Decision annotations: {file}[/bold]")

    if not annotations and not unlinked_ranges and not uncommitted_ranges:
        console.print(
            "[dim]No recorded decisions for this file's commits — "
            "absence of links, not evidence that no decisions were made.[/dim]"
        )
        return

    for a in annotations:
        ranges_str = ", ".join(f"{s}-{e}" for s, e in a.line_ranges)
        stale_suffix = f" [yellow][STALE:{a.staleness_status}][/yellow]" if a.staleness_status != "fresh" else ""
        console.print(f"  {a.commit_sha[:8]} lines {ranges_str} — {a.title}{stale_suffix}")
        console.print(f"    [dim]{a.rationale_excerpt}[/dim]")
        if a.rejected_count > 0:
            console.print(f"    ({a.rejected_count} rejected alternatives)")
        if a.staleness_status != "fresh":
            console.print(f"    ↳ re-verify: ec decision get {a.decision_id}")

    for s, e in unlinked_ranges:
        console.print(
            f"  lines {s}-{e}: no recorded decision "
            "(absence of links, not evidence that no decisions were made)"
        )

    for s, e in uncommitted_ranges:
        console.print(f"  lines {s}-{e}: uncommitted (no blame history yet)")


def register(app: typer.Typer) -> None:
    app.command("blame")(blame_cmd)
