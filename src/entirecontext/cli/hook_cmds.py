"""Hook entry points called by Claude Code."""

from __future__ import annotations

import sys

import typer

from . import app

hook_app = typer.Typer(help="Hook handlers (called by Claude Code)")
app.add_typer(hook_app, name="hook")


@hook_app.command("handle")
def hook_handle():
    """Read stdin JSON and dispatch to appropriate hook handler."""
    from ..hooks.handler import handle_hook

    hook_type = None
    import json

    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
            hook_type = data.get("hook_type") or data.get("type")
    except (json.JSONDecodeError, OSError):
        pass

    if hook_type:
        import io

        sys.stdin = io.StringIO(raw if "raw" in dir() else "")

    exit_code = handle_hook(hook_type)
    raise typer.Exit(exit_code)
