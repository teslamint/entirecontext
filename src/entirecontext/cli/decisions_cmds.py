"""Decision commands."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()
decision_app = typer.Typer(help="Decision memory management")


@decision_app.command("create")
def decision_create(
    title: str = typer.Argument(..., help="Decision title"),
    rationale: Optional[str] = typer.Option(None, "--rationale", help="Decision rationale"),
    scope: Optional[str] = typer.Option(None, "--scope", help="Decision scope"),
):
    from ..core.decisions import create_decision
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        decision = create_decision(conn, title=title, rationale=rationale, scope=scope)
    finally:
        conn.close()
    console.print(f"[green]Created decision:[/green] {decision['id']}")


@decision_app.command("list")
def decision_list(
    status: Optional[str] = typer.Option(None, "--status", help="fresh|stale|superseded|contradicted"),
    file: Optional[str] = typer.Option(None, "--file", help="Filter by linked file path"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
):
    from ..core.decisions import list_decisions
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        decisions = list_decisions(conn, staleness_status=status, file_path=file, limit=limit)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()

    if not decisions:
        console.print("[dim]No decisions found.[/dim]")
        return

    table = Table(title=f"Decisions ({len(decisions)})")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Updated")
    for d in decisions:
        table.add_row(d["id"][:12], d.get("title", ""), d.get("staleness_status", ""), d.get("updated_at", ""))
    console.print(table)


@decision_app.command("show")
def decision_show(decision_id: str = typer.Argument(..., help="Decision ID")):
    from ..core.decisions import get_decision
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        decision = get_decision(conn, decision_id)
    finally:
        conn.close()

    if not decision:
        console.print(f"[red]Decision not found:[/red] {decision_id}")
        raise typer.Exit(1)

    console.print(f"[bold]Decision:[/bold] {decision['id']}")
    console.print(f"  Title: {decision.get('title', '')}")
    console.print(f"  Status: {decision.get('staleness_status', '')}")
    console.print(f"  Scope: {decision.get('scope') or ''}")
    console.print(f"  Rationale: {decision.get('rationale') or ''}")
    console.print(f"  Rejected alternatives: {len(decision.get('rejected_alternatives', []))}")
    console.print(f"  Supporting evidence: {len(decision.get('supporting_evidence', []))}")
    if decision.get("files"):
        console.print("  Files:")
        for file_path in decision["files"]:
            console.print(f"    - {file_path}")
    if decision.get("assessments"):
        console.print("  Assessments:")
        for item in decision["assessments"]:
            console.print(f"    - {item['assessment_id'][:12]} ({item['relation_type']})")


@decision_app.command("link")
def decision_link(
    decision_id: str = typer.Argument(..., help="Decision ID"),
    assessment: Optional[str] = typer.Option(None, "--assessment", help="Assessment ID"),
    checkpoint: Optional[str] = typer.Option(None, "--checkpoint", help="Checkpoint ID"),
    commit: Optional[str] = typer.Option(None, "--commit", help="Commit SHA"),
    file: Optional[str] = typer.Option(None, "--file", help="File path"),
    relation_type: str = typer.Option("supports", "--relation-type", help="Assessment relation type"),
):
    from ..core.decisions import (
        link_decision_to_assessment,
        link_decision_to_checkpoint,
        link_decision_to_commit,
        link_decision_to_file,
    )
    from ..core.project import find_git_root
    from ..db import get_db

    link_args = [bool(assessment), bool(checkpoint), bool(commit), bool(file)]
    if sum(link_args) != 1:
        console.print("[red]Exactly one of --assessment, --checkpoint, --commit, --file is required.[/red]")
        raise typer.Exit(1)

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        if assessment:
            linked = link_decision_to_assessment(conn, decision_id, assessment, relation_type=relation_type)
            console.print(
                f"[green]Linked decision {linked['decision_id'][:12]} to assessment {linked['assessment_id'][:12]} ({linked['relation_type']})[/green]"
            )
        elif checkpoint:
            linked = link_decision_to_checkpoint(conn, decision_id, checkpoint)
            console.print(
                f"[green]Linked decision {linked['decision_id'][:12]} to checkpoint {linked['checkpoint_id'][:12]}[/green]"
            )
        elif commit:
            linked = link_decision_to_commit(conn, decision_id, commit)
            console.print(
                f"[green]Linked decision {linked['decision_id'][:12]} to commit {linked['commit_sha']}[/green]"
            )
        else:
            linked = link_decision_to_file(conn, decision_id, file or "")
            console.print(f"[green]Linked decision {linked['decision_id'][:12]} to file {linked['file_path']}[/green]")
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()


@decision_app.command("stale")
def decision_stale(
    decision_id: str = typer.Argument(..., help="Decision ID"),
    status: str = typer.Option(..., "--status", help="fresh|stale|superseded|contradicted"),
):
    from ..core.decisions import update_decision_staleness
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        decision = update_decision_staleness(conn, decision_id, status)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()
    console.print(f"[green]Updated decision:[/green] {decision['id'][:12]} -> {decision['staleness_status']}")


def register(app: typer.Typer) -> None:
    app.add_typer(decision_app, name="decision")
