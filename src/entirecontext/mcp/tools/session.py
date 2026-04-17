"""Session and context MCP tools."""

from __future__ import annotations

import json

from .. import runtime


async def ec_session_context(
    session_id: str | None = None,
    repos: str | list[str] | None = None,
    retrieval_event_id: str | None = None,
) -> str:
    repo_names = runtime.normalize_repo_names(repos)
    if repos is not None and repos != "":
        from ...core.cross_repo import cross_repo_session_detail

        if not session_id:
            return runtime.error_payload("session_id is required for cross-repo session context")
        result, warnings = cross_repo_session_detail(session_id, repos=repo_names, include_warnings=True)
        if not result:
            return runtime.error_payload(f"Session not found: {session_id}", warnings=warnings)
        turns = result.get("turns", [])
        return json.dumps(
            {
                "session_id": result.get("id", ""),
                "session_title": result.get("session_title", ""),
                "session_summary": result.get("session_summary", ""),
                "started_at": result.get("started_at", ""),
                "ended_at": result.get("ended_at"),
                "total_turns": result.get("total_turns", 0),
                "repo_name": result.get("repo_name", ""),
                "repo_path": result.get("repo_path", ""),
                "recent_turns": [
                    {
                        "id": turn.get("id", ""),
                        "turn_number": turn.get("turn_number", 0),
                        "user_message": turn.get("user_message", ""),
                        "assistant_summary": turn.get("assistant_summary", ""),
                        "timestamp": turn.get("timestamp", ""),
                    }
                    for turn in turns
                ],
                "warnings": warnings,
                "telemetry_skipped": "cross_repo",
            }
        )

    (conn, repo_path), error = runtime.resolve_repo()
    if error:
        return error

    try:
        if not session_id:
            session_id = runtime.detect_current_session(conn)
        if not session_id:
            return runtime.error_payload("No active session found")
        session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not session:
            return runtime.error_payload(f"Session not found: {session_id}")
        turns = conn.execute(
            """
            SELECT id, turn_number, user_message, assistant_summary, timestamp
            FROM turns WHERE session_id = ? ORDER BY turn_number DESC LIMIT 10
            """,
            (session_id,),
        ).fetchall()
        from ...core.config import load_config
        from ...core.content_filter import redact_for_query

        config = load_config(repo_path)
        selection_id = runtime.record_selection(
            conn,
            retrieval_event_id=retrieval_event_id,
            result_type="session",
            result_id=session["id"],
        )
        return json.dumps(
            {
                "session_id": session["id"],
                "session_title": session["session_title"],
                "session_summary": session["session_summary"],
                "started_at": session["started_at"],
                "ended_at": session["ended_at"],
                "total_turns": session["total_turns"],
                "recent_turns": [
                    {
                        "id": turn["id"],
                        "turn_number": turn["turn_number"],
                        "user_message": redact_for_query(turn["user_message"] or "", config),
                        "assistant_summary": redact_for_query(turn["assistant_summary"] or "", config),
                        "timestamp": turn["timestamp"],
                    }
                    for turn in turns
                ],
                "selection_id": selection_id,
            }
        )
    finally:
        conn.close()


async def ec_attribution(
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    repos: str | list[str] | None = None,
) -> str:
    repo_names = runtime.normalize_repo_names(repos)
    if repos is not None and repos != "":
        from ...core.cross_repo import cross_repo_attribution

        results, warnings = cross_repo_attribution(
            file_path,
            start_line,
            end_line,
            repos=repo_names,
            include_warnings=True,
        )
        attributions = [
            {
                "start_line": result.get("start_line"),
                "end_line": result.get("end_line"),
                "type": result.get("attribution_type", ""),
                "agent_name": result.get("agent_name"),
                "session_id": result.get("session_id", ""),
                "turn_id": result.get("turn_id", ""),
                "confidence": result.get("confidence"),
                "repo_name": result.get("repo_name", ""),
                "repo_path": result.get("repo_path", ""),
            }
            for result in results
        ]
        return json.dumps({"file_path": file_path, "attributions": attributions, "warnings": warnings})

    (conn, _), error = runtime.resolve_repo()
    if error:
        return error

    try:
        query = "SELECT * FROM attributions WHERE file_path = ?"
        params: list = [file_path]
        if start_line is not None:
            query += " AND end_line >= ?"
            params.append(start_line)
        if end_line is not None:
            query += " AND start_line <= ?"
            params.append(end_line)
        query += " ORDER BY start_line"
        rows = conn.execute(query, params).fetchall()
        attributions = []
        for row in rows:
            agent_name = None
            if row["agent_id"]:
                agent = conn.execute("SELECT name, agent_type FROM agents WHERE id = ?", (row["agent_id"],)).fetchone()
                if agent:
                    agent_name = agent["name"] or agent["agent_type"]
            attributions.append(
                {
                    "start_line": row["start_line"],
                    "end_line": row["end_line"],
                    "type": row["attribution_type"],
                    "agent_name": agent_name,
                    "session_id": row["session_id"],
                    "turn_id": row["turn_id"],
                    "confidence": row["confidence"],
                }
            )
        return json.dumps({"file_path": file_path, "attributions": attributions})
    finally:
        conn.close()


