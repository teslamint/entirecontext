"""AST-based semantic search commands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from . import app

console = Console()


@app.command("ast-search")
def ast_search_cmd(
    query: str = typer.Argument(..., help="Search query (name, docstring keyword, etc.)"),
    symbol_type: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter by symbol type: function, class, or method",
    ),
    file_filter: str | None = typer.Option(
        None,
        "--file",
        "-f",
        help="Restrict results to this file path",
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum results (default 20)"),
):
    """Search indexed Python AST symbols by name, qualified name, or docstring.

    Searches the ``ast_symbols`` table via FTS5 full-text indexing.
    Index files first with ``ec ast-index <file>`` or via the post-turn hook.
    """
    from ..core.ast_index import search_ast_symbols
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        results = search_ast_symbols(conn, query, symbol_type=symbol_type, file_filter=file_filter, limit=limit)
    finally:
        conn.close()

    if not results:
        console.print("[dim]No matching symbols found.[/dim]")
        return

    table = Table(title=f"AST Symbol Search: {query!r} ({len(results)} results)")
    table.add_column("Type", style="cyan", max_width=10)
    table.add_column("Qualified Name", style="bold", max_width=40)
    table.add_column("File", style="dim", max_width=30)
    table.add_column("Lines", justify="right", max_width=10)
    table.add_column("Docstring", max_width=40)

    for r in results:
        lines = f"{r.get('start_line', '?')}–{r.get('end_line', '?')}"
        doc = (r.get("docstring") or "")[:40]
        table.add_row(
            r.get("symbol_type", ""),
            r.get("qualified_name", r.get("name", "")),
            r.get("file_path", ""),
            lines,
            doc,
        )

    console.print(table)
