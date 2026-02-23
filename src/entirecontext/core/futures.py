"""Futures assessment operations — Tidy First philosophy."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

VALID_VERDICTS = ("expand", "narrow", "neutral")
VALID_FEEDBACKS = ("agree", "disagree")
VALID_RELATIONSHIP_TYPES = ("causes", "fixes", "contradicts")

ASSESS_SYSTEM_PROMPT = """You are a futures analyst grounded in Kent Beck's "Tidy First?" philosophy.
You evaluate code changes through the lens of software design options:
- **expand**: the change increases future options (good structure, reversibility, new capabilities)
- **narrow**: the change reduces future options (tight coupling, irreversible decisions, tech debt)
- **neutral**: the change neither significantly expands nor narrows future options

Analyze the given diff against the project roadmap and provide your assessment.
Respond with a JSON object (no markdown fences) with these fields:
- verdict: "expand" | "narrow" | "neutral"
- impact_summary: one-sentence summary of the change's impact on future options
- roadmap_alignment: how this change aligns with the roadmap
- tidy_suggestion: actionable suggestion (what to tidy, what to keep, what to reconsider)"""


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
    """Get an assessment by ID (supports prefix match)."""
    row = conn.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM assessments WHERE id LIKE ?", (f"{assessment_id}%",)).fetchone()
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

    # Use the full ID from the resolved assessment (supports prefix match)
    full_id = existing["id"]
    conn.execute(
        "UPDATE assessments SET feedback = ?, feedback_reason = ? WHERE id = ?",
        (feedback, feedback_reason, full_id),
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


def auto_distill_lessons(repo_path: str | Path) -> bool:
    """Auto-distill lessons to file if futures.auto_distill is enabled. Returns True if file was written."""
    from .config import load_config
    from ..db import get_db

    config = load_config(repo_path)
    if not config.get("futures", {}).get("auto_distill", False):
        return False

    conn = get_db(str(repo_path))
    try:
        lessons = get_lessons(conn)
    finally:
        conn.close()

    text = distill_lessons(lessons)
    output_name = config.get("futures", {}).get("lessons_output", "LESSONS.md")
    output_path = Path(repo_path) / output_name
    output_path.write_text(text, encoding="utf-8")
    return True


def _resolve_assessment_id(conn, assessment_id: str) -> str | None:
    """Resolve a full or prefix assessment ID. Returns full ID or None.

    Escapes LIKE metacharacters so '%' and '_' in the input are treated literally.
    """
    row = conn.execute("SELECT id FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
    if row is None:
        escaped = assessment_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        row = conn.execute(
            "SELECT id FROM assessments WHERE id LIKE ? ESCAPE '\\'", (f"{escaped}%",)
        ).fetchone()
    return row["id"] if row else None


def add_assessment_relationship(
    conn,
    source_id: str,
    target_id: str,
    relationship_type: str,
    note: str | None = None,
) -> dict:
    """Link two assessments with a typed relationship.

    Supports prefix IDs. Valid types: causes, fixes, contradicts.
    Raises ValueError for invalid inputs or duplicate relationships.
    """
    if relationship_type not in VALID_RELATIONSHIP_TYPES:
        raise ValueError(f"Invalid relationship_type '{relationship_type}'. Must be one of: {VALID_RELATIONSHIP_TYPES}")

    full_source_id = _resolve_assessment_id(conn, source_id)
    if full_source_id is None:
        raise ValueError(f"Source assessment '{source_id}' not found")

    full_target_id = _resolve_assessment_id(conn, target_id)
    if full_target_id is None:
        raise ValueError(f"Target assessment '{target_id}' not found")

    if full_source_id == full_target_id:
        raise ValueError("An assessment cannot relate to itself")

    existing = conn.execute(
        "SELECT id FROM assessment_relationships WHERE source_id = ? AND target_id = ? AND relationship_type = ?",
        (full_source_id, full_target_id, relationship_type),
    ).fetchone()
    if existing:
        raise ValueError(
            f"Relationship '{relationship_type}' from '{full_source_id[:8]}' to '{full_target_id[:8]}' already exists"
        )

    rel_id = str(uuid4())
    now = _now_iso()
    conn.execute(
        "INSERT INTO assessment_relationships (id, source_id, target_id, relationship_type, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (rel_id, full_source_id, full_target_id, relationship_type, note, now),
    )
    conn.commit()
    return {
        "id": rel_id,
        "source_id": full_source_id,
        "target_id": full_target_id,
        "relationship_type": relationship_type,
        "note": note,
        "created_at": now,
    }


def get_assessment_relationships(
    conn,
    assessment_id: str,
    direction: str = "both",
) -> list[dict]:
    """Get typed relationships for an assessment.

    direction: "outgoing" (source), "incoming" (target), or "both" (default).
    Supports prefix IDs. Returns enriched dicts with counterpart's impact_summary.
    """
    full_id = _resolve_assessment_id(conn, assessment_id)
    if full_id is None:
        return []

    results: list[dict] = []

    if direction in ("outgoing", "both"):
        rows = conn.execute(
            """SELECT r.*, a.impact_summary AS target_impact_summary
               FROM assessment_relationships r
               LEFT JOIN assessments a ON a.id = r.target_id
               WHERE r.source_id = ?
               ORDER BY r.created_at DESC""",
            (full_id,),
        ).fetchall()
        for row in rows:
            r = dict(row)
            r["direction"] = "outgoing"
            results.append(r)

    if direction in ("incoming", "both"):
        rows = conn.execute(
            """SELECT r.*, a.impact_summary AS source_impact_summary
               FROM assessment_relationships r
               LEFT JOIN assessments a ON a.id = r.source_id
               WHERE r.target_id = ?
               ORDER BY r.created_at DESC""",
            (full_id,),
        ).fetchall()
        for row in rows:
            r = dict(row)
            r["direction"] = "incoming"
            results.append(r)

    return results


def remove_assessment_relationship(
    conn,
    source_id: str,
    target_id: str,
    relationship_type: str,
) -> bool:
    """Remove a typed relationship between two assessments.

    Supports prefix IDs. Returns True if a row was deleted, False if not found.
    """
    full_source_id = _resolve_assessment_id(conn, source_id)
    full_target_id = _resolve_assessment_id(conn, target_id)

    if full_source_id is None or full_target_id is None:
        return False

    cursor = conn.execute(
        "DELETE FROM assessment_relationships WHERE source_id = ? AND target_id = ? AND relationship_type = ?",
        (full_source_id, full_target_id, relationship_type),
    )
    conn.commit()
    return cursor.rowcount > 0
