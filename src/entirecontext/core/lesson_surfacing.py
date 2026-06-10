"""Lesson retrieval, ranking, and formatting for surfacing pipelines."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def get_surfaceable_lessons(
    conn: sqlite3.Connection,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Retrieve assessments with feedback (lessons), ordered by recency."""
    rows = conn.execute(
        """
        SELECT a.*, c.files_snapshot, c.git_commit_hash
        FROM assessments a
        LEFT JOIN checkpoints c ON c.id = a.checkpoint_id
        WHERE a.feedback IS NOT NULL
        ORDER BY a.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_checkpoint_file_paths(
    conn: sqlite3.Connection,
    checkpoint_id: str,
) -> list[str]:
    """Extract file paths from a checkpoint's files_snapshot."""
    row = conn.execute(
        "SELECT files_snapshot FROM checkpoints WHERE id = ?",
        (checkpoint_id,),
    ).fetchone()
    if not row or not row["files_snapshot"]:
        return []
    try:
        snapshot = json.loads(row["files_snapshot"]) if isinstance(row["files_snapshot"], str) else row["files_snapshot"]
        if isinstance(snapshot, dict):
            return list(snapshot.keys())
        if isinstance(snapshot, list):
            return [str(p) for p in snapshot if p]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def rank_lessons_for_prompt(
    conn: sqlite3.Connection,
    *,
    file_paths: list[str] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Rank lessons by file overlap with working-area files, then recency.

    Returns lessons sorted by: (has_file_overlap DESC, created_at DESC).
    """
    lessons = get_surfaceable_lessons(conn, limit=limit * 3)
    if not lessons:
        return []

    file_set = set(file_paths) if file_paths else set()
    scored: list[tuple[float, dict[str, Any]]] = []

    for lesson in lessons:
        overlap_score = 0.0
        snapshot_raw = lesson.pop("files_snapshot", None)
        lesson.pop("git_commit_hash", None)

        if file_set and snapshot_raw:
            try:
                snapshot = json.loads(snapshot_raw) if isinstance(snapshot_raw, str) else snapshot_raw
                if isinstance(snapshot, dict):
                    lesson_files = set(snapshot.keys())
                elif isinstance(snapshot, list):
                    lesson_files = set(str(p) for p in snapshot if p)
                else:
                    lesson_files = set()
                overlap_count = len(file_set & lesson_files)
                if overlap_count > 0:
                    overlap_score = 10.0 + overlap_count
            except (json.JSONDecodeError, TypeError):
                pass

        scored.append((overlap_score, lesson))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:limit]]


def format_lesson_entry(lesson: dict[str, Any], rank: int) -> str:
    """Format a single lesson for Markdown output."""
    title = lesson.get("impact_summary") or "(no summary)"
    parts = [f"### {rank}. {title}"]
    if lesson.get("id"):
        parts.append(f"  ID: `{lesson['id'][:12]}`")
    verdict = lesson.get("verdict", "")
    if verdict:
        icon = {"expand": "\U0001f7e2", "narrow": "\U0001f534", "neutral": "\U0001f7e1"}.get(verdict, "")
        parts.append(f"  Verdict: {icon} {verdict}")
    if lesson.get("feedback"):
        parts.append(f"  Feedback: {lesson['feedback']}")
    if lesson.get("feedback_reason"):
        reason = lesson["feedback_reason"]
        if len(reason) > 200:
            reason = reason[:200] + "…"
        parts.append(f"  Reason: {reason}")
    if lesson.get("tidy_suggestion"):
        suggestion = lesson["tidy_suggestion"]
        if len(suggestion) > 200:
            suggestion = suggestion[:200] + "…"
        parts.append(f"\n  Suggestion: {suggestion}")
    return "\n".join(parts)
