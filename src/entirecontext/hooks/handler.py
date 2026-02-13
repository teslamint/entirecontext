"""Main hook handler — reads stdin JSON and dispatches to appropriate handler."""

from __future__ import annotations

import json
import sys
from typing import Any


def read_stdin_json() -> dict[str, Any]:
    """Read and parse JSON from stdin (Claude Code hook protocol)."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def handle_hook(hook_type: str | None = None) -> int:
    """Main entry point: read stdin JSON, dispatch to handler.

    Returns exit code: 0=success, 2=block.
    """
    data = read_stdin_json()

    if hook_type is None:
        hook_type = data.get("hook_type", "")

    handlers = {
        "SessionStart": _handle_session_start,
        "UserPromptSubmit": _handle_user_prompt,
        "Stop": _handle_stop,
        "PostToolUse": _handle_tool_use,
        "SessionEnd": _handle_session_end,
    }

    handler = handlers.get(hook_type)
    if handler is None:
        return 0

    try:
        return handler(data)
    except Exception as e:
        print(f"EntireContext hook error ({hook_type}): {e}", file=sys.stderr)
        return 0


def _handle_session_start(data: dict[str, Any]) -> int:
    from .session_lifecycle import on_session_start

    on_session_start(data)
    return 0


def _handle_user_prompt(data: dict[str, Any]) -> int:
    from .turn_capture import on_user_prompt

    on_user_prompt(data)
    return 0


def _handle_stop(data: dict[str, Any]) -> int:
    from .turn_capture import on_stop

    on_stop(data)
    return 0


def _handle_tool_use(data: dict[str, Any]) -> int:
    from .turn_capture import on_tool_use

    on_tool_use(data)
    return 0


def _handle_session_end(data: dict[str, Any]) -> int:
    from .session_lifecycle import on_session_end

    on_session_end(data)
    return 0
