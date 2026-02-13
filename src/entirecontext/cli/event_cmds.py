"""Event management commands."""

from __future__ import annotations

from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from . import app

console = Console()
event_app = typer.Typer(help="Event management")
app.add_typer(event_app, name="event")


@event_app.command("list")
def event_list(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (active/frozen/archived)"),
    event_type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by type (task/temporal/milestone)"),
    limit: int = typer.Option(20, "--limit", "-n"),
    global_search: bool = typer.Option(False, "--global", "-g", help="List events across all registered repos"),
    repo: Optional[List[str]] = typer.Option(None, "--repo", "-r", help="Filter by repo name (repeatable)"),
):
    """List events."""
    is_cross_repo = global_search or repo

    if is_cross_repo:
        from ..core.cross_repo import cross_repo_events

        events, warnings = cross_repo_events(
            repos=repo, status=status, event_type=event_type, limit=limit, include_warnings=True
        )

        if not events:
            console.print("[dim]No events found.[/dim]")
            return

        table = Table(title=f"Events ({len(events)})")
        table.add_column("Repo", style="cyan", max_width=15)
        table.add_column("ID", style="dim", max_width=12)
        table.add_column("Title")
        table.add_column("Type")
        table.add_column("Status")
        table.add_column("Created")

        for e in events:
            status_str = "[green]active[/green]" if e["status"] == "active" else e["status"]
            table.add_row(
                e.get("repo_name", ""),
                e["id"][:12],
                e.get("title", ""),
                e.get("event_type", ""),
                status_str,
                e.get("created_at", ""),
            )

        console.print(table)
        for w in warnings:
            console.print(f"[dim]{w}[/dim]")
        return

    from ..core.event import list_events
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    events = list_events(conn, status=status, event_type=event_type, limit=limit)
    conn.close()

    if not events:
        console.print("[dim]No events found.[/dim]")
        return

    table = Table(title=f"Events ({len(events)})")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Title")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Created")

    for e in events:
        status_str = "[green]active[/green]" if e["status"] == "active" else e["status"]
        table.add_row(
            e["id"][:12],
            e.get("title", ""),
            e.get("event_type", ""),
            status_str,
            e.get("created_at", ""),
        )

    console.print(table)


@event_app.command("show")
def event_show(event_id: str = typer.Argument(..., help="Event ID")):
    """Show event details and linked sessions."""
    from ..core.event import get_event, get_event_sessions
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)

    event = get_event(conn, event_id)
    if not event:
        row = conn.execute("SELECT * FROM events WHERE id LIKE ?", (f"{event_id}%",)).fetchone()
        if row:
            event = dict(row)

    if not event:
        console.print(f"[red]Event not found:[/red] {event_id}")
        conn.close()
        raise typer.Exit(1)

    console.print(f"\n[bold]Event:[/bold] {event['id']}")
    console.print(f"  Title: {event.get('title', '')}")
    console.print(f"  Type: {event.get('event_type', '')}")
    console.print(f"  Status: {event.get('status', '')}")
    console.print(f"  Created: {event.get('created_at', '')}")
    if event.get("description"):
        console.print(f"  Description: {event['description']}")

    sessions = get_event_sessions(conn, event["id"])
    conn.close()

    if sessions:
        console.print(f"\n[bold]Linked Sessions ({len(sessions)}):[/bold]")
        for s in sessions:
            status_str = "active" if s.get("ended_at") is None else "ended"
            console.print(f"  {s['id'][:12]}  {s.get('session_type', '')}  {status_str}")


@event_app.command("create")
def event_create(
    title: str = typer.Argument(..., help="Event title"),
    event_type: str = typer.Option("task", "--type", "-t", help="Event type (task/temporal/milestone)"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Event description"),
):
    """Create a new event."""
    from ..core.event import create_event
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        event = create_event(conn, title, event_type=event_type, description=description)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        conn.close()
        raise typer.Exit(1)
    conn.close()

    console.print(f"[green]Created event:[/green] {event['id']}")


@event_app.command("link")
def event_link(
    event_id: str = typer.Argument(..., help="Event ID"),
    session_id: str = typer.Argument(..., help="Session ID"),
):
    """Link a session to an event."""
    from ..core.event import get_event, link_event_session
    from ..core.project import find_git_root
    from ..core.session import get_session
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)

    event = get_event(conn, event_id)
    if not event:
        console.print(f"[red]Event not found:[/red] {event_id}")
        conn.close()
        raise typer.Exit(1)

    session = get_session(conn, session_id)
    if not session:
        console.print(f"[red]Session not found:[/red] {session_id}")
        conn.close()
        raise typer.Exit(1)

    link_event_session(conn, event_id, session_id)
    conn.close()

    console.print(f"[green]Linked session {session_id[:12]} to event {event_id[:12]}[/green]")
