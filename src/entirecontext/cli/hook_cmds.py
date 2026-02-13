"""Hook entry points called by Claude Code."""

from __future__ import annotations

import sys

import typer

from . import app

hook_app = typer.Typer(help="Hook handlers (called by Claude Code)")
app.add_typer(hook_app, name="hook")


@hook_app.command("handle")
def hook_handle(
    hook_type_arg: str = typer.Option(None, "--type", "-t", help="Hook type (e.g. SessionStart)"),
):
    """Read stdin JSON and dispatch to appropriate hook handler."""
    import io
    import json

    from ..hooks.handler import handle_hook

    raw = ""
    data = {}
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        pass

    resolved_type = hook_type_arg
    if not resolved_type:
        resolved_type = data.get("hook_type") or data.get("type")

    if raw.strip():
        sys.stdin = io.StringIO(raw)

    exit_code = handle_hook(resolved_type, data=data if data else None)
    raise typer.Exit(exit_code)
