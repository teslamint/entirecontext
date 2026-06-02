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
    import threading

    from ..core.project import find_git_root
    from .turn_capture import on_user_prompt

    cwd = data.get("cwd", ".")
    # Resolve git root once — pass to on_user_prompt to avoid a second probe.
    repo_path = find_git_root(cwd)

    on_user_prompt(data, _resolved_repo_path=repo_path)

    session_id = data.get("session_id")
    if not session_id or not repo_path:
        return 0

    prompt_text = data.get("prompt", "")

    try:
        from ..core.config import load_config

        config = load_config(repo_path)

        if not config.get("capture", {}).get("auto_capture", True):
            return 0

        inject_cfg = config.get("decisions", {}).get("injection", {})
        if not inject_cfg.get("inject_on_user_prompt", True):
            return 0

        from ..db import get_db

        timeout_s = int(inject_cfg.get("inject_timeout_ms", 250)) / 1000

        top_k = int(inject_cfg.get("top_k", 5))
        max_tokens = int(inject_cfg.get("max_tokens", 800))
        min_confidence = float(inject_cfg.get("min_confidence", 0.4))

        def _rank_and_trim_in_thread() -> list[dict] | None:
            from ..core.decision_prompt_surfacing import optimize_for_context_budget, rank_decisions_for_prompt

            conn = get_db(repo_path)
            try:
                session_row = conn.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
                if session_row and session_row[0]:
                    try:
                        meta = json.loads(session_row[0])
                        if meta.get("capture_disabled"):
                            return None
                    except (ValueError, TypeError):
                        pass
                surfaced, _ = rank_decisions_for_prompt(
                    conn, repo_path=repo_path, prompt_text=prompt_text, config=config
                )
                return optimize_for_context_budget(
                    surfaced, top_k=top_k, max_tokens=max_tokens, min_confidence=min_confidence
                )
            finally:
                conn.close()

        _result: list[Any] = []
        _exc: list[BaseException] = []

        def _rank_wrapper() -> None:
            try:
                _result.append(_rank_and_trim_in_thread())
            except Exception as e:
                _exc.append(e)

        t = threading.Thread(target=_rank_wrapper, daemon=True)
        t.start()
        t.join(timeout=timeout_s)
        if t.is_alive():
            return 0

        if _exc:
            raise _exc[0]

        if not _result or _result[0] is None:
            return 0

        trimmed = _result[0]

        if trimmed:
            from ..core.decision_prompt_surfacing import _format_decision_entry

            entries = [_format_decision_entry(d, i + 1) for i, d in enumerate(trimmed)]
            md = "## Related Decisions\n\n" + "\n\n".join(entries)
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "UserPromptSubmit",
                            "additionalContext": md,
                        }
                    }
                )
            )
    except Exception as e:
        print(f"EntireContext PDI error: {e}", file=sys.stderr)

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
