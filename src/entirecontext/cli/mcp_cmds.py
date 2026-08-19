"""MCP server commands."""

from __future__ import annotations

import typer
from rich.console import Console

# stderr: `ec mcp serve` speaks JSON-RPC over stdout, so diagnostics must not
# touch stdout even on the failure paths.
console = Console(stderr=True)
mcp_app = typer.Typer(help="MCP server management")


@mcp_app.command("serve")
def mcp_serve():
    """Start the MCP server (stdio transport)."""
    try:
        from ..mcp.server import run_server
    except ImportError as exc:
        console.print(f"[red]MCP server module import failed: {exc}[/red]")
        console.print("[yellow]Install the extra: uv tool install --force 'entirecontext[mcp] @ <repo path>'[/yellow]")
        raise typer.Exit(1) from exc

    # Deliberately outside the try: exceptions raised inside run_server keep
    # their own traceback instead of being misreported as an import problem.
    run_server()


def register(app: typer.Typer) -> None:
    app.add_typer(mcp_app, name="mcp")