async def ec_turn_content(
    turn_id: str,
    repos: str | list[str] | None = None,
    retrieval_event_id: str | None = None,
) -> str:
    repo_names = runtime.normalize_repo_names(repos)
    if repos is not None and repos != "":
        from ...core.cross_repo import cross_repo_turn_content

        result, warnings = cross_repo_turn_content(turn_id, repos=repo_names, include_warnings=True)
        if not result:
            return runtime.error_payload(f"Turn not found: {turn_id}", warnings=warnings)
        return json.dumps(
            {
                "turn_id": result.get("id", ""),
                "session_id": result.get("session_id", ""),
                "turn_number": result.get("turn_number", 0),
                "user_message": result.get("user_message", ""),
                "assistant_summary": result.get("assistant_summary", ""),
                "timestamp": result.get("timestamp", ""),
                "content": result.get("content"),
                "content_path": result.get("content_path"),
                "repo_name": result.get("repo_name", ""),
                "repo_path": result.get("repo_path", ""),
                "warnings": warnings,
                "telemetry_skipped": "cross_repo",
            }
        )

    (conn, repo_path), error = runtime.resolve_repo()
    if error:
        return error

    try:
        from ...core.turn import get_turn

        turn = get_turn(conn, turn_id)
        if not turn:
            return runtime.error_payload(f"Turn not found: {turn_id}")
        content_row = conn.execute("SELECT content_path FROM turn_content WHERE turn_id = ?", (turn_id,)).fetchone()
        content = None
        content_path = None
        if content_row:
            content_path = content_row["content_path"]
            from ...core.cross_repo import resolve_content_path

            full_path = resolve_content_path(str(repo_path), content_path)
            if full_path.exists():
                content = full_path.read_text(encoding="utf-8")
        from ...core.config import load_config
        from ...core.content_filter import redact_for_query

        config = load_config(repo_path)
        selection_id = runtime.record_selection(
            conn,
            retrieval_event_id=retrieval_event_id,
            result_type="turn",
            result_id=turn["id"],
        )
        return json.dumps(
            {
                "turn_id": turn["id"],
                "session_id": turn["session_id"],
                "turn_number": turn.get("turn_number", 0),
                "user_message": redact_for_query(turn.get("user_message") or "", config),
                "assistant_summary": redact_for_query(turn.get("assistant_summary") or "", config),
                "timestamp": turn.get("timestamp", ""),
                "content": redact_for_query(content, config) if content else content,
                "content_path": content_path,
                "selection_id": selection_id,
            }
        )
    finally:
        conn.close()


async def ec_context_apply(
    application_type: str,
    selection_id: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    note: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> str:
    (conn, _), error = runtime.resolve_repo()
    if error:
        return error

    try:
        from ...core.telemetry import detect_current_context, record_context_application

        current_session_id, current_turn_id = detect_current_context(conn)
        application = record_context_application(
            conn,
            application_type=application_type,
            selection_id=selection_id,
            source_type=source_type,
            source_id=source_id,
            note=note,
            session_id=session_id or current_session_id,
            turn_id=turn_id or current_turn_id,
        )

        if application.get("source_type") == "decision" and application_type in ("decision_change", "code_reuse"):
            try:
                from ...core.decisions import record_decision_outcome

                app_session = application.get("session_id")
                app_turn = application.get("turn_id")
                if app_session and not app_turn:
                    app_session = None
                record_decision_outcome(
                    conn,
                    application["source_id"],
                    outcome_type="accepted",
                    retrieval_selection_id=application.get("retrieval_selection_id"),
                    session_id=app_session,
                    turn_id=app_turn,
                    note="auto: context_apply",
                )
            except Exception:
                pass

        return json.dumps(application)
    except ValueError as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


def register_tools(mcp, services=None) -> None:
    for tool in (ec_session_context, ec_attribution, ec_turn_content, ec_context_apply):
        mcp.tool()(tool)
