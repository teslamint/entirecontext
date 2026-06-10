"""Tests for core/lesson_surfacing.py — lesson retrieval, ranking, formatting."""

from __future__ import annotations

import json

import pytest

from entirecontext.core.checkpoint import create_checkpoint
from entirecontext.core.futures import add_feedback, create_assessment
from entirecontext.core.session import create_session
from entirecontext.core.turn import create_turn


@pytest.fixture
def lesson_setup(ec_db, ec_repo):
    """Seed: 1 session, 1 checkpoint with files_snapshot, 1 assessment with feedback."""
    conn = ec_db
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

    session = create_session(conn, project_id, session_type="claude")
    session_id = session["id"]

    create_turn(
        conn,
        session_id,
        turn_number=1,
        user_message="implement auth",
        files_touched=json.dumps(["src/auth.py", "src/middleware.py"]),
        tools_used=json.dumps(["Edit"]),
    )

    checkpoint = create_checkpoint(
        conn,
        session_id,
        git_commit_hash="abc123",
        files_snapshot={"src/auth.py": "hash1", "src/middleware.py": "hash2", "README.md": "hash3"},
    )

    assessment = create_assessment(
        conn,
        checkpoint_id=checkpoint["id"],
        verdict="expand",
        impact_summary="Added token refresh reduces session drops",
        roadmap_alignment="Aligned with auth hardening",
        tidy_suggestion="Consider extracting token logic to separate module",
    )
    add_feedback(conn, assessment["id"], "agree", "Confirmed token refresh works in prod")

    return {
        "conn": conn,
        "repo_path": str(ec_repo),
        "project_id": project_id,
        "session_id": session_id,
        "checkpoint_id": checkpoint["id"],
        "assessment_id": assessment["id"],
    }


def test_get_surfaceable_lessons_returns_lessons_with_feedback(lesson_setup):
    from entirecontext.core.lesson_surfacing import get_surfaceable_lessons

    ctx = lesson_setup
    lessons = get_surfaceable_lessons(ctx["conn"], limit=10)
    assert len(lessons) == 1
    assert lessons[0]["id"] == ctx["assessment_id"]
    assert lessons[0]["feedback"] is not None


def test_get_surfaceable_lessons_excludes_no_feedback(lesson_setup):
    from entirecontext.core.lesson_surfacing import get_surfaceable_lessons

    ctx = lesson_setup
    create_assessment(
        ctx["conn"],
        checkpoint_id=ctx["checkpoint_id"],
        verdict="neutral",
        impact_summary="No feedback assessment",
    )
    lessons = get_surfaceable_lessons(ctx["conn"], limit=10)
    assert len(lessons) == 1


def test_get_surfaceable_lessons_respects_limit(lesson_setup):
    from entirecontext.core.lesson_surfacing import get_surfaceable_lessons

    ctx = lesson_setup
    for i in range(5):
        a = create_assessment(
            ctx["conn"],
            checkpoint_id=ctx["checkpoint_id"],
            verdict="expand",
            impact_summary=f"Lesson {i}",
        )
        add_feedback(ctx["conn"], a["id"], "agree")

    lessons = get_surfaceable_lessons(ctx["conn"], limit=3)
    assert len(lessons) == 3


def test_get_checkpoint_file_paths_returns_snapshot_keys(lesson_setup):
    from entirecontext.core.lesson_surfacing import get_checkpoint_file_paths

    ctx = lesson_setup
    paths = get_checkpoint_file_paths(ctx["conn"], ctx["checkpoint_id"])
    assert set(paths) == {"src/auth.py", "src/middleware.py", "README.md"}


def test_get_checkpoint_file_paths_null_snapshot(ec_db, ec_repo):
    from entirecontext.core.lesson_surfacing import get_checkpoint_file_paths

    conn = ec_db
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
    session = create_session(conn, project_id)
    cp = create_checkpoint(conn, session["id"], git_commit_hash="def456", files_snapshot=None)
    paths = get_checkpoint_file_paths(conn, cp["id"])
    assert paths == []


