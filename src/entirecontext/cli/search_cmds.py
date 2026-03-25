"""Search commands."""

from __future__ import annotations

import sqlite3
import time
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()

def search(
    query: str = typer.Argument(..., help="Search query"),
    fts: bool = typer.Option(False, "--fts", help="Use FTS5 full-text search"),
    hybrid: bool = typer.Option(False, "--hybrid", help="Hybrid search: FTS5 relevance + recency via RRF"),
    semantic: bool = typer.Option(False, "--semantic", help="Use semantic search"),
    file: Optional[str] = typer.Option(None, "--file", help="Filter by file path"),
    commit: Optional[str] = typer.Option(None, "--commit", help="Filter by commit hash"),
    agent: Optional[str] = typer.Option(None, "--agent", help="Filter by agent type"),
    since: Optional[str] = typer.Option(None, "--since", help="Filter by date (ISO8601)"),
    target: str = typer.Option("turn", "-t", help="Search target: turn|session|event|content"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
    global_search: bool = typer.Option(False, "--global", "-g", help="Search across all registered repos"),
    repo: Optional[List[str]] = typer.Option(None, "--repo", "-r", help="Filter by repo name (repeatable)"),
):
    """Search across sessions, turns, and events."""
    if sum([bool(semantic), bool(hybrid), bool(fts)]) > 1:
        console.print("[red]--semantic, --hybrid, and --fts are mutually exclusive.[/red]")
        raise typer.Exit(1)

    is_cross_repo = global_search or repo
    retrieval_event_id = None

    if is_cross_repo:
        from ..core.cross_repo import cross_repo_search

        if hybrid:
            console.print("[yellow]--hybrid is not supported for cross-repo search; falling back to FTS5.[/yellow]")
        search_type = "semantic" if semantic else ("fts" if fts or hybrid else "regex")
        results = cross_repo_search(
            query,
            search_type=search_type,
            target=target,
            repos=repo,
            file_filter=file,
            commit_filter=commit,
            agent_filter=agent,
            since=since,
            limit=limit,
        )
    else:
        from ..core.project import find_git_root
        from ..core.telemetry import detect_current_context, record_retrieval_event
        from ..db import check_and_migrate, get_db

        repo_path = find_git_root()
        if not repo_path:
            console.print("[red]Not in a git repository.[/red]")
            raise typer.Exit(1)

        conn = get_db(repo_path)
        if isinstance(conn, sqlite3.Connection):
            check_and_migrate(conn)
        if semantic:
            try:
                from ..core.embedding import semantic_search

                started_at = time.perf_counter()
                results = semantic_search(
                    conn,
                    query,
                    file_filter=file,
                    commit_filter=commit,
                    agent_filter=agent,
                    since=since,
                    limit=limit,
                )
                latency_ms = int((time.perf_counter() - started_at) * 1000)
            except ImportError:
                conn.close()
                console.print(
                    "[red]sentence-transformers is required for semantic search. "
                    "Install with: pip install 'entirecontext[semantic]'[/red]"
                )
                raise typer.Exit(1)
        elif hybrid:
            from ..core.hybrid_search import hybrid_search as _hybrid_search

            started_at = time.perf_counter()
            results = _hybrid_search(
                conn,
                query,
                target=target,
                file_filter=file,
                commit_filter=commit,
                agent_filter=agent,
                since=since,
                limit=limit,
            )
            latency_ms = int((time.perf_counter() - started_at) * 1000)
        elif fts:
            from ..core.search import fts_search

            started_at = time.perf_counter()
            results = fts_search(
                conn,
                query,
                target=target,
                file_filter=file,
                commit_filter=commit,
                agent_filter=agent,
                since=since,
                limit=limit,
            )
            latency_ms = int((time.perf_counter() - started_at) * 1000)
        else:
            from ..core.search import regex_search

            started_at = time.perf_counter()
            results = regex_search(
                conn,
                query,
                target=target,
                file_filter=file,
                commit_filter=commit,
                agent_filter=agent,
                since=since,
                limit=limit,
            )
            latency_ms = int((time.perf_counter() - started_at) * 1000)

        session_id, turn_id = detect_current_context(conn)
        retrieval_event = record_retrieval_event(
            conn,
            source="cli",
            search_type="semantic" if semantic else ("hybrid" if hybrid else ("fts" if fts else "regex")),
            target=target,
            query=query,
            result_count=len(results),
            latency_ms=latency_ms,
            session_id=session_id,
            turn_id=turn_id,
            file_filter=file,
            commit_filter=commit,
            agent_filter=agent,
            since_filter=since,
        )
        retrieval_event_id = retrieval_event["id"]

        conn.close()

    if not results:
        console.print("[dim]No results found.[/dim]")
        if not is_cross_repo and retrieval_event_id:
            console.print(f"[dim]Search ID: {retrieval_event_id}[/dim]")
        return

    table = Table(title=f"Search: '{query}' ({len(results)} results)")

    if target == "turn":
        if is_cross_repo:
            table.add_column("Repo", style="cyan", max_width=15)
        table.add_column("Turn ID", style="dim", max_width=12)
        table.add_column("Session", style="dim", max_width=12)
        table.add_column("Message", max_width=50)
        table.add_column("Summary", max_width=40)
        table.add_column("Time")
        for r in results:
            row = []
            if is_cross_repo:
                row.append(r.get("repo_name", ""))
            row.extend(
                [
                    r.get("id", "")[:12],
                    r.get("session_id", "")[:12],
                    (r.get("user_message") or "")[:50],
                    (r.get("assistant_summary") or "")[:40],
                    r.get("timestamp", ""),
                ]
            )
            table.add_row(*row)
    elif target == "session":
        if is_cross_repo:
            table.add_column("Repo", style="cyan", max_width=15)
        table.add_column("Session ID", style="dim", max_width=12)
        table.add_column("Title", max_width=40)
        table.add_column("Summary", max_width=40)
        table.add_column("Turns")
        for r in results:
            row = []
            if is_cross_repo:
                row.append(r.get("repo_name", ""))
            row.extend(
                [
                    r.get("id", "")[:12],
                    r.get("session_title") or "",
                    (r.get("session_summary") or "")[:40],
                    str(r.get("total_turns", 0)),
                ]
            )
            table.add_row(*row)
    elif target == "event":
        if is_cross_repo:
            table.add_column("Repo", style="cyan", max_width=15)
        table.add_column("Event ID", style="dim", max_width=12)
        table.add_column("Title")
        table.add_column("Description", max_width=50)
        for r in results:
            row = []
            if is_cross_repo:
                row.append(r.get("repo_name", ""))
            row.extend(
                [
                    r.get("id", "")[:12],
                    r.get("title", ""),
                    (r.get("description") or "")[:50],
                ]
            )
            table.add_row(*row)
    elif target == "content":
        if is_cross_repo:
            table.add_column("Repo", style="cyan", max_width=15)
        table.add_column("Turn ID", style="dim", max_width=12)
        table.add_column("Session", style="dim", max_width=12)
        table.add_column("Content Path")
        for r in results:
            row = []
            if is_cross_repo:
                row.append(r.get("repo_name", ""))
            row.extend(
                [
                    r.get("turn_id", "")[:12],
                    r.get("session_id", "")[:12],
                    r.get("content_path", ""),
                ]
            )
            table.add_row(*row)

    console.print(table)
    if is_cross_repo:
        console.print("[dim]Search telemetry skipped: cross_repo[/dim]")
    elif retrieval_event_id:
        console.print(f"[dim]Search ID: {retrieval_event_id}[/dim]")


def register(app: typer.Typer) -> None:
    app.command()(search)
