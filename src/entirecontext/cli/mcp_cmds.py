"""MCP server commands."""

from __future__ import annotations

import typer
from rich.console import Console

from . import app

console = Console()
mcp_app = typer.Typer(help="MCP server management")
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("serve")
def mcp_serve():
    """Start the MCP server (stdio transport)."""
    try:
        from ..mcp.server import run_server

        run_server()
    except ImportError:
        console.print("[red]MCP not available. Install with: pip install 'entirecontext[mcp]'[/red]")
        raise typer.Exit(1)
