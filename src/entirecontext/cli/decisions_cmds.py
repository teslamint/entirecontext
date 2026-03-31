"""Decision commands."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()
decision_app = typer.Typer(help="Decision memory management")


def _get_repo_connection():
    from ..core.project import find_git_root
    from ..db import check_and_migrate, get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        check_and_migrate(conn)
    except Exception:
        conn.close()
        raise
    return conn


@decision_app.command("create")
def decision_create(
    title: str = typer.Argument(..., help="Decision title"),
    rationale: Optional[str] = typer.Option(None, "--rationale", help="Decision rationale"),
    scope: Optional[str] = typer.Option(None, "--scope", help="Decision scope"),
):
    from ..core.decisions import create_decision

    conn = _get_repo_connection()
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

    conn = _get_repo_connection()
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

    conn = _get_repo_connection()
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
    quality = decision.get("quality_summary") or {}
    counts = quality.get("counts") or {}
    console.print(
        "  Outcomes:"
        f" accepted={counts.get('accepted', 0)}"
        f" ignored={counts.get('ignored', 0)}"
        f" contradicted={counts.get('contradicted', 0)}"
        f" total={quality.get('total_outcomes', 0)}"
        f" score={quality.get('quality_score', 0.0)}"
    )
    if decision.get("files"):
        console.print("  Files:")
        for file_path in decision["files"]:
            console.print(f"    - {file_path}")
    if decision.get("assessments"):
        console.print("  Assessments:")
        for item in decision["assessments"]:
            console.print(f"    - {item['assessment_id'][:12]} ({item['relation_type']})")
    if decision.get("recent_outcomes"):
        console.print("  Recent outcomes:")
        for item in decision["recent_outcomes"]:
            console.print(f"    - {item['outcome_type']} @ {item['created_at']}")


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

    link_args = [bool(assessment), bool(checkpoint), bool(commit), bool(file)]
    if sum(link_args) != 1:
        console.print("[red]Exactly one of --assessment, --checkpoint, --commit, --file is required.[/red]")
        raise typer.Exit(1)

    conn = _get_repo_connection()
    try:
        if assessment:
            linked = link_decision_to_assessment(conn, decision_id, assessment, relation_type=relation_type)
            console.print(
                "[green]Linked decision "
                f"{linked['decision_id'][:12]} to assessment {linked['assessment_id'][:12]} "
                f"({linked['relation_type']})[/green]"
            )
        elif checkpoint:
            linked = link_decision_to_checkpoint(conn, decision_id, checkpoint)
            console.print(
                "[green]Linked decision "
                f"{linked['decision_id'][:12]} to checkpoint {linked['checkpoint_id'][:12]}[/green]"
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
    status: Optional[str] = typer.Option(None, "--status", help="Manually set: fresh|stale|superseded|contradicted"),
):
    """Check or set staleness for a decision. Without --status, auto-detects via git."""
    from ..core.project import find_git_root

    conn = _get_repo_connection()
    try:
        if status:
            from ..core.decisions import update_decision_staleness

            decision = update_decision_staleness(conn, decision_id, status)
            console.print(f"[green]Updated decision:[/green] {decision['id'][:12]} -> {decision['staleness_status']}")
        else:
            from ..core.decisions import check_staleness

            repo_path = find_git_root()
            if not repo_path:
                console.print("[red]Not in a git repository.[/red]")
                raise typer.Exit(1)
            result = check_staleness(conn, decision_id, repo_path)
            if result["stale"]:
                console.print(f"[yellow]STALE[/yellow] — {len(result['changed_files'])} linked file(s) changed:")
                for f in result["changed_files"]:
                    console.print(f"  - {f}")
            else:
                console.print("[green]Not stale.[/green]")
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()


@decision_app.command("outcome")
def decision_outcome(
    decision_id: str = typer.Argument(..., help="Decision ID"),
    outcome: str = typer.Option(..., "--outcome", help="accepted|ignored|contradicted"),
    selection_id: Optional[str] = typer.Option(None, "--selection-id", help="Decision retrieval selection ID"),
    note: Optional[str] = typer.Option(None, "--note", help="Optional outcome note"),
):
    from ..core.decisions import record_decision_outcome
    from ..core.telemetry import detect_current_context

    conn = _get_repo_connection()
    try:
        session_id, turn_id = detect_current_context(conn)
        if turn_id is None:
            session_id = None
        created = record_decision_outcome(
            conn,
            decision_id,
            outcome,
            retrieval_selection_id=selection_id,
            note=note,
            session_id=session_id,
            turn_id=turn_id,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()

    console.print(
        f"[green]Recorded decision outcome:[/green] {created['decision_id'][:12]} -> {created['outcome_type']}"
    )


@decision_app.command("update")
def decision_update(
    decision_id: str = typer.Argument(..., help="Decision ID (supports prefix)"),
    title: Optional[str] = typer.Option(None, "--title", "-t"),
    rationale: Optional[str] = typer.Option(None, "--rationale"),
    scope: Optional[str] = typer.Option(None, "--scope"),
):
    """Update a decision's fields."""
    from ..core.decisions import update_decision

    conn = _get_repo_connection()
    try:
        d = update_decision(conn, decision_id, title=title, rationale=rationale, scope=scope)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()

    console.print(f"[green]Updated decision:[/green] {d['id'][:12]} — {d['title']}")


