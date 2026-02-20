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


SYSTEM_PROMPT = """You are a futures analyst grounded in Kent Beck's "Tidy First?" philosophy.
You evaluate code changes through the lens of software design options:
- **expand**: the change increases future options (good structure, reversibility, new capabilities)
- **narrow**: the change reduces future options (tight coupling, irreversible decisions, tech debt)
- **neutral**: the change neither significantly expands nor narrows future options

Analyze the given diff against the project roadmap and provide your assessment.
Respond with a JSON object (no markdown fences) with these fields:
- verdict: "expand" | "narrow" | "neutral"
- impact_summary: one-sentence summary of the change's impact on future options
- roadmap_alignment: how this change aligns with the roadmap
- tidy_suggestion: actionable suggestion (what to tidy, what to keep, what to reconsider)"""


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
    from ..core.llm import get_backend

    backend = get_backend(backend_name, model=model)
    content = backend.complete(system, user)
    # Strip markdown fences if present
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    return json.loads(content)


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
