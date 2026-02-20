"""Futures assessment operations — Tidy First philosophy."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

VALID_VERDICTS = ("expand", "narrow", "neutral")
VALID_FEEDBACKS = ("agree", "disagree")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_assessment(
    conn,
    checkpoint_id: str | None = None,
    verdict: str = "neutral",
    impact_summary: str | None = None,
    roadmap_alignment: str | None = None,
    tidy_suggestion: str | None = None,
    diff_summary: str | None = None,
    model_name: str | None = None,
) -> dict:
    """Create a new futures assessment."""
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"Invalid verdict '{verdict}'. Must be one of: {VALID_VERDICTS}")

    assessment_id = str(uuid4())
    now = _now_iso()

    conn.execute(
        """INSERT INTO assessments (id, checkpoint_id, verdict, impact_summary, roadmap_alignment, tidy_suggestion, diff_summary, model_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            assessment_id,
            checkpoint_id,
            verdict,
            impact_summary,
            roadmap_alignment,
            tidy_suggestion,
            diff_summary,
            model_name,
            now,
        ),
    )
    conn.commit()
    return {
        "id": assessment_id,
        "checkpoint_id": checkpoint_id,
        "verdict": verdict,
        "impact_summary": impact_summary,
        "roadmap_alignment": roadmap_alignment,
        "tidy_suggestion": tidy_suggestion,
        "diff_summary": diff_summary,
        "model_name": model_name,
        "created_at": now,
    }


def get_assessment(conn, assessment_id: str) -> dict | None:
    """Get an assessment by ID."""
    row = conn.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
    return dict(row) if row else None


def list_assessments(
    conn,
    verdict: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List assessments with optional verdict filter."""
    query = "SELECT * FROM assessments"
    params: list[Any] = []

    if verdict:
        if verdict not in VALID_VERDICTS:
            raise ValueError(f"Invalid verdict '{verdict}'. Must be one of: {VALID_VERDICTS}")
        query += " WHERE verdict = ?"
        params.append(verdict)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def add_feedback(conn, assessment_id: str, feedback: str, feedback_reason: str | None = None) -> None:
    """Add feedback to an assessment."""
    if feedback not in VALID_FEEDBACKS:
        raise ValueError(f"Invalid feedback '{feedback}'. Must be one of: {VALID_FEEDBACKS}")

    existing = get_assessment(conn, assessment_id)
    if existing is None:
        raise ValueError(f"Assessment '{assessment_id}' not found")

    conn.execute(
        "UPDATE assessments SET feedback = ?, feedback_reason = ? WHERE id = ?",
        (feedback, feedback_reason, assessment_id),
    )
    conn.commit()


def get_lessons(conn, limit: int = 50) -> list[dict]:
    """Get assessments that have feedback — these are lessons learned."""
    rows = conn.execute(
        "SELECT * FROM assessments WHERE feedback IS NOT NULL ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def distill_lessons(assessments: list[dict]) -> str:
    """Format assessment+feedback list into LESSONS.md text. No LLM needed."""
    if not assessments:
        return "# Lessons Learned\n\nNo lessons recorded yet.\n"

    lines = ["# Lessons Learned", "", f"_Generated from {len(assessments)} assessed changes._", ""]

    by_verdict: dict[str, list[dict]] = {"expand": [], "narrow": [], "neutral": []}
    for a in assessments:
        by_verdict.setdefault(a["verdict"], []).append(a)

    verdict_labels = {
        "expand": "\U0001f7e2 Expand (increases future options)",
        "narrow": "\U0001f534 Narrow (reduces future options)",
        "neutral": "\U0001f7e1 Neutral",
    }

    for verdict, label in verdict_labels.items():
        items = by_verdict.get(verdict, [])
        if not items:
            continue
        lines.append(f"## {label}")
        lines.append("")
        for a in items:
            feedback_icon = "\u2705" if a.get("feedback") == "agree" else "\u274c"
            lines.append(f"### {feedback_icon} {a.get('impact_summary', 'No summary')}")
            lines.append("")
            if a.get("roadmap_alignment"):
                lines.append(f"**Roadmap alignment:** {a['roadmap_alignment']}")
                lines.append("")
            if a.get("tidy_suggestion"):
                lines.append(f"**Suggestion:** {a['tidy_suggestion']}")
                lines.append("")
            if a.get("feedback_reason"):
                lines.append(f"**Feedback:** {a['feedback']} — {a['feedback_reason']}")
                lines.append("")
            lines.append(f"_Assessment: {a['id'][:8]} | {a.get('created_at', '')}_ ")
            lines.append("")

    return "\n".join(lines) + "\n"
