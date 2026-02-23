"""Team dashboard command — sessions, checkpoints, and assessment trends."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from . import app

console = Console()


@app.command("dashboard")
def dashboard_cmd(
    since: str | None = typer.Option(
        None, "--since", "-s", help="Only include data on or after this date (YYYY-MM-DD)"
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of recent items to show per section (default 10)"),
) -> None:
    """Show a team dashboard: session stats, checkpoint stats, and assessment trends."""
    from ..core.dashboard import get_dashboard_stats
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        stats = get_dashboard_stats(conn, since=since, limit=limit)
    finally:
        conn.close()

    _render_dashboard(stats)


def _render_dashboard(stats: dict) -> None:
    """Render the dashboard stats using Rich tables."""
    since_label = f"  [dim]since {stats['since']}[/dim]" if stats["since"] else ""

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    s = stats["sessions"]
    console.print(f"\n[bold]Sessions[/bold] — {s['total']} total  active: {s['active']}  ended: {s['ended']}{since_label}")

    if s["recent"]:
        tbl = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        tbl.add_column("ID", style="dim", max_width=14)
        tbl.add_column("Title", max_width=30)
        tbl.add_column("Started", style="dim", max_width=20)
        tbl.add_column("Last Activity", style="dim", max_width=20)
        tbl.add_column("Status", max_width=8)

        for row in s["recent"]:
            status = "[dim]ended[/dim]" if row.get("ended_at") else "[green]active[/green]"
            tbl.add_row(
                (row.get("id") or "")[:14],
                (row.get("session_title") or "")[:30],
                (row.get("started_at") or "")[:19],
                (row.get("last_activity_at") or "")[:19],
                status,
            )
        console.print(tbl)
    else:
        console.print("[dim]  No sessions.[/dim]")

    # ------------------------------------------------------------------
    # Checkpoints
    # ------------------------------------------------------------------
    c = stats["checkpoints"]
    console.print(f"\n[bold]Checkpoints[/bold] — {c['total']} total{since_label}")

    if c["recent"]:
        tbl = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        tbl.add_column("ID", style="dim", max_width=14)
        tbl.add_column("Session", style="dim", max_width=14)
        tbl.add_column("Branch", max_width=20)
        tbl.add_column("Commit", style="dim", max_width=10)
        tbl.add_column("Created", style="dim", max_width=20)

        for row in c["recent"]:
            tbl.add_row(
                (row.get("id") or "")[:14],
                (row.get("session_id") or "")[:14],
                (row.get("git_branch") or "")[:20],
                (row.get("git_commit_hash") or "")[:8],
                (row.get("created_at") or "")[:19],
            )
        console.print(tbl)
    else:
        console.print("[dim]  No checkpoints.[/dim]")

    # ------------------------------------------------------------------
    # Assessments
    # ------------------------------------------------------------------
    a = stats["assessments"]
    bv = a["by_verdict"]
    total = a["total"]
    feedback_pct = f"{a['feedback_rate'] * 100:.0f}%" if total > 0 else "0%"

    console.print(f"\n[bold]Assessments[/bold] — {total} total  feedback: {a['with_feedback']} ({feedback_pct}){since_label}")

    verdict_table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    verdict_table.add_column("Verdict", max_width=12)
    verdict_table.add_column("Count", justify="right", max_width=8)
    verdict_table.add_column("Pct", justify="right", max_width=6)

    verdict_colors = {"expand": "green", "narrow": "red", "neutral": "yellow"}
    for v in ("expand", "narrow", "neutral"):
        count = bv.get(v, 0)
        pct = f"{round(100 * count / total)}%" if total else "0%"
        color = verdict_colors[v]
        verdict_table.add_row(f"[{color}]{v}[/{color}]", str(count), pct)

    console.print(verdict_table)

    if a["recent"]:
        tbl = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        tbl.add_column("ID", style="dim", max_width=14)
        tbl.add_column("Verdict", max_width=10)
        tbl.add_column("Impact", max_width=50)
        tbl.add_column("Feedback", max_width=10)
        tbl.add_column("Created", style="dim", max_width=20)

        for row in a["recent"]:
            v = row.get("verdict", "")
            color = verdict_colors.get(v, "white")
            tbl.add_row(
                (row.get("id") or "")[:14],
                f"[{color}]{v}[/{color}]",
                (row.get("impact_summary") or "")[:50],
                row.get("feedback") or "",
                (row.get("created_at") or "")[:19],
            )
        console.print(tbl)
    else:
        console.print("[dim]  No recent assessments.[/dim]")