@decision_app.command("supersede")
def decision_supersede(
    old_id: str = typer.Argument(..., help="Decision ID to supersede (supports prefix)"),
    new_id: str = typer.Argument(..., help="New decision ID that replaces it (supports prefix)"),
):
    """Mark a decision as superseded by another."""
    from ..core.decisions import supersede_decision

    conn = _get_repo_connection()
    try:
        d = supersede_decision(conn, old_id, new_id)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()

    console.print(f"[green]Decision superseded:[/green] {d['id'][:12]} → {d.get('superseded_by_id', '')[:12]}")


@decision_app.command("unlink")
def decision_unlink(
    decision_id: str = typer.Argument(..., help="Decision ID (supports prefix)"),
    assessment: Optional[str] = typer.Option(None, "--assessment", help="Assessment ID to unlink"),
    checkpoint: Optional[str] = typer.Option(None, "--checkpoint", help="Checkpoint ID to unlink"),
    commit: Optional[str] = typer.Option(None, "--commit", help="Commit SHA to unlink"),
    file: Optional[str] = typer.Option(None, "--file", help="File path to unlink"),
    relation_type: str = typer.Option("supports", "--relation-type", help="Assessment relation type"),
):
    """Remove a link from a decision."""
    from ..core.decisions import (
        unlink_decision_from_assessment,
        unlink_decision_from_checkpoint,
        unlink_decision_from_commit,
        unlink_decision_from_file,
    )

    link_args = [bool(assessment), bool(checkpoint), bool(commit), bool(file)]
    if sum(link_args) != 1:
        console.print("[red]Exactly one of --assessment, --checkpoint, --commit, --file is required.[/red]")
        raise typer.Exit(1)

    conn = _get_repo_connection()
    try:
        if assessment:
            removed = unlink_decision_from_assessment(conn, decision_id, assessment, relation_type)
        elif checkpoint:
            removed = unlink_decision_from_checkpoint(conn, decision_id, checkpoint)
        elif commit:
            removed = unlink_decision_from_commit(conn, decision_id, commit)
        else:
            removed = unlink_decision_from_file(conn, decision_id, file or "")
    finally:
        conn.close()

    if removed:
        console.print("[green]Link removed.[/green]")
    else:
        console.print("[yellow]Link not found.[/yellow]")


@decision_app.command("stale-all")
def decision_stale_all():
    """Check staleness for all fresh decisions and persist results."""
    from ..core.decisions import check_staleness, detect_contradictions, list_decisions, update_decision_staleness
    from ..core.project import find_git_root

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    from ..db import check_and_migrate, get_db

    conn = get_db(repo_path)
    try:
        check_and_migrate(conn)
        decisions = list_decisions(conn, staleness_status="fresh", limit=1000)
        stale_count = 0
        for d in decisions:
            result = check_staleness(conn, d["id"], repo_path)
            if result["stale"]:
                stale_count += 1
                update_decision_staleness(conn, d["id"], "stale")
                console.print(
                    f"[yellow]STALE[/yellow] {d['id'][:12]} {d['title'][:40]} — {len(result['changed_files'])} file(s)"
                )

        contradictions = detect_contradictions(conn, limit=10)
        if contradictions:
            console.print(
                f"\n[yellow]Found {len(contradictions)} potential contradiction pair(s). "
                f"Run 'ec decision contradictions' for details.[/yellow]"
            )
    finally:
        conn.close()

    if stale_count == 0:
        console.print(f"[green]All {len(decisions)} fresh decisions are up to date.[/green]")
    else:
        console.print(f"\n[yellow]{stale_count}/{len(decisions)} decisions marked as stale.[/yellow]")


