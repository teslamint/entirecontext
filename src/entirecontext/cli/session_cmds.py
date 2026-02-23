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
