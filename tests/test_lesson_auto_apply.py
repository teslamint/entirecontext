"""Tests for auto_apply lesson extension — lesson file-overlap detection."""

from __future__ import annotations

import json

import pytest

from entirecontext.core.auto_apply import infer_applied_decisions
from entirecontext.core.checkpoint import create_checkpoint
from entirecontext.core.futures import add_feedback, create_assessment
from entirecontext.core.session import create_session
from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection
from entirecontext.core.turn import create_turn


@pytest.fixture
def lesson_auto_apply_setup(ec_db, ec_repo):
    """Seed: session with lesson surfaced + file overlap."""
    conn = ec_db
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

    # Origin session with lesson
    origin_session = create_session(conn, project_id, session_type="claude")
    origin_cp = create_checkpoint(
        conn,
        origin_session["id"],
        git_commit_hash="origin123",
        files_snapshot={"src/auth.py": "hash1", "src/middleware.py": "hash2"},
    )
    assessment = create_assessment(
        conn,
        checkpoint_id=origin_cp["id"],
        verdict="expand",
        impact_summary="Auth token improvement",
    )
    add_feedback(conn, assessment["id"], "agree", "Works well")

    # Current session: lesson surfaced, then files modified
    current_session = create_session(conn, project_id, session_type="claude")
    current_session_id = current_session["id"]

    turn = create_turn(
        conn,
        current_session_id,
        turn_number=1,
        user_message="improve auth",
        files_touched=json.dumps(["src/auth.py", "src/utils.py"]),
        tools_used=json.dumps(["Edit"]),
    )

    # Surfacing telemetry (lesson surfaced at session start)
    event = record_retrieval_event(
        conn,
        source="hook",
        search_type="lesson_surfacing",
        target="assessment",
        query="src/auth.py",
        result_count=1,
        latency_ms=0,
        session_id=current_session_id,
    )
    selection = record_retrieval_selection(
        conn,
        event["id"],
        result_type="assessment",
        result_id=assessment["id"],
        rank=1,
        session_id=current_session_id,
        turn_id=turn["id"],
    )

    return {
        "conn": conn,
        "repo_path": str(ec_repo),
        "project_id": project_id,
        "current_session_id": current_session_id,
        "assessment_id": assessment["id"],
        "selection_id": selection["id"],
        "checkpoint_id": origin_cp["id"],
    }


def test_lesson_overlap_creates_context_application(lesson_auto_apply_setup):
    """Lesson with file overlap creates context_application with source_type='assessment'."""
    ctx = lesson_auto_apply_setup
    conn = ctx["conn"]

    result = infer_applied_decisions(conn, ctx["current_session_id"], repo_path=ctx["repo_path"])
    assert result["applied_count"] >= 1

    app_row = conn.execute(
        "SELECT * FROM context_applications WHERE source_type = 'assessment' AND session_id = ?",
        (ctx["current_session_id"],),
    ).fetchone()
    assert app_row is not None
    assert app_row["application_type"] == "lesson_applied"
    assert app_row["source_id"] == ctx["assessment_id"]


def test_lesson_no_overlap_no_application(ec_db, ec_repo):
    """Lesson whose checkpoint files don't overlap session files => no application."""
    conn = ec_db
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

    origin_session = create_session(conn, project_id)
    origin_cp = create_checkpoint(
        conn,
        origin_session["id"],
        git_commit_hash="abc",
        files_snapshot={"unrelated/other.py": "hash"},
    )
    assessment = create_assessment(
        conn,
        checkpoint_id=origin_cp["id"],
        verdict="neutral",
        impact_summary="Unrelated lesson",
    )
    add_feedback(conn, assessment["id"], "agree")

    current_session = create_session(conn, project_id)
    turn = create_turn(
        conn,
        current_session["id"],
        turn_number=1,
        user_message="work",
        files_touched=json.dumps(["src/totally_different.py"]),
        tools_used=json.dumps(["Edit"]),
    )

    event = record_retrieval_event(
        conn,
        source="hook",
        search_type="lesson_surfacing",
        target="assessment",
        query="",
        result_count=1,
        latency_ms=0,
        session_id=current_session["id"],
    )
    record_retrieval_selection(
        conn,
        event["id"],
        result_type="assessment",
        result_id=assessment["id"],
        rank=1,
        session_id=current_session["id"],
        turn_id=turn["id"],
    )

    infer_applied_decisions(conn, current_session["id"], repo_path=str(ec_repo))
    apps = conn.execute(
        "SELECT * FROM context_applications WHERE session_id = ?",
        (current_session["id"],),
    ).fetchall()
    assert len(apps) == 0


def test_lesson_idempotent_no_duplicates(lesson_auto_apply_setup):
    """Running inference twice does not create duplicate context_applications."""
    ctx = lesson_auto_apply_setup
    conn = ctx["conn"]

    infer_applied_decisions(conn, ctx["current_session_id"], repo_path=ctx["repo_path"])
    infer_applied_decisions(conn, ctx["current_session_id"], repo_path=ctx["repo_path"])

    apps = conn.execute(
        "SELECT * FROM context_applications WHERE source_type = 'assessment' AND session_id = ?",
        (ctx["current_session_id"],),
    ).fetchall()
    assert len(apps) == 1


def test_lesson_and_decision_both_detected(lesson_auto_apply_setup):
    """Both decision and lesson overlap detected in same session."""
    from entirecontext.core.decisions import create_decision, link_decision_to_file

    ctx = lesson_auto_apply_setup
    conn = ctx["conn"]

    decision = create_decision(conn, title="Use JWT refresh", rationale="Better UX")
    link_decision_to_file(conn, decision["id"], "src/auth.py")

    event = record_retrieval_event(
        conn,
        source="hook",
        search_type="decision_surface",
        target="decisions",
        query="auth",
        result_count=1,
        latency_ms=5,
        session_id=ctx["current_session_id"],
    )
    turn_row = conn.execute(
        "SELECT id FROM turns WHERE session_id = ? LIMIT 1",
        (ctx["current_session_id"],),
    ).fetchone()
    record_retrieval_selection(
        conn,
        event["id"],
        result_type="decision",
        result_id=decision["id"],
        session_id=ctx["current_session_id"],
        turn_id=turn_row["id"],
    )

    infer_applied_decisions(conn, ctx["current_session_id"], repo_path=ctx["repo_path"])

    decision_apps = conn.execute(
        "SELECT * FROM context_applications WHERE source_type = 'decision' AND session_id = ?",
        (ctx["current_session_id"],),
    ).fetchall()
    lesson_apps = conn.execute(
        "SELECT * FROM context_applications WHERE source_type = 'assessment' AND session_id = ?",
        (ctx["current_session_id"],),
    ).fetchall()
    assert len(decision_apps) >= 1
    assert len(lesson_apps) >= 1
