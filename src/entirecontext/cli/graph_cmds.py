"""Knowledge graph command — git entities as nodes, relations as edges."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from . import app

console = Console()


@app.command("graph")
def graph_cmd(
    session_id: str | None = typer.Option(
        None, "--session", "-s", help="Restrict graph to a single session ID"
    ),
    since: str | None = typer.Option(
        None, "--since", help="Only include turns on or after this date (YYYY-MM-DD)"
    ),
    limit: int = typer.Option(
        200, "--limit", "-n", help="Maximum number of turns to include (default 200)"
    ),
):
    """Show the knowledge graph of git entities (commits, files, sessions, agents).

    Builds a graph from existing DB data — no new git subprocess calls.
    Displays a summary table of node/edge counts by type.
    """
    from ..core.knowledge_graph import build_knowledge_graph, get_graph_stats
    from ..core.project import find_git_root
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        graph = build_knowledge_graph(conn, session_id=session_id, since=since, limit=limit)
    finally:
        conn.close()

    stats = get_graph_stats(graph)

    if stats["total_nodes"] == 0:
        console.print("[dim]No graph data found. Run some sessions first.[/dim]")
        return

    # Nodes by type table
    nodes_table = Table(title="Knowledge Graph — Nodes")
    nodes_table.add_column("Type", style="cyan")
    nodes_table.add_column("Count", justify="right")

    for ntype, count in sorted(stats["nodes_by_type"].items()):
        nodes_table.add_row(ntype, str(count))
    nodes_table.add_row("[bold]Total[/bold]", f"[bold]{stats['total_nodes']}[/bold]")

    console.print(nodes_table)

    # Edges by relation table
    edges_table = Table(title="Knowledge Graph — Edges")
    edges_table.add_column("Relation", style="green")
    edges_table.add_column("Count", justify="right")

    for rel, count in sorted(stats["edges_by_relation"].items()):
        edges_table.add_row(rel, str(count))
    edges_table.add_row("[bold]Total[/bold]", f"[bold]{stats['total_edges']}[/bold]")

    console.print(edges_table)
