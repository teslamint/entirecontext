"""Shared CLI helpers to reduce boilerplate across command modules."""

from __future__ import annotations

import sqlite3

import typer
from rich.console import Console

console = Console()


def get_repo_connection(*, migrate: bool = True) -> tuple[sqlite3.Connection, str]:
    """Get a DB connection for the current git repository.

    Returns (conn, repo_path). Prints an error and exits if not in a git repo.
    Caller is responsible for closing the connection.
    """
    from ..core.project import find_git_root
    from ..db import check_and_migrate, get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    if migrate and isinstance(conn, sqlite3.Connection):
        check_and_migrate(conn)
    return conn, repo_path
