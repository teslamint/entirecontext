"""Futures assessment commands — Tidy First philosophy."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import app

console = Console()
futures_app = typer.Typer(help="Futures assessment (Tidy First)")
app.add_typer(futures_app, name="futures")


from ..core.futures import ASSESS_SYSTEM_PROMPT as SYSTEM_PROMPT  # noqa: E402


def _get_staged_diff() -> str:
    """Get the current staged diff."""
    result = subprocess.run(
        ["git", "diff", "--staged"],
        capture_output=True,
        text=True,
    )
    return result.stdout


def _get_checkpoint_diff(conn, checkpoint_id: str) -> str | None:
    """Get diff summary from a checkpoint."""
    row = conn.execute(
        "SELECT diff_summary FROM checkpoints WHERE id = ? OR id LIKE ?", (checkpoint_id, f"{checkpoint_id}%")
    ).fetchone()
    return row["diff_summary"] if row else None


def _call_llm(backend_name: str, model: str, system: str, user: str) -> dict:
    """Call LLM backend for assessment."""
    from ..core.llm import get_backend, strip_markdown_fences

    backend = get_backend(backend_name, model=model)
    content = backend.complete(system, user)
    return json.loads(strip_markdown_fences(content))


def _render_assessment(assessment: dict) -> None:
    """Render assessment with Rich."""
    verdict = assessment.get("verdict", "neutral")
    verdict_colors = {"expand": "green", "narrow": "red", "neutral": "yellow"}
    color = verdict_colors.get(verdict, "white")
    verdict_icons = {"expand": "\U0001f7e2", "narrow": "\U0001f534", "neutral": "\U0001f7e1"}
    icon = verdict_icons.get(verdict, "")

    console.print(
        Panel(
            f"[bold {color}]{icon} {verdict.upper()}[/bold {color}]\n\n"
            f"[bold]Impact:[/bold] {assessment.get('impact_summary', 'N/A')}\n\n"
            f"[bold]Roadmap alignment:[/bold] {assessment.get('roadmap_alignment', 'N/A')}\n\n"
            f"[bold]Suggestion:[/bold] {assessment.get('tidy_suggestion', 'N/A')}",
            title="Futures Assessment",
            subtitle=f"ID: {assessment.get('id', '')[:12]}",
        )
    )


@futures_app.command("assess")
def futures_assess(
    checkpoint: Optional[str] = typer.Option(None, "--checkpoint", "-c", help="Checkpoint ID to assess"),
    roadmap: str = typer.Option("ROADMAP.md", "--roadmap", "-r", help="Path to roadmap file"),
    model: str = typer.Option("gpt-4o-mini", "--model", "-m", help="LLM model name"),
    backend: str = typer.Option("openai", "--backend", "-b", help="LLM backend (openai|codex|claude|ollama)"),
):
    """Assess current staged diff or a checkpoint against project roadmap."""
    from ..core.futures import create_assessment
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)

    # Get diff
    checkpoint_id = None
    if checkpoint:
        diff = _get_checkpoint_diff(conn, checkpoint)
        if not diff:
            console.print(f"[red]Checkpoint not found or has no diff: {checkpoint}[/red]")
            conn.close()
            raise typer.Exit(1)
        # Resolve full checkpoint ID
        row = conn.execute(
            "SELECT id FROM checkpoints WHERE id = ? OR id LIKE ?", (checkpoint, f"{checkpoint}%")
        ).fetchone()
        checkpoint_id = row["id"] if row else None
    else:
        diff = _get_staged_diff()
        if not diff.strip():
            console.print("[yellow]No staged changes found. Stage changes with `git add` first.[/yellow]")
            conn.close()
            raise typer.Exit(1)

    # Read roadmap
    roadmap_text = ""
    roadmap_path = Path(roadmap)
    if roadmap_path.exists():
        roadmap_text = roadmap_path.read_text(encoding="utf-8")
    else:
        console.print(f"[dim]Roadmap file not found: {roadmap}. Proceeding without it.[/dim]")

    # Build user prompt
    user_prompt = ""
    if roadmap_text:
        user_prompt += f"## ROADMAP\n\n{roadmap_text}\n\n"
    user_prompt += f"## DIFF\n\n```diff\n{diff[:8000]}\n```"

    # Call LLM
    console.print("[dim]Analyzing with LLM...[/dim]")
    try:
        result = _call_llm(backend, model, SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        console.print(f"[red]LLM call failed: {e}[/red]")
        conn.close()
        raise typer.Exit(1)

    # Save assessment
    assessment = create_assessment(
        conn,
        checkpoint_id=checkpoint_id,
        verdict=result.get("verdict", "neutral"),
        impact_summary=result.get("impact_summary"),
        roadmap_alignment=result.get("roadmap_alignment"),
        tidy_suggestion=result.get("tidy_suggestion"),
        diff_summary=diff[:2000],
        model_name=model,
    )
    conn.close()

    _render_assessment(assessment)


@futures_app.command("list")
def futures_list(
    verdict: Optional[str] = typer.Option(None, "--verdict", "-v", help="Filter by verdict (expand/narrow/neutral)"),
    limit: int = typer.Option(20, "--limit", "-n"),
):
    """List futures assessments."""
    from ..core.futures import list_assessments
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        assessments = list_assessments(conn, verdict=verdict, limit=limit)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        conn.close()
        raise typer.Exit(1)
    conn.close()

    if not assessments:
        console.print("[dim]No assessments found.[/dim]")
        return

    table = Table(title=f"Assessments ({len(assessments)})")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Verdict")
    table.add_column("Impact")
    table.add_column("Feedback")
    table.add_column("Created")

    verdict_colors = {"expand": "green", "narrow": "red", "neutral": "yellow"}
    for a in assessments:
        v = a.get("verdict", "")
        color = verdict_colors.get(v, "white")
        fb = a.get("feedback") or ""
        table.add_row(
            a["id"][:12],
            f"[{color}]{v}[/{color}]",
            (a.get("impact_summary") or "")[:60],
            fb,
            a.get("created_at", ""),
        )

    console.print(table)


@futures_app.command("feedback")
def futures_feedback(
    assessment_id: str = typer.Argument(..., help="Assessment ID"),
    feedback: str = typer.Argument(..., help="Feedback: agree or disagree"),
    reason: Optional[str] = typer.Option(None, "--reason", "-r", help="Feedback reason"),
):
    """Add feedback to an assessment."""
    from ..core.futures import add_feedback, auto_distill_lessons
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        add_feedback(conn, assessment_id, feedback, feedback_reason=reason)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        conn.close()
        raise typer.Exit(1)
    conn.close()

    console.print(f"[green]Feedback recorded:[/green] {feedback} on {assessment_id[:12]}")

    from ..core.config import load_config

    config = load_config(repo_path)
    if auto_distill_lessons(repo_path):
        output = config.get("futures", {}).get("lessons_output", "LESSONS.md")
        console.print(f"[dim]Auto-updated {output}[/dim]")


@futures_app.command("lessons")
def futures_lessons(
    output: str = typer.Option("LESSONS.md", "--output", "-o", help="Output file path"),
    since: Optional[str] = typer.Option(
        None, "--since", "-s", help="Only include lessons after this date (YYYY-MM-DD)"
    ),
):
    """Generate LESSONS.md from assessed changes with feedback."""
    from ..core.futures import distill_lessons, get_lessons
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    lessons = get_lessons(conn)
    conn.close()

    if since:
        lessons = [item for item in lessons if (item.get("created_at") or "") >= since]

    text = distill_lessons(lessons)
    Path(output).write_text(text, encoding="utf-8")
    console.print(f"[green]Written {len(lessons)} lessons to {output}[/green]")


@futures_app.command("relate")
def futures_relate(
    source_id: str = typer.Argument(..., help="Source assessment ID (supports prefix)"),
    relationship_type: str = typer.Argument(..., help="Relationship type: causes, fixes, or contradicts"),
    target_id: str = typer.Argument(..., help="Target assessment ID (supports prefix)"),
    note: Optional[str] = typer.Option(None, "--note", "-n", help="Optional explanatory note"),
):
    """Add a typed relationship between two assessments.

    Example: ec futures relate abc123 causes def456
    """
    from ..core.futures import add_assessment_relationship
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        rel = add_assessment_relationship(conn, source_id, target_id, relationship_type, note=note)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        conn.close()
        raise typer.Exit(1)
    conn.close()

    type_colors = {"causes": "red", "fixes": "green", "contradicts": "yellow"}
    color = type_colors.get(relationship_type, "white")
    console.print(
        f"[green]Relationship added:[/green] {rel['source_id'][:12]} [{color}]{relationship_type}[/{color}] {rel['target_id'][:12]}"
    )
    if note:
        console.print(f"  [dim]Note: {note}[/dim]")


@futures_app.command("relationships")
def futures_relationships(
    assessment_id: str = typer.Argument(..., help="Assessment ID to show relationships for (supports prefix)"),
    direction: str = typer.Option("both", "--direction", "-d", help="Direction: outgoing, incoming, or both"),
):
    """List typed relationships for an assessment."""
    from ..core.futures import get_assessment_relationships
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    rels = get_assessment_relationships(conn, assessment_id, direction=direction)
    conn.close()

    if not rels:
        console.print("[dim]No relationships found.[/dim]")
        return

    type_colors = {"causes": "red", "fixes": "green", "contradicts": "yellow"}
    type_icons = {"causes": "→", "fixes": "✓", "contradicts": "≠"}

    table = Table(title=f"Relationships for {assessment_id[:12]} ({len(rels)})")
    table.add_column("Direction", style="dim", max_width=10)
    table.add_column("Type", max_width=12)
    table.add_column("Other Assessment", max_width=14)
    table.add_column("Summary", max_width=50)
    table.add_column("Note", max_width=30)

    for r in rels:
        if r.get("direction") == "outgoing":
            dir_label = "[bold]→ out[/bold]"
            other_id = r["target_id"][:12]
            summary = (r.get("target_impact_summary") or "")[:50]
        else:
            dir_label = "[dim]← in[/dim]"
            other_id = r["source_id"][:12]
            summary = (r.get("source_impact_summary") or "")[:50]

        rtype = r["relationship_type"]
        color = type_colors.get(rtype, "white")
        icon = type_icons.get(rtype, "")
        table.add_row(
            dir_label,
            f"[{color}]{icon} {rtype}[/{color}]",
            other_id,
            summary,
            r.get("note") or "",
        )

    console.print(table)


@futures_app.command("unrelate")
def futures_unrelate(
    source_id: str = typer.Argument(..., help="Source assessment ID (supports prefix)"),
    relationship_type: str = typer.Argument(..., help="Relationship type: causes, fixes, or contradicts"),
    target_id: str = typer.Argument(..., help="Target assessment ID (supports prefix)"),
):
    """Remove a typed relationship between two assessments."""
    from ..core.futures import remove_assessment_relationship
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    removed = remove_assessment_relationship(conn, source_id, target_id, relationship_type)
    conn.close()

    if removed:
        console.print(f"[green]Relationship removed:[/green] {source_id[:12]} {relationship_type} {target_id[:12]}")
    else:
        console.print(f"[yellow]Relationship not found:[/yellow] {source_id[:12]} {relationship_type} {target_id[:12]}")


@futures_app.command("trend")
def futures_trend(
    repos: Optional[list[str]] = typer.Option(None, "--repo", "-R", help="Filter by repo name (repeat for multiple)"),
    since: Optional[str] = typer.Option(
        None, "--since", "-s", help="Only include assessments after this date (YYYY-MM-DD)"
    ),
):
    """Show cross-repo assessment trend analysis."""
    from ..core.cross_repo import cross_repo_assessment_trends

    trends, warnings = cross_repo_assessment_trends(repos=repos, since=since, include_warnings=True)

    for w in warnings:
        console.print(f"[yellow]Warning:[/yellow] {w}")

    total = trends["total_count"]
    if total == 0:
        console.print("[dim]No assessments found across repos.[/dim]")
        return

    overall = trends["overall"]
    console.print(f"\n[bold]Cross-Repo Assessment Trends[/bold] — {total} total\n")

    overall_table = Table(title="Overall Distribution")
    overall_table.add_column("Verdict")
    overall_table.add_column("Count", justify="right")
    overall_table.add_column("Pct", justify="right")

    verdict_colors = {"expand": "green", "narrow": "red", "neutral": "yellow"}
    verdict_icons = {"expand": "🟢", "narrow": "🔴", "neutral": "🟡"}
    for v in ("expand", "narrow", "neutral"):
        count = overall.get(v, 0)
        pct = f"{100 * count / total:.0f}%" if total else "0%"
        color = verdict_colors.get(v, "white")
        icon = verdict_icons.get(v, "")
        overall_table.add_row(f"[{color}]{icon} {v}[/{color}]", str(count), pct)

    console.print(overall_table)

    with_fb = trends["with_feedback"]
    console.print(f"\nWith feedback: {with_fb}/{total} ({100 * with_fb // total if total else 0}%)\n")

    by_repo = trends["by_repo"]
    if len(by_repo) > 1:
        repo_table = Table(title="Per-Repo Breakdown")
        repo_table.add_column("Repo")
        repo_table.add_column("Total", justify="right")
        repo_table.add_column("🟢 Expand", justify="right")
        repo_table.add_column("🔴 Narrow", justify="right")
        repo_table.add_column("🟡 Neutral", justify="right")
        repo_table.add_column("Feedback", justify="right")

        for repo_name, stats in sorted(by_repo.items()):
            repo_table.add_row(
                repo_name,
                str(stats["total"]),
                str(stats["expand"]),
                str(stats["narrow"]),
                str(stats["neutral"]),
                str(stats["with_feedback"]),
            )
        console.print(repo_table)


@futures_app.command("report")
def futures_report(
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Write report to file; omit to print to stdout"),
    since: Optional[str] = typer.Option(
        None, "--since", "-s", help="Only include assessments after this date (YYYY-MM-DD)"
    ),
    limit: int = typer.Option(100, "--limit", "-n", help="Maximum number of assessments to include"),
):
    """Generate a Markdown futures report — team-shareable summary of assessment trends."""
    from pathlib import Path

    from ..core.futures import list_assessments
    from ..core.project import find_git_root, get_project
    from ..core.report import generate_futures_report
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    # Pass `since` to SQL so LIMIT is applied after the date filter
    assessments = list_assessments(conn, limit=limit, since=since)
    project = get_project(repo_path)
    conn.close()

    project_name = project.get("name") if project else None

    report = generate_futures_report(assessments, project_name=project_name, since=since)

    if output:
        Path(output).write_text(report, encoding="utf-8")
        console.print(f"[green]Report written to:[/green] {output}")
    else:
        typer.echo(report)


@futures_app.command("tidy-pr")
def futures_tidy_pr(
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Write PR draft to file; omit to print to stdout"),
    since: Optional[str] = typer.Option(
        None, "--since", "-s", help="Only include assessments after this date (YYYY-MM-DD)"
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum number of suggestions to include"),
):
    """Generate a tidy PR draft from narrow assessment suggestions (rule-based)."""
    from pathlib import Path

    from ..core.project import find_git_root
    from ..core.tidy_pr import generate_tidy_pr
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        pr_text = generate_tidy_pr(conn, since=since, limit=limit)
    finally:
        conn.close()

    if output:
        Path(output).write_text(pr_text, encoding="utf-8")
        console.print(f"[green]Tidy PR draft written to:[/green] {output}")
    else:
        typer.echo(pr_text)


@futures_app.command("worker-status")
def futures_worker_status():
    """Show background assessment worker status (running / idle / stale)."""
    from ..core.async_worker import worker_status
    from ..core.project import find_git_root

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    status = worker_status(repo_path)
    if status["running"]:
        console.print(f"[green]Worker running[/green] (PID {status['pid']})")
    elif status.get("stale"):
        console.print(
            f"[yellow]Stale PID file found[/yellow] (PID {status['pid']} no longer running). Run 'ec futures worker-stop' to clean up."
        )
    else:
        console.print("[dim]No active worker (idle).[/dim]")


@futures_app.command("worker-stop")
def futures_worker_stop():
    """Stop the background assessment worker (sends SIGTERM)."""
    from ..core.async_worker import stop_worker
    from ..core.project import find_git_root

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    try:
        outcome = stop_worker(repo_path)
    except PermissionError:
        console.print("[red]Cannot stop worker: permission denied (process owned by another user).[/red]")
        raise typer.Exit(1)

    if outcome == "killed":
        console.print("[green]Worker stopped (SIGTERM sent).[/green]")
    elif outcome == "stale":
        console.print("[yellow]Stale PID file removed (worker was not running).[/yellow]")
    else:
        console.print("[dim]No worker running.[/dim]")


@futures_app.command("worker-launch")
def futures_worker_launch(
    diff: Optional[str] = typer.Option(None, "--diff", "-d", help="Diff text to assess (reads stdin if omitted)"),
):
    """Launch a background assessment worker for the current repo.

    The worker runs ``ec futures assess`` asynchronously so it does not block
    the calling process (e.g. a Claude Code hook).  Its PID is stored in
    ``.entirecontext/worker.pid``.
    """
    import sys

    from ..core.async_worker import launch_worker
    from ..core.project import find_git_root

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    # Build the command: use the same Python executable that's running now
    # so the worker picks up the correct virtualenv/installation.
    cmd = [sys.executable, "-m", "entirecontext.cli", "futures", "assess"]
    if diff:
        cmd.extend(["--diff", diff])

    pid = launch_worker(repo_path, cmd)
    console.print(f"[green]Worker launched[/green] (PID {pid})")
