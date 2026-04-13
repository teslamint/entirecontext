"""Decision commands."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .helpers import get_repo_connection

console = Console()
decision_app = typer.Typer(help="Decision memory management")


@decision_app.command("create")
def decision_create(
    title: str = typer.Argument(..., help="Decision title"),
    rationale: Optional[str] = typer.Option(None, "--rationale", help="Decision rationale"),
    scope: Optional[str] = typer.Option(None, "--scope", help="Decision scope"),
):
    from ..core.decisions import create_decision

    conn, _ = get_repo_connection()
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

    conn, _ = get_repo_connection()
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

    conn, _ = get_repo_connection()
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

    conn, _ = get_repo_connection()
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
    conn, repo_path = get_repo_connection()
    try:
        if status:
            from ..core.decisions import update_decision_staleness

            decision = update_decision_staleness(conn, decision_id, status)
            console.print(f"[green]Updated decision:[/green] {decision['id'][:12]} -> {decision['staleness_status']}")
        else:
            from ..core.decisions import check_staleness

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

    conn, _ = get_repo_connection()
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

    conn, _ = get_repo_connection()
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

    conn, _ = get_repo_connection()
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

    conn, _ = get_repo_connection()
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


@decision_app.command("search")
def decision_search(
    query: str = typer.Argument(..., help='FTS5 search query (supports AND, OR, NOT, prefix*, "phrase")'),
    search_type: str = typer.Option("fts", "--search-type", "-t", help="fts|hybrid"),
    since: Optional[str] = typer.Option(None, "--since", help="Only decisions updated after this ISO date"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
    include_stale: bool = typer.Option(True, "--include-stale/--no-include-stale", help="Include stale decisions"),
    include_superseded: bool = typer.Option(
        False, "--include-superseded/--no-include-superseded", help="Include superseded decisions"
    ),
    include_contradicted: bool = typer.Option(
        True,
        "--include-contradicted/--no-include-contradicted",
        help="Include contradicted decisions (default True; will flip to False in v0.3.0)",
    ),
):
    """Search decisions by keyword."""
    if search_type not in ("fts", "hybrid"):
        console.print(f"[red]Invalid search_type '{search_type}'. Use 'fts' or 'hybrid'.[/red]")
        raise typer.Exit(1)

    from ..core.decisions import fts_search_decisions, hybrid_search_decisions

    conn, _ = get_repo_connection()
    try:
        if search_type == "hybrid":
            decisions = hybrid_search_decisions(
                conn,
                query,
                since=since,
                limit=limit,
                include_stale=include_stale,
                include_superseded=include_superseded,
                include_contradicted=include_contradicted,
            )
        else:
            decisions = fts_search_decisions(
                conn,
                query,
                since=since,
                limit=limit,
                include_stale=include_stale,
                include_superseded=include_superseded,
                include_contradicted=include_contradicted,
            )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()

    if not decisions:
        console.print("[dim]No decisions found.[/dim]")
        return

    table = Table(title=f"Decision Search: '{query}' ({len(decisions)} results)")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Updated")
    if search_type == "hybrid":
        table.add_column("Score", justify="right")
    for d in decisions:
        row = [d["id"][:12], d.get("title", ""), d.get("staleness_status", ""), d.get("updated_at", "")]
        if search_type == "hybrid":
            row.append(f"{d.get('hybrid_score', 0):.4f}")
        table.add_row(*row)
    console.print(table)


@decision_app.command("chain")
def decision_chain(
    decision_id: str = typer.Argument(..., help="Decision ID (prefix supported)"),
):
    """Walk a decision's supersession chain for debugging.

    Prints each hop from the starting decision to the terminal successor,
    showing id, title, and staleness_status at each step.
    """
    from ..core.decisions import _SUCCESSOR_CHAIN_DEPTH_CAP
    from ..core.resolve import resolve_decision_id

    conn, _ = get_repo_connection()
    try:
        full_id = resolve_decision_id(conn, decision_id)
        if full_id is None:
            console.print(f"[red]Decision '{decision_id}' not found[/red]")
            raise typer.Exit(1)

        table = Table(title=f"Supersession chain for {full_id[:12]}")
        table.add_column("Hop", justify="right", style="dim")
        table.add_column("ID", style="dim", max_width=12)
        table.add_column("Title")
        table.add_column("Status")

        current_id: Optional[str] = full_id
        visited: set[str] = set()
        hop = 0
        while current_id is not None and hop < _SUCCESSOR_CHAIN_DEPTH_CAP:
            if current_id in visited:
                table.add_row(str(hop), current_id[:12], "[red]<cycle detected>[/red]", "")
                break
            visited.add(current_id)
            row = conn.execute(
                "SELECT id, title, staleness_status, superseded_by_id FROM decisions WHERE id = ?",
                (current_id,),
            ).fetchone()
            if row is None:
                break
            table.add_row(
                str(hop),
                row["id"][:12],
                row["title"] or "",
                row["staleness_status"] or "fresh",
            )
            successor = row["superseded_by_id"]
            if not successor:
                break
            current_id = successor
            hop += 1

        console.print(table)
    finally:
        conn.close()


@decision_app.command("stale-all")
def decision_stale_all():
    """Check staleness for all fresh decisions and persist results."""
    from ..core.decisions import check_staleness, list_decisions, update_decision_staleness

    conn, repo_path = get_repo_connection()
    try:
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
    finally:
        conn.close()

    if stale_count == 0:
        console.print(f"[green]All {len(decisions)} fresh decisions are up to date.[/green]")
    else:
        console.print(f"\n[yellow]{stale_count}/{len(decisions)} decisions marked as stale.[/yellow]")


def _get_llm_response(summaries: str, repo_path: str) -> str:
    """Call LLM to extract decisions. Separated for testability."""
    from ..core.config import load_config
    from ..core.llm import get_backend

    config = load_config(repo_path)
    backend_name = config.get("futures", {}).get("default_backend", "openai")
    model = config.get("futures", {}).get("default_model", None)
    backend = get_backend(backend_name, model=model)

    system = (
        "Extract architectural/technical decisions from this coding session. "
        'Return a JSON array: [{"title": str, "rationale": str, "scope": str, "rejected_alternatives": [str]}] '
        "Only include actual decisions (choosing one approach over another), "
        "not tasks, plans, or status updates. "
        "Return [] if no decisions were made."
    )
    return backend.complete(system, summaries)


def _extract_from_session_impl(conn, session_id: str, repo_path: str) -> None:
    """Core extraction logic. Used by CLI command and testable directly."""
    import json as _json
    import re

    from ..core.config import load_config
    from ..core.decisions import create_decision, link_decision_to_file

    # Idempotency check
    row = conn.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row and row["metadata"]:
        try:
            meta = _json.loads(row["metadata"])
            if meta.get("decisions_extracted") is True:
                return
        except (ValueError, TypeError):
            pass

    # Collect summaries with files
    rows = conn.execute(
        "SELECT assistant_summary, files_touched FROM turns "
        "WHERE session_id = ? AND assistant_summary IS NOT NULL "
        "ORDER BY turn_number ASC",
        (session_id,),
    ).fetchall()
    if not rows:
        return

    summaries = [r["assistant_summary"] for r in rows if r["assistant_summary"]]
    all_files: set[str] = set()
    for r in rows:
        if r["files_touched"]:
            try:
                files = _json.loads(r["files_touched"])
                if isinstance(files, list):
                    all_files.update(files)
            except (ValueError, TypeError):
                pass

    # Keyword filter
    config = load_config(repo_path)
    keywords = config.get("decisions", {}).get("extract_keywords", [])
    if keywords:
        pattern = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
        summaries = [s for s in summaries if pattern.search(s)]
    if not summaries:
        return

    # LLM call
    combined = "\n".join(summaries)
    raw = _get_llm_response(combined, repo_path)

    # Parse
    try:
        decisions_data = _json.loads(raw)
    except (ValueError, TypeError):
        console.print("[yellow]Invalid JSON from LLM, skipping extraction[/yellow]")
        return

    if not isinstance(decisions_data, list):
        return

    decisions_data = decisions_data[:5]

    for item in decisions_data:
        try:
            if not isinstance(item, dict) or "title" not in item:
                continue
            d = create_decision(
                conn,
                title=item["title"],
                rationale=item.get("rationale"),
                scope=item.get("scope"),
                rejected_alternatives=item.get("rejected_alternatives"),
            )
            for f in all_files:
                try:
                    link_decision_to_file(conn, d["id"], f)
                except Exception:
                    pass
        except Exception:
            continue

    # Set idempotency marker (null-safe)
    conn.execute(
        "UPDATE sessions SET metadata = json_set(COALESCE(metadata, '{}'), '$.decisions_extracted', json('true')) WHERE id = ?",
        (session_id,),
    )
    conn.commit()


@decision_app.command("extract-from-session")
def decision_extract_from_session(
    session_id: str = typer.Argument(..., help="Session ID to extract decisions from"),
):
    """Extract decisions from a session using LLM (background worker target)."""
    conn, repo_path = get_repo_connection()
    try:
        _extract_from_session_impl(conn, session_id, repo_path)
    except Exception as exc:
        console.print(f"[red]Extraction failed: {exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()


def register(app: typer.Typer) -> None:
    app.add_typer(decision_app, name="decision")
