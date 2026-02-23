"""Session management commands."""

from __future__ import annotations

from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from . import app

console = Console()
session_app = typer.Typer(help="Session management")
app.add_typer(session_app, name="session")


@session_app.command("list")
def session_list(
    limit: int = typer.Option(20, "--limit", "-n"),
    global_search: bool = typer.Option(False, "--global", "-g", help="List sessions across all registered repos"),
    repo: Optional[List[str]] = typer.Option(None, "--repo", "-r", help="Filter by repo name (repeatable)"),
):
    """List sessions."""
    is_cross_repo = global_search or repo

    if is_cross_repo:
        from ..core.cross_repo import cross_repo_sessions

        sessions = cross_repo_sessions(repos=repo, limit=limit)

        if not sessions:
            console.print("[dim]No sessions found.[/dim]")
            return

        table = Table(title=f"Sessions ({len(sessions)})")
        table.add_column("Repo", style="cyan", max_width=15)
        table.add_column("ID", style="dim", max_width=12)
        table.add_column("Type")
        table.add_column("Started")
        table.add_column("Turns")
        table.add_column("Status")

        for s in sessions:
            status = "[green]active[/green]" if s.get("ended_at") is None else "ended"
            table.add_row(
                s.get("repo_name", ""),
                s["id"][:12],
                s.get("session_type", ""),
                s.get("started_at", ""),
                str(s.get("total_turns", 0)),
                status,
            )

        console.print(table)
        return

    from ..core.project import find_git_root, get_project
    from ..core.session import list_sessions
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    project = get_project(repo_path)
    if not project:
        console.print("[yellow]Not initialized. Run 'ec init'.[/yellow]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    sessions = list_sessions(conn, project_id=project["id"], limit=limit)
    conn.close()

    if not sessions:
        console.print("[dim]No sessions found.[/dim]")
        return

    table = Table(title=f"Sessions ({len(sessions)})")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Type")
    table.add_column("Started")
    table.add_column("Turns")
    table.add_column("Status")

    for s in sessions:
        status = "[green]active[/green]" if s.get("ended_at") is None else "ended"
        table.add_row(
            s["id"][:12],
            s.get("session_type", ""),
            s.get("started_at", ""),
            str(s.get("total_turns", 0)),
            status,
        )

    console.print(table)


@session_app.command("show")
def session_show(
    session_id: str = typer.Argument(..., help="Session ID"),
    global_search: bool = typer.Option(False, "--global", "-g", help="Search across all registered repos"),
    repo: Optional[List[str]] = typer.Option(None, "--repo", "-r", help="Filter by repo name (repeatable)"),
):
    """Show session details and turn summaries."""
    is_cross_repo = global_search or repo

    if is_cross_repo:
        from ..core.cross_repo import cross_repo_session_detail

        result, warnings = cross_repo_session_detail(session_id, repos=repo, include_warnings=True)

        if not result:
            console.print(f"[red]Session not found:[/red] {session_id}")
            raise typer.Exit(1)

        session = result
        console.print(f"\n[bold]Session:[/bold] {session['id']}")
        console.print(f"  Repo: {session.get('repo_name', '')}")
        console.print(f"  Type: {session.get('session_type', '')}")
        console.print(f"  Started: {session.get('started_at', '')}")
        console.print(f"  Ended: {session.get('ended_at') or 'active'}")
        console.print(f"  Turns: {session.get('total_turns', 0)}")
        if session.get("session_title"):
            console.print(f"  Title: {session['session_title']}")
        if session.get("session_summary"):
            console.print(f"  Summary: {session['session_summary']}")

        turns = session.get("turns", [])
        if turns:
            console.print(f"\n[bold]Turns ({len(turns)}):[/bold]")
            for t in turns:
                msg = (t.get("user_message") or "")[:80]
                summary = (t.get("assistant_summary") or "")[:80]
                console.print(f"  #{t['turn_number']}: {msg}")
                if summary:
                    console.print(f"      → {summary}")

        for w in warnings:
            console.print(f"[dim]{w}[/dim]")
        return

    from ..core.project import find_git_root
    from ..core.session import get_session
    from ..core.turn import list_turns
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)

    session = get_session(conn, session_id)
    if not session:
        row = conn.execute("SELECT * FROM sessions WHERE id LIKE ?", (f"{session_id}%",)).fetchone()
        if row:
            session = dict(row)

    if not session:
        console.print(f"[red]Session not found:[/red] {session_id}")
        conn.close()
        raise typer.Exit(1)

    console.print(f"\n[bold]Session:[/bold] {session['id']}")
    console.print(f"  Type: {session.get('session_type', '')}")
    console.print(f"  Started: {session.get('started_at', '')}")
    console.print(f"  Ended: {session.get('ended_at') or 'active'}")
    console.print(f"  Turns: {session.get('total_turns', 0)}")
    if session.get("session_title"):
        console.print(f"  Title: {session['session_title']}")
    if session.get("session_summary"):
        console.print(f"  Summary: {session['session_summary']}")

    turns = list_turns(conn, session["id"])
    conn.close()

    if turns:
        console.print(f"\n[bold]Turns ({len(turns)}):[/bold]")
        for t in turns:
            msg = (t.get("user_message") or "")[:80]
            summary = (t.get("assistant_summary") or "")[:80]
            console.print(f"  #{t['turn_number']}: {msg}")
            if summary:
                console.print(f"      → {summary}")


