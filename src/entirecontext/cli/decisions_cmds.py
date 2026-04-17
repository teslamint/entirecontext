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
    include_contradicted: bool = typer.Option(
        False,
        "--include-contradicted/--no-include-contradicted",
        help="Include contradicted decisions (default False)",
    ),
):
    from ..core.decisions import list_decisions

    conn, _ = get_repo_connection()
    try:
        decisions = list_decisions(
            conn,
            staleness_status=status,
            file_path=file,
            limit=limit,
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
        False,
        "--include-contradicted/--no-include-contradicted",
        help="Include contradicted decisions (default False)",
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
        while current_id is not None and hop <= _SUCCESSOR_CHAIN_DEPTH_CAP:
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


def _get_llm_response(summaries: str, repo_path: str, source_type: str = "session") -> str:
    """LLM call shim preserved at current module path for monkeypatch-based tests.

    The shim body below (_extract_from_session_impl) must always call this
    module-level function so that test monkeypatches on
    `entirecontext.cli.decisions_cmds._get_llm_response` remain effective.
    The production hook/worker path invokes
    `core.decision_extraction.call_extraction_llm` directly instead.

    `source_type` is a keyword with default so that legacy tests that
    monkeypatch this function with a 2-arg lambda (no source_type) still
    work — the shim calls through `_invoke_get_llm_response` which falls
    back to the 2-arg signature when the bound symbol does not accept
    `source_type`.
    """
    from ..core.decision_extraction import call_extraction_llm

    return call_extraction_llm(summaries, repo_path, source_type=source_type)


def _invoke_get_llm_response(summaries: str, repo_path: str, source_type: str) -> str:
    """Dispatch through the module-level _get_llm_response symbol while
    staying compatible with pre-existing 2-arg monkeypatches.

    Production callers (and tests that use `lambda *a, **kw: ...`) get
    the correct per-source system prompt via the `source_type` kwarg.
    Legacy tests that monkeypatch with `lambda summaries, repo_path: ...`
    are detected via inspect.signature and called without the kwarg.
    """
    import inspect

    try:
        params = inspect.signature(_get_llm_response).parameters
    except (TypeError, ValueError):
        return _get_llm_response(summaries, repo_path)
    accepts_source = "source_type" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    if accepts_source:
        return _get_llm_response(summaries, repo_path, source_type=source_type)
    return _get_llm_response(summaries, repo_path)


def _extract_from_session_impl(conn, session_id: str, repo_path: str, *, min_confidence: float | None = None) -> None:
    """Back-compat shim that drives the candidate pipeline while keeping
    monkeypatches on _get_llm_response effective. Writes into
    decision_candidates, NOT decisions — legacy tests were migrated."""
    from ..core import decision_extraction as ex

    if ex.is_session_extracted(conn, session_id):
        return

    bundles = ex.collect_signals(conn, session_id, repo_path)
    if not bundles:
        # Intentionally NOT marking as extracted — future collector rules or
        # new source types must be able to rediscover these sessions.
        return

    parsed_ok = False
    for bundle in bundles:
        prompt_text = ex.assemble_prompt(bundle)
        if not prompt_text.strip():
            continue
        redacted = ex.apply_redaction(prompt_text, repo_path)
        try:
            raw = _invoke_get_llm_response(redacted, repo_path, bundle.source_type)
        except ex.DecisionExtractionError:
            continue
        except Exception as exc:
            console.print(f"[yellow]LLM call failed for {bundle.source_type}: {exc}[/yellow]")
            continue
        try:
            drafts = ex.parse_llm_response(raw, bundle)
        except ex.DecisionExtractionError:
            # Parse failure intentionally does NOT mark the session, so that
            # the next SessionEnd re-runs extraction once the upstream noise
            # has been resolved. Matches test_extract_from_session_invalid_llm_json.
            continue
        parsed_ok = True
        for draft in drafts:
            dedup_result = ex.dedup(conn, draft)
            score, breakdown = ex.score_confidence(draft, dedup_result)
            if min_confidence is not None and score < min_confidence:
                continue
            ex.persist_candidate(conn, draft, score, breakdown, dedup_result)

    if parsed_ok:
        ex.mark_session_extracted(conn, session_id)


@decision_app.command("extract-candidates")
def decision_extract_candidates(
    session_id: str = typer.Option(..., "--session", help="Session ID to extract candidates from"),
):
    """Extract candidate decisions from a session (background worker target)."""
    conn, repo_path = get_repo_connection()
    try:
        from ..core.config import load_config
        from ..core.decision_extraction import run_extraction

        config = load_config(repo_path)
        min_confidence = config.get("decisions", {}).get("candidate_min_confidence", 0.35)
        outcome = run_extraction(conn, session_id, repo_path, min_confidence=min_confidence)
        console.print(
            f"[green]Extraction complete[/green] — bundles={outcome.bundles_collected} "
            f"drafts={outcome.drafts_parsed} inserted={outcome.candidates_inserted} "
            f"duplicates={outcome.duplicates_skipped} low_confidence={outcome.low_confidence_skipped}"
        )
        if outcome.warnings:
            for warning in outcome.warnings:
                console.print(f"[yellow]warning:[/yellow] {warning}")
    except Exception as exc:
        console.print(f"[red]Extraction failed: {exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()


@decision_app.command("extract-from-session")
def decision_extract_from_session(
    session_id: str = typer.Argument(..., help="Session ID to extract candidates from"),
):
    """Back-compat alias for the candidate extraction pipeline."""
    conn, repo_path = get_repo_connection()
    try:
        from ..core.config import load_config

        config = load_config(repo_path)
        min_confidence = config.get("decisions", {}).get("candidate_min_confidence", 0.35)
        _extract_from_session_impl(conn, session_id, repo_path, min_confidence=min_confidence)
    except Exception as exc:
        console.print(f"[red]Extraction failed: {exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()


@decision_app.command("surface-prompt")
def decision_surface_prompt(
    session_id: str = typer.Option(..., "--session", help="Session ID that originated the prompt"),
    turn_id: str = typer.Option(..., "--turn", help="Turn ID that originated the prompt"),
    prompt_file: str = typer.Option(..., "--prompt-file", help="Path to the tmp file holding the redacted prompt"),
    repo_path_arg: Optional[str] = typer.Option(
        None, "--repo-path", help="Absolute repo root (required when the worker inherits cwd outside the repo)"
    ),
):
    """Background worker: rank decisions against the current user prompt.

    Invoked by ``on_user_prompt`` via ``launch_worker`` when
    ``[decisions] surface_on_user_prompt = true``. Reads the redacted
    prompt from ``--prompt-file`` (defense-in-depth: re-applies secret
    filters), writes Markdown to
    ``.entirecontext/decisions-context-prompt-<session>-<turn>.md``,
    and deletes the tmp prompt file in ``try/finally`` regardless of
    outcome. Never exits nonzero on surfacing errors.

    ``--repo-path`` is the primary resolution path — the hook passes it
    explicitly because ``launch_worker`` does not set ``cwd`` on the
    child process, so a worker that falls back to ``find_git_root()``
    would read whatever directory the parent hook was launched from
    (which may be outside the repo when Claude Code runs from a
    different cwd than ``data["cwd"]``).
    """
    from pathlib import Path

    from ..core.decision_prompt_surfacing import run_prompt_surface_worker
    from ..core.project import find_git_root

    prompt_path = Path(prompt_file)
    repo_path = repo_path_arg or find_git_root()
    if not repo_path:
        # Either the caller (the hook) forgot to pass --repo-path AND the
        # worker's inherited cwd is outside a git tree, or the repo was
        # removed mid-run. Clean up the tmp file before exit so a
        # misconfigured invocation cannot leak the prompt payload on disk.
        try:
            prompt_path.unlink()
        except OSError:
            pass
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    result = run_prompt_surface_worker(repo_path, session_id, turn_id, prompt_path)
    if result.get("warnings"):
        for warning in result["warnings"]:
            console.print(f"[yellow]warning:[/yellow] {warning}")


candidates_app = typer.Typer(help="Candidate decision review flow")


@candidates_app.command("list")
def candidates_list(
    session_id: Optional[str] = typer.Option(None, "--session", help="Filter by session id"),
    status: Optional[str] = typer.Option(None, "--status", help="pending|confirmed|rejected"),
    min_confidence: float = typer.Option(0.0, "--min-confidence", help="Minimum confidence"),
    source: Optional[str] = typer.Option(None, "--source", help="session|checkpoint|assessment"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
):
    from ..core.decision_candidates import list_candidates

    conn, _ = get_repo_connection()
    try:
        rows = list_candidates(
            conn,
            session_id=session_id,
            status=status,
            min_confidence=min_confidence,
            source_type=source,
            limit=limit,
        )
    finally:
        conn.close()

    if not rows:
        console.print("[dim]No candidates found.[/dim]")
        return

    table = Table(title=f"Decision Candidates ({len(rows)})")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Title")
    table.add_column("Source")
    table.add_column("Status")
    table.add_column("Conf", justify="right")
    for r in rows:
        table.add_row(
            r["id"][:12],
            (r.get("title") or "")[:60],
            r.get("source_type", ""),
            r.get("review_status", ""),
            f"{r.get('confidence', 0.0):.2f}",
        )
    console.print(table)


@candidates_app.command("show")
def candidates_show(candidate_id: str = typer.Argument(..., help="Candidate ID")):
    import json as _json

    from ..core.decision_candidates import get_candidate

    conn, _ = get_repo_connection()
    try:
        candidate = get_candidate(conn, candidate_id)
    finally:
        conn.close()

    if not candidate:
        console.print(f"[red]Candidate not found:[/red] {candidate_id}")
        raise typer.Exit(1)

    console.print(f"[bold]Candidate:[/bold] {candidate['id']}")
    console.print(f"  Title: {candidate.get('title', '')}")
    console.print(f"  Source: {candidate.get('source_type', '')} / {candidate.get('source_id', '')}")
    console.print(f"  Status: {candidate.get('review_status', '')}")
    console.print(f"  Confidence: {candidate.get('confidence', 0.0):.3f}")
    if candidate.get("rationale"):
        console.print(f"  Rationale: {candidate['rationale']}")
    if candidate.get("scope"):
        console.print(f"  Scope: {candidate['scope']}")
    alts = candidate.get("rejected_alternatives") or []
    if alts:
        console.print(f"  Rejected alternatives: {alts}")
    files = candidate.get("files") or []
    if files:
        console.print(f"  Files: {files}")
    breakdown = candidate.get("confidence_breakdown") or {}
    if breakdown:
        console.print("  Breakdown:")
        console.print(_json.dumps(breakdown, indent=2, ensure_ascii=False))


@candidates_app.command("confirm")
def candidates_confirm(
    candidate_id: str = typer.Argument(..., help="Candidate ID"),
    scope: Optional[str] = typer.Option(None, "--scope", help="Override scope on promotion"),
    note: Optional[str] = typer.Option(None, "--note", help="Reviewer note"),
):
    from ..core.decision_candidates import confirm_candidate

    conn, _ = get_repo_connection()
    try:
        result = confirm_candidate(
            conn,
            candidate_id,
            scope_override=scope,
            reviewer="cli",
            note=note,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()
    console.print(
        f"[green]Confirmed[/green] candidate {result['candidate_id'][:12]} → decision {result['decision_id']}"
    )


@candidates_app.command("reject")
def candidates_reject(
    candidate_id: str = typer.Argument(..., help="Candidate ID"),
    reason: Optional[str] = typer.Option(None, "--reason", help="Reviewer reason"),
):
    from ..core.decision_candidates import reject_candidate

    conn, _ = get_repo_connection()
    try:
        result = reject_candidate(conn, candidate_id, reason=reason, reviewer="cli")
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()
    console.print(f"[yellow]Rejected[/yellow] candidate {result['candidate_id'][:12]}")


decision_app.add_typer(candidates_app, name="candidates")


def register(app: typer.Typer) -> None:
    app.add_typer(decision_app, name="decision")
