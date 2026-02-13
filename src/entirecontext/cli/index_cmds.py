"""Index management commands."""

from __future__ import annotations

import typer
from rich.console import Console

from . import app

console = Console()


@app.command("index")
def index_cmd(
    semantic: bool = typer.Option(
        False, "--semantic", help="Generate semantic embeddings (requires entirecontext[semantic])"
    ),
    force: bool = typer.Option(False, "--force", help="Force regenerate all embeddings"),
    model: str = typer.Option("all-MiniLM-L6-v2", "--model", help="Embedding model name"),
):
    """Rebuild search indexes (FTS5) and optionally generate embeddings."""
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)

    from ..core.indexing import rebuild_fts_indexes

    counts = rebuild_fts_indexes(conn)
    console.print("[green]FTS indexes rebuilt:[/green]")
    for name, count in counts.items():
        console.print(f"  {name}: {count} rows")

    if semantic:
        try:
            from ..core.indexing import generate_embeddings

            count = generate_embeddings(conn, repo_path, model_name=model, force=force)
            console.print(f"[green]Generated {count} embeddings[/green] (model: {model})")
        except ImportError as e:
            console.print(f"[red]{e}[/red]")
            conn.close()
            raise typer.Exit(1)

    conn.close()
