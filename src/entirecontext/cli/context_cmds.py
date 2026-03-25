"""Context telemetry commands."""

from __future__ import annotations

import sqlite3

import typer
from rich.console import Console

console = Console()
context_app = typer.Typer(help="Context telemetry")


@context_app.command("select")
def context_select(
    retrieval_event_id: str = typer.Argument(..., help="Retrieval event ID"),
    result_type: str = typer.Argument(..., help="Selected result type"),
    result_id: str = typer.Argument(..., help="Selected result ID"),
    rank: int = typer.Option(1, "--rank", min=1, help="Rank of the selected result"),
) -> None:
    from ..core.project import find_git_root
    from ..core.telemetry import record_retrieval_selection
    from ..db import check_and_migrate, get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        if isinstance(conn, sqlite3.Connection):
            check_and_migrate(conn)
        selection = record_retrieval_selection(
            conn,
            retrieval_event_id,
            result_type,
            result_id,
            rank=rank,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    finally:
        conn.close()

    console.print(f"Selection ID: {selection['id']}")


@context_app.command("apply")
def context_apply(
    application_type: str = typer.Argument(..., help="Application type"),
    selection_id: str | None = typer.Option(None, "--selection-id", help="Retrieval selection ID"),
    source_type: str | None = typer.Option(None, "--source-type", help="Source type when no selection is provided"),
    source_id: str | None = typer.Option(None, "--source-id", help="Source ID when no selection is provided"),
    note: str | None = typer.Option(None, "--note", help="Optional note"),
) -> None:
    from ..core.project import find_git_root
    from ..core.telemetry import detect_current_context, record_context_application
    from ..db import check_and_migrate, get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        if isinstance(conn, sqlite3.Connection):
            check_and_migrate(conn)
        session_id, turn_id = detect_current_context(conn)
        application = record_context_application(
            conn,
            application_type=application_type,
            selection_id=selection_id,
            source_type=source_type,
            source_id=source_id,
            note=note,
            session_id=session_id,
            turn_id=turn_id,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    finally:
        conn.close()

    console.print(f"Application ID: {application['id']}")


def register(app: typer.Typer) -> None:
    app.add_typer(context_app, name="context")