@decision_app.command("relate")
def decision_relate(
    source_id: str = typer.Argument(..., help="Source decision ID"),
    target_id: str = typer.Argument(..., help="Target decision ID"),
    relationship_type: str = typer.Argument(..., help="contradicts|supersedes|related_to"),
    note: Optional[str] = typer.Option(None, "--note", help="Relationship note"),
    confidence: float = typer.Option(1.0, "--confidence", help="Confidence 0.0-1.0"),
):
    """Create a relationship between two decisions."""
    from ..core.decisions import add_decision_relationship

    conn = _get_repo_connection()
    try:
        rel = add_decision_relationship(conn, source_id, target_id, relationship_type, confidence=confidence, note=note)
    except (ValueError, Exception) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()

    console.print(
        f"[green]Created relationship:[/green] {rel['source_id'][:12]} "
        f"--{rel['relationship_type']}--> {rel['target_id'][:12]}"
    )


@decision_app.command("relations")
def decision_relations(
    decision_id: str = typer.Argument(..., help="Decision ID"),
    direction: str = typer.Option("both", "--direction", help="outgoing|incoming|both"),
):
    """Show relationships for a decision."""
    from ..core.decisions import get_decision_relationships

    conn = _get_repo_connection()
    try:
        rels = get_decision_relationships(conn, decision_id, direction=direction)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()

    if not rels:
        console.print("[dim]No relationships found.[/dim]")
        return

    table = Table(title=f"Decision Relationships ({len(rels)})")
    table.add_column("Direction", style="dim")
    table.add_column("Type")
    table.add_column("Other Decision")
    table.add_column("Confidence")
    table.add_column("Note")
    for r in rels:
        other_title = r.get("target_title") or r.get("source_title") or ""
        other_id = r["target_id"][:12] if r["direction"] == "outgoing" else r["source_id"][:12]
        table.add_row(
            r["direction"],
            r["relationship_type"],
            f"{other_id} {other_title[:30]}",
            f"{r.get('confidence', 1.0):.1f}",
            (r.get("note") or "")[:40],
        )
    console.print(table)


@decision_app.command("contradictions")
def decision_contradictions(
    scope: Optional[str] = typer.Option(None, "--scope", help="Filter by scope"),
    min_overlap: int = typer.Option(1, "--min-overlap", help="Min shared files"),
    limit: int = typer.Option(20, "--limit", "-n"),
    auto_link: bool = typer.Option(False, "--auto-link", help="Auto-create contradiction relationships"),
):
    """Detect potential contradictions between fresh decisions."""
    from ..core.decisions import add_decision_relationship, detect_contradictions

    conn = _get_repo_connection()
    try:
        results = detect_contradictions(conn, scope_filter=scope, min_file_overlap=min_overlap, limit=limit)

        if not results:
            console.print("[green]No potential contradictions found.[/green]")
            return

        table = Table(title=f"Potential Contradictions ({len(results)})")
        table.add_column("Decision A", max_width=30)
        table.add_column("Decision B", max_width=30)
        table.add_column("Shared Files")
        table.add_column("Scope")
        table.add_column("Score")
        for r in results:
            table.add_row(
                f"{r['source_id'][:12]} {r['source_title'][:18]}",
                f"{r['target_id'][:12]} {r['target_title'][:18]}",
                str(len(r["shared_files"])),
                r.get("shared_scope") or "",
                f"{r['score']:.1f}",
            )
        console.print(table)

        if auto_link:
            linked = 0
            for r in results:
                try:
                    add_decision_relationship(conn, r["source_id"], r["target_id"], "contradicts", confidence=0.5)
                    linked += 1
                except Exception:
                    pass
            console.print(f"[green]Auto-linked {linked} contradiction pair(s).[/green]")
    finally:
        conn.close()


def register(app: typer.Typer) -> None:
    app.add_typer(decision_app, name="decision")