def test_rank_lessons_by_file_overlap(lesson_setup):
    from entirecontext.core.lesson_surfacing import rank_lessons_for_prompt

    ctx = lesson_setup
    session2 = create_session(ctx["conn"], ctx["project_id"])
    cp2 = create_checkpoint(
        ctx["conn"],
        session2["id"],
        git_commit_hash="xyz789",
        files_snapshot={"unrelated/file.py": "hash4"},
    )
    a2 = create_assessment(
        ctx["conn"],
        checkpoint_id=cp2["id"],
        verdict="narrow",
        impact_summary="Unrelated lesson",
    )
    add_feedback(ctx["conn"], a2["id"], "disagree", "Not relevant")

    ranked = rank_lessons_for_prompt(
        ctx["conn"],
        file_paths=["src/auth.py"],
        limit=5,
    )
    assert len(ranked) == 2
    assert ranked[0]["id"] == ctx["assessment_id"]


def test_format_lesson_entry_output(lesson_setup):
    from entirecontext.core.lesson_surfacing import format_lesson_entry, get_surfaceable_lessons

    ctx = lesson_setup
    lessons = get_surfaceable_lessons(ctx["conn"], limit=1)
    output = format_lesson_entry(lessons[0], rank=1)
    assert "### 1." in output
    assert "token refresh" in output.lower()
    assert lessons[0]["id"][:12] in output


def test_session_start_surfaces_lessons_to_stdout(lesson_setup, capsys, monkeypatch):
    """SessionStart dispatches lesson surfacing and prints to stdout."""
    import entirecontext.core.config as config_mod

    ctx = lesson_setup
    monkeypatch.setattr(
        config_mod,
        "load_config",
        lambda *a, **kw: {
            "capture": {"auto_capture": True, "surface_lessons_on_start": True},
            "decisions": {},
        },
    )

    from entirecontext.hooks.handler import _handle_session_start

    data = {
        "cwd": ctx["repo_path"],
        "session_id": ctx["session_id"],
    }
    _handle_session_start(data)

    captured = capsys.readouterr()
    assert "Lessons" in captured.out or "lesson" in captured.out.lower()


def test_session_start_lesson_surfacing_config_off(lesson_setup, capsys, monkeypatch):
    """surface_lessons_on_start=False skips lesson surfacing."""
    import entirecontext.core.config as config_mod

    ctx = lesson_setup
    monkeypatch.setattr(
        config_mod,
        "load_config",
        lambda *a, **kw: {
            "capture": {"auto_capture": True, "surface_lessons_on_start": False},
            "decisions": {},
        },
    )

    from entirecontext.hooks.handler import _handle_session_start

    data = {
        "cwd": ctx["repo_path"],
        "session_id": ctx["session_id"],
    }
    _handle_session_start(data)

    captured = capsys.readouterr()
    assert "Relevant Lessons" not in captured.out


def test_session_start_lesson_surfacing_records_telemetry(lesson_setup, monkeypatch):
    """Lesson surfacing records retrieval_event and retrieval_selection."""
    import entirecontext.core.config as config_mod

    ctx = lesson_setup
    monkeypatch.setattr(
        config_mod,
        "load_config",
        lambda *a, **kw: {
            "capture": {"auto_capture": True, "surface_lessons_on_start": True},
            "decisions": {},
        },
    )

    from entirecontext.hooks.handler import _handle_session_start

    data = {
        "cwd": ctx["repo_path"],
        "session_id": ctx["session_id"],
    }
    _handle_session_start(data)

    conn = ctx["conn"]
    events = conn.execute(
        "SELECT * FROM retrieval_events WHERE search_type = 'lesson_surfacing'",
    ).fetchall()
    assert len(events) >= 1

    selections = conn.execute(
        "SELECT * FROM retrieval_selections WHERE result_type = 'assessment'",
    ).fetchall()
    assert len(selections) >= 1