@session_app.command("current")
def session_current():
    """Show current active session."""
    from ..core.project import find_git_root
    from ..core.session import get_current_session
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    session = get_current_session(conn)
    conn.close()

    if not session:
        console.print("[dim]No active session.[/dim]")
        return

    console.print(f"[bold]Active Session:[/bold] {session['id']}")
    console.print(f"  Started: {session.get('started_at', '')}")
    console.print(f"  Turns: {session.get('total_turns', 0)}")


@session_app.command("export")
def session_export(
    session_id: str = typer.Argument(..., help="Session ID (prefix supported)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Write to file; omit to print to stdout"),
):
    """Export a session as a Markdown document (git-friendly sharing format)."""
    from pathlib import Path

    from ..core.export import export_session_markdown
    from ..core.project import find_git_root, get_project
    from ..core.session import get_session
    from ..core.turn import list_turns
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)

    session = get_session(conn, session_id)
    if not session:
        row = conn.execute("SELECT * FROM sessions WHERE id LIKE ?", (f"{session_id}%",)).fetchone()
        if row:
            session = dict(row)

    if not session:
        console.print(f"[red]Session not found:[/red] {session_id}")
        conn.close()
        raise typer.Exit(1)

    project = get_project(repo_path)
    project_name = project.get("name") if project else None

    turns = list_turns(conn, session["id"])
    conn.close()

    markdown = export_session_markdown(session, turns, project_name=project_name)

    if output:
        Path(output).write_text(markdown, encoding="utf-8")
        console.print(f"[green]Exported to:[/green] {output}")
    else:
        typer.echo(markdown)


@session_app.command("consolidate")
def session_consolidate(
    before: Optional[str] = typer.Option(
        None,
        "--before",
        help="Consolidate turns older than this date (YYYY-MM-DD). Defaults to 30 days ago.",
    ),
    session_id: Optional[str] = typer.Option(None, "--session", "-s", help="Restrict to a single session ID"),
    limit: int = typer.Option(500, "--limit", "-n", help="Maximum number of turns to consolidate"),
    execute: bool = typer.Option(False, "--execute", help="Actually delete content files (default is dry-run)"),
):
    """Consolidate old turn content files to save storage (preserves metadata).

    By default runs in dry-run mode — use --execute to actually delete content files.
    """
    from datetime import datetime, timedelta, timezone

    from ..core.consolidation import consolidate_old_turns
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    if before is None:
        before = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    conn = get_db(repo_path)
    stats = consolidate_old_turns(
        conn,
        repo_path,
        before_date=before,
        session_id=session_id,
        limit=limit,
        dry_run=not execute,
    )
    conn.close()

    if not execute:
        console.print(f"[dim]Dry-run:[/dim] {stats['candidates']} turns eligible for consolidation (before {before}).")
        console.print("[dim]Use --execute to actually consolidate.[/dim]")
    else:
        console.print(f"[green]Consolidated {stats['consolidated']} turns[/green] (of {stats['candidates']} eligible).")


