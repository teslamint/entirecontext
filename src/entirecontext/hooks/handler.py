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

    try:
        _surface_lessons_on_start(data)
    except Exception:
        pass

    return 0


def _surface_lessons_on_start(data: dict[str, Any]) -> None:
    """Surface relevant lessons at SessionStart. Never raises to caller."""
    from ..core.config import load_config
    from ..core.project import find_git_root

    cwd = data.get("cwd", ".")
    repo_path = find_git_root(cwd)
    if not repo_path:
        return

    config = load_config(repo_path)
    if not config.get("capture", {}).get("surface_lessons_on_start", True):
        return

    session_id = data.get("session_id")

    from ..core.decision_prompt_surfacing import (
        _get_recent_commit_file_paths,
        _get_uncommitted_file_paths,
    )
    from ..core.lesson_surfacing import (
        format_lesson_entry,
        rank_lessons_for_prompt,
    )
    from ..db import get_db

    file_paths = _get_uncommitted_file_paths(repo_path)
    commit_file_paths = _get_recent_commit_file_paths(repo_path, limit=5)
    if commit_file_paths:
        seen = set(file_paths)
        for p in commit_file_paths:
            if p not in seen:
                seen.add(p)
                file_paths.append(p)

    conn = get_db(repo_path)
    try:
        lessons = rank_lessons_for_prompt(conn, file_paths=file_paths, limit=5)
        if not lessons:
            return

        from ..core.context import transaction
        from ..core.telemetry import record_retrieval_event, record_retrieval_selection

        with transaction(conn):
            event = record_retrieval_event(
                conn,
                source="hook",
                search_type="lesson_surfacing",
                target="assessment",
                query=",".join(file_paths[:10]) if file_paths else "",
                result_count=len(lessons),
                latency_ms=0,
                session_id=session_id,
                file_filter=",".join(file_paths[:10]) if file_paths else None,
            )
            for idx, lesson in enumerate(lessons, start=1):
                sel = record_retrieval_selection(
                    conn,
                    event["id"],
                    result_type="assessment",
                    result_id=lesson["id"],
                    rank=idx,
                    session_id=session_id,
                )
                lesson["selection_id"] = sel["id"]

        entries = [format_lesson_entry(lesson, i + 1) for i, lesson in enumerate(lessons)]
        output = "## Relevant Lessons\n\n" + "\n\n".join(entries)
        print(output)
    finally:
        conn.close()


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

            # Best-effort lesson surfacing in separate timeout thread —
            # lesson latency must never block decision output.
            # Telemetry is recorded ONLY when the result is used (after
            # timeout check + trim), not inside the thread, so abandoned
            # threads don't create phantom selections.
            try:
                remaining_tokens = max_tokens - _estimate_tokens(md)
                _lesson_result: list[tuple[str, list[dict]] | None] = []

                def _lesson_wrapper() -> None:
                    try:
                        _lesson_result.append(
                            _rank_and_format_lessons_for_pdi(repo_path, session_id, config, remaining_tokens)
                        )
                    except Exception:
                        _lesson_result.append(None)

                lt = threading.Thread(target=_lesson_wrapper, daemon=True)
                lt.start()
                lt.join(timeout=0.1)
                if not lt.is_alive() and _lesson_result and _lesson_result[0]:
                    lesson_md, surviving_lessons = _lesson_result[0]
                    md = md + "\n\n" + lesson_md
                    _record_pdi_lesson_telemetry(repo_path, session_id, surviving_lessons)
            except Exception:
                pass

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


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def _rank_and_format_lessons_for_pdi(
    repo_path: str, session_id: str | None, config: dict, remaining_tokens: int
) -> tuple[str, list[dict]] | None:
    """Rank, trim, and format lessons for PDI. No telemetry writes.

    Returns (markdown, surviving_lessons) or None. Telemetry is recorded
    by the caller only when the result is actually used — this prevents
    phantom selections when the thread is abandoned by timeout.
    """
    if remaining_tokens < 100:
        return None

    from ..core.decision_prompt_surfacing import (
        _get_recent_commit_file_paths,
        _get_uncommitted_file_paths,
    )
    from ..core.lesson_surfacing import format_lesson_entry, rank_lessons_for_prompt
    from ..db import get_db

    file_paths = _get_uncommitted_file_paths(repo_path)
    commit_file_paths = _get_recent_commit_file_paths(repo_path, limit=5)
    if commit_file_paths:
        seen = set(file_paths)
        for p in commit_file_paths:
            if p not in seen:
                seen.add(p)
                file_paths.append(p)

    conn = get_db(repo_path)
    try:
        lessons = rank_lessons_for_prompt(conn, file_paths=file_paths, limit=3)
        if not lessons:
            return None

        entries = [format_lesson_entry(lesson, i + 1) for i, lesson in enumerate(lessons)]
        result = "## Relevant Lessons\n\n" + "\n\n".join(entries)

        if _estimate_tokens(result) > remaining_tokens:
            while entries and _estimate_tokens("## Relevant Lessons\n\n" + "\n\n".join(entries)) > remaining_tokens:
                entries.pop()
                lessons.pop()
            if not entries:
                return None
            result = "## Relevant Lessons\n\n" + "\n\n".join(entries)

        return result, lessons
    finally:
        conn.close()


def _record_pdi_lesson_telemetry(repo_path: str, session_id: str | None, lessons: list[dict]) -> None:
    """Record telemetry for PDI lessons that were actually shown to the user."""
    from ..core.context import transaction
    from ..core.telemetry import record_retrieval_event, record_retrieval_selection
    from ..db import get_db

    conn = get_db(repo_path)
    try:
        current_turn_id = None
        if session_id:
            turn_row = conn.execute(
                "SELECT id FROM turns WHERE session_id = ? ORDER BY turn_number DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if turn_row:
                current_turn_id = turn_row["id"]

        with transaction(conn):
            event = record_retrieval_event(
                conn,
                source="hook",
                search_type="lesson_surfacing",
                target="assessment",
                query="",
                result_count=len(lessons),
                latency_ms=0,
                session_id=session_id,
            )
            for idx, lesson in enumerate(lessons, start=1):
                record_retrieval_selection(
                    conn,
                    event["id"],
                    result_type="assessment",
                    result_id=lesson["id"],
                    rank=idx,
                    session_id=session_id,
                    turn_id=current_turn_id,
                )
    finally:
        conn.close()


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
