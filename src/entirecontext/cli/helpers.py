"""Shared CLI helpers to reduce boilerplate across command modules."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import typer
from rich.console import Console

if TYPE_CHECKING:
    from ..core.repo_roots import RepoRoots

console = Console()


def get_repo_roots_connection(*, migrate: bool = True) -> tuple[sqlite3.Connection, RepoRoots]:
    """Get a DB connection plus the project/workspace roots for the current checkout.

    The connection is opened at ``roots.project_root``; Git work belongs in
    ``roots.workspace_root``. Prints an error and exits if not in a git repo.
    Caller is responsible for closing the connection.
    """
    from ..core.project import get_repo_roots
    from ..db import check_and_migrate, get_db

    roots = get_repo_roots()
    if not roots:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(roots.project_root)
    if migrate:
        check_and_migrate(conn)
    return conn, roots


def get_repo_connection(*, migrate: bool = True) -> tuple[sqlite3.Connection, str]:
    """Get a DB connection for the current git repository.

    Returns (conn, project_root). The path is the canonical project root, so
    use it only for DB, config and ``.entirecontext`` content; commands that
    run Git should use ``get_repo_roots_connection`` and the workspace root.
    Prints an error and exits if not in a git repo. Caller is responsible for
    closing the connection.
    """
    conn, roots = get_repo_roots_connection(migrate=migrate)
    return conn, roots.project_root
