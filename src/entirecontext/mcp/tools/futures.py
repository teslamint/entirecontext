"""Futures MCP tools."""

from __future__ import annotations

import json

from .. import runtime


async def ec_assess(assessment_id: str | None = None, retrieval_event_id: str | None = None) -> str:
    (conn, _), error = runtime.resolve_repo()
    if error:
        return error
    try:
        if assessment_id:
            from ...core.futures import get_assessment

            result = get_assessment(conn, assessment_id)
            if not result:
                row = conn.execute("SELECT * FROM assessments WHERE id LIKE ?", (f"{assessment_id}%",)).fetchone()
                result = dict(row) if row else None
        else:
            row = conn.execute("SELECT * FROM assessments ORDER BY created_at DESC LIMIT 1").fetchone()
            result = dict(row) if row else None
        if not result:
            return runtime.error_payload("No assessment found")
        selection_id = runtime.record_selection(
            conn,
            retrieval_event_id=retrieval_event_id,
            result_type="assessment",
            result_id=result["id"],
        )
        result = dict(result)
        result["selection_id"] = selection_id
        return json.dumps(result)
    finally:
        conn.close()


async def ec_assess_create(
    verdict: str | None = None,
    impact_summary: str | None = None,
    roadmap_alignment: str | None = None,
    tidy_suggestion: str | None = None,
    checkpoint_id: str | None = None,
    diff_summary: str | None = None,
    diff: str | None = None,
    roadmap: str | None = None,
    backend: str | None = None,
    model: str | None = None,
) -> str:
    (conn, repo_path), error = runtime.resolve_repo()
    if error:
        return error
    try:
        from ...core.futures import ASSESS_SYSTEM_PROMPT, create_assessment

        resolved_checkpoint_id = None
        if checkpoint_id:
            row = conn.execute(
                "SELECT id, diff_summary FROM checkpoints WHERE id = ? OR id LIKE ?",
                (checkpoint_id, f"{checkpoint_id}%"),
            ).fetchone()
            if row:
                resolved_checkpoint_id = row["id"]
                if not diff and not diff_summary:
                    diff_summary = row["diff_summary"]
                    diff = row["diff_summary"]

        if verdict:
            assessment = create_assessment(
                conn,
                checkpoint_id=resolved_checkpoint_id,
                verdict=verdict,
                impact_summary=impact_summary,
                roadmap_alignment=roadmap_alignment,
                tidy_suggestion=tidy_suggestion,
                diff_summary=diff_summary,
                model_name="mcp-agent",
            )
            return json.dumps(assessment)

        diff_text = diff or diff_summary
        if not diff_text:
            return runtime.error_payload("LLM mode requires diff text via 'diff', 'diff_summary', or 'checkpoint_id'")

        from ...core.config import load_config
        from ...core.llm import get_backend, strip_markdown_fences

        config = load_config(repo_path)
        roadmap_text = (roadmap or "")[:8000]
        if not roadmap_text and repo_path:
            from pathlib import Path

            roadmap_path = Path(repo_path) / "ROADMAP.md"
            if roadmap_path.exists():
                roadmap_text = roadmap_path.read_text(encoding="utf-8")[:8000]

        user_prompt = ""
        if roadmap_text:
            user_prompt += f"## ROADMAP\n\n{roadmap_text}\n\n"
        user_prompt += f"## DIFF\n\n```diff\n{diff_text[:8000]}\n```"

        futures_config = config.get("futures", {})
        llm_backend = backend or futures_config.get("default_backend", "openai")
        llm_model = model or futures_config.get("default_model", "gpt-4o-mini")

        try:
            llm = get_backend(llm_backend, model=llm_model)
            content = llm.complete(ASSESS_SYSTEM_PROMPT, user_prompt)
            result = json.loads(strip_markdown_fences(content))
        except Exception as exc:
            return runtime.error_payload(f"LLM analysis failed: {exc}")

        assessment = create_assessment(
            conn,
            checkpoint_id=resolved_checkpoint_id,
            verdict=result.get("verdict", "neutral"),
            impact_summary=result.get("impact_summary"),
            roadmap_alignment=result.get("roadmap_alignment"),
            tidy_suggestion=result.get("tidy_suggestion"),
            diff_summary=diff_text[:2000],
            model_name=llm_model,
        )
        return json.dumps(assessment)
    except ValueError as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


async def ec_feedback(assessment_id: str, feedback: str, reason: str | None = None) -> str:
    (conn, repo_path), error = runtime.resolve_repo()
    if error:
        return error
    try:
        from ...core.futures import add_feedback, auto_distill_lessons

        add_feedback(conn, assessment_id, feedback, feedback_reason=reason)
        distilled = auto_distill_lessons(repo_path) if repo_path else False
        return json.dumps(
            {
                "status": "ok",
                "assessment_id": assessment_id,
                "feedback": feedback,
                "auto_distilled": distilled,
            }
        )
    except ValueError as exc:
        return runtime.error_payload(str(exc))
    finally:
        conn.close()


async def ec_lessons(limit: int = 50) -> str:
    (conn, _), error = runtime.resolve_repo()
    if error:
        return error
    try:
        from ...core.futures import get_lessons

        lessons = get_lessons(conn, limit=limit)
        return json.dumps({"lessons": lessons, "count": len(lessons)})
    finally:
        conn.close()


async def ec_assess_trends(repos: list[str] | None = None, since: str | None = None) -> str:
    from ...core.cross_repo import cross_repo_assessment_trends

    trends, warnings = cross_repo_assessment_trends(
        repos=runtime.normalize_repo_names(repos),
        since=since,
        include_warnings=True,
    )
    return json.dumps({**trends, "warnings": warnings})


def register_tools(mcp, services=None) -> None:
    for tool in (ec_assess, ec_assess_create, ec_feedback, ec_lessons, ec_assess_trends):
        mcp.tool()(tool)
