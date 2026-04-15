"""Main hook handler — reads stdin JSON and dispatches to appropriate handler."""

from __future__ import annotations

import json
import sys
from typing import Any

from ..core.context import RepoContext


def read_stdin_json() -> dict[str, Any]:
    """Read and parse JSON from stdin (Claude Code hook protocol)."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def handle_hook(hook_type: str | None = None, *, data: dict[str, Any] | None = None) -> int:
    """Main entry point: read stdin JSON, dispatch to handler.

    Returns exit code: 0=success, 2=block.
    """
    if data is None:
        data = read_stdin_json()

    if hook_type is None:
        hook_type = data.get("hook_type", "")

    handlers = {
        "SessionStart": _handle_session_start,
        "UserPromptSubmit": _handle_user_prompt,
        "Stop": _handle_stop,
        "PostToolUse": _handle_tool_use,
        "SessionEnd": _handle_session_end,
        "PostCommit": _handle_post_commit,
    }

    handler = handlers.get(hook_type)
    if handler is None:
        return 0

    try:
        return handler(data)
    except Exception as e:
        cwd = data.get("cwd", ".") if data else "."
        context = RepoContext.from_cwd(cwd)
        if context is not None:
            with context:
                from ..core.telemetry import record_operation_event

                session_id, turn_id = None, None
                if context.current_session_id:
                    session_id = context.current_session_id
                record_operation_event(
                    context.conn,
                    source="hook",
                    operation_name="handle_hook",
                    phase=hook_type or "unknown",
                    status="warning",
                    error_class=type(e).__name__,
                    message=str(e),
                    session_id=session_id,
                    turn_id=turn_id,
                )
        print(f"EntireContext hook error ({hook_type}): {e}", file=sys.stderr)
        return 0


def _handle_session_start(data: dict[str, Any]) -> int:
    from .session_lifecycle import on_session_start

    on_session_start(data)

    try:
        from .decision_hooks import on_session_start_decisions

        result = on_session_start_decisions(data)
        if result:
            print(result)
    except Exception:
        pass
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

    try:
        from .decision_hooks import on_post_tool_use_decisions

        result = on_post_tool_use_decisions(data)
        if result:
            print(result)
    except Exception:
        pass
    return 0


def _handle_session_end(data: dict[str, Any]) -> int:
    from .session_lifecycle import on_session_end

    on_session_end(data)
    return 0


def _handle_post_commit(data: dict[str, Any]) -> int:
    from .session_lifecycle import on_post_commit

    on_post_commit(data)
    return 0
