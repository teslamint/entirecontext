"""CLI commands for purging turns, sessions, and content."""

from __future__ import annotations

import typer

from . import app

purge_app = typer.Typer(help="Purge turns, sessions, or matching content.")
app.add_typer(purge_app, name="purge")


def _get_conn_and_repo():
    from ..core.project import find_git_root
    from ..db import get_db, check_and_migrate

    repo_path = find_git_root()
    if not repo_path:
        typer.echo("Error: not in an EntireContext-initialized repo", err=True)
        raise typer.Exit(1)
    conn = get_db(repo_path)
    check_and_migrate(conn)
    return conn, repo_path


@purge_app.command("session")
def purge_session_cmd(
    session_id: str = typer.Argument(..., help="Session ID to purge"),
    execute: bool = typer.Option(False, "--execute", help="Actually delete (default is dry-run)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Purge an entire session and all its turns."""
    from ..core.purge import ActiveSessionError, purge_session

    conn, repo_path = _get_conn_and_repo()
    try:
        dry_run = not execute
        if execute and not force:
            typer.confirm(f"Permanently delete session {session_id} and all turns?", abort=True)

        result = purge_session(conn, repo_path, session_id, dry_run=dry_run)

        if result.get("error"):
            typer.echo(f"Error: {result['error']}", err=True)
            raise typer.Exit(1)

        if dry_run:
            typer.echo(f"[DRY RUN] Would delete {result['matched_turns']} turns from session {session_id}")
        else:
            typer.echo(f"Deleted {result['deleted']} turns from session {session_id}")

        for p in result.get("previews", [])[:10]:
            typer.echo(f"  - {p['id'][:8]}... {p['user_message']}")

    except ActiveSessionError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    finally:
        conn.close()


@purge_app.command("turn")
def purge_turn_cmd(
    turn_ids: list[str] = typer.Argument(..., help="Turn IDs to purge"),
    execute: bool = typer.Option(False, "--execute", help="Actually delete (default is dry-run)"),
):
    """Purge specific turns by ID."""
    from ..core.purge import purge_turns

    conn, repo_path = _get_conn_and_repo()
    try:
        result = purge_turns(conn, repo_path, turn_ids, dry_run=not execute)

        if not execute:
            typer.echo(f"[DRY RUN] Would delete {result['matched_turns']} turns")
        else:
            typer.echo(f"Deleted {result['deleted']} turns")

        for p in result.get("previews", [])[:10]:
            typer.echo(f"  - {p['id'][:8]}... {p['user_message']}")

    finally:
        conn.close()


@purge_app.command("match")
def purge_match_cmd(
    pattern: str = typer.Argument(..., help="Regex pattern to match against turn content"),
    execute: bool = typer.Option(False, "--execute", help="Actually delete (default is dry-run)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Purge turns matching a regex pattern."""
    from ..core.purge import purge_by_pattern

    conn, repo_path = _get_conn_and_repo()
    try:
        dry_run = not execute
        result_preview = purge_by_pattern(conn, repo_path, pattern, dry_run=True)

        if result_preview["matched_turns"] == 0:
            typer.echo("No matching turns found.")
            return

        if dry_run:
            typer.echo(f"[DRY RUN] Would delete {result_preview['matched_turns']} turns matching '{pattern}'")
            for p in result_preview.get("previews", [])[:10]:
                typer.echo(f"  - {p['id'][:8]}... {p['user_message']}")
            return

        if not force:
            typer.confirm(
                f"Permanently delete {result_preview['matched_turns']} turns matching '{pattern}'?",
                abort=True,
            )

        result = purge_by_pattern(conn, repo_path, pattern, dry_run=False)
        typer.echo(f"Deleted {result['deleted']} turns matching '{pattern}'")

    finally:
        conn.close()