@session_app.command("graph")
def session_graph(
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Root agent ID (prefix supported)"),
    session_id: Optional[str] = typer.Option(None, "--session", "-s", help="Seed session ID (uses its agent as root)"),
    depth: int = typer.Option(3, "--depth", "-d", help="Maximum depth of agent hierarchy to traverse (default 3)"),
):
    """Visualise the multi-agent session graph rooted at an agent or session.

    Traverses ``agents.parent_agent_id`` edges downward from the root agent,
    displaying all spawned child agents up to *depth* levels and the number
    of sessions associated with each agent.
    """
    from ..core.agent_graph import build_agent_graph
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    if not agent and not session_id:
        console.print("[red]Provide --agent or --session to seed the graph.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        graph = build_agent_graph(conn, root_agent_id=agent, session_id=session_id, depth=depth)
    finally:
        conn.close()

    nodes = graph["nodes"]
    edges = graph["edges"]

    if not nodes:
        console.print("[dim]No agents found.[/dim]")
        return

    # Build a parent→children map for tree display
    children_map: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for edge in edges:
        src, tgt = edge["source"], edge["target"]
        if src in children_map:
            children_map[src].append(tgt)

    node_map = {n["id"]: n for n in nodes}

    # Determine roots: nodes with no incoming edges within the graph
    has_parent_in_graph = {e["target"] for e in edges}
    roots = [n["id"] for n in nodes if n["id"] not in has_parent_in_graph]

    # Display as tree using Rich (iterative BFS to avoid recursion depth issues)
    from collections import deque

    from rich.tree import Tree

    def _agent_label(nid: str) -> str:
        n = node_map.get(nid, {})
        label = n.get("name") or nid[:12]
        atype = n.get("agent_type") or ""
        sessions = n.get("session_count", 0)
        role = f" [{n['role']}]" if n.get("role") else ""
        return f"{label}{role}  [dim]({atype}, {sessions} sessions)[/dim]"

    def _build_tree(root_id: str) -> Tree:
        root_tree = Tree(_agent_label(root_id))
        # Iterative BFS: queue of (tree_node, agent_id)
        bfs_queue: deque[tuple[object, str]] = deque([(root_tree, root_id)])
        visited: set[str] = {root_id}
        while bfs_queue:
            parent_node, current_id = bfs_queue.popleft()
            for child_id in children_map.get(current_id, []):
                if child_id not in visited:
                    visited.add(child_id)
                    child_node = parent_node.add(_agent_label(child_id))
                    bfs_queue.append((child_node, child_id))
        return root_tree

    for root_id in roots:
        console.print(_build_tree(root_id))

    console.print(
        f"\n[dim]{len(nodes)} agents, {len(edges)} edges (depth={depth})[/dim]"
    )


@session_app.command("activate")
def session_activate(
    turn: Optional[str] = typer.Option(None, "--turn", "-t", help="Seed turn ID (prefix supported)"),
    session_id: Optional[str] = typer.Option(None, "--session", "-s", help="Seed all turns in this session"),
    hops: int = typer.Option(2, "--hops", "-H", help="Maximum traversal hops (default 2)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum results to return"),
):
    """Find related turns via spreading activation (shared files / commits).

    Propagates activation from a seed turn or session through the graph of
    shared ``files_touched`` and ``git_commit_hash`` edges, returning the most
    strongly connected turns ranked by activation score.
    """
    from ..core.activation import spread_activation
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    if not turn and not session_id:
        console.print("[red]Provide --turn or --session to seed activation.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    results = spread_activation(
        conn,
        seed_turn_id=turn,
        seed_session_id=session_id,
        max_hops=hops,
        limit=limit,
    )
    conn.close()

    if not results:
        console.print("[dim]No related turns found.[/dim]")
        return

    from rich.table import Table

    table = Table(title=f"Related Turns via Spreading Activation ({len(results)})")
    table.add_column("Score", justify="right", style="cyan", max_width=8)
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Session", style="dim", max_width=12)
    table.add_column("Message", max_width=60)
    table.add_column("Date", max_width=12)

    for r in results:
        score = f"{r['activation_score']:.3f}"
        msg = (r.get("user_message") or "")[:60]
        date = (r.get("timestamp") or "")[:10]
        table.add_row(score, r["id"][:12], r["session_id"][:12], msg, date)

    console.print(table)
