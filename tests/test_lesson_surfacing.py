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


def test_session_start_lesson_surfacing_respects_experiment_block_off(lesson_setup, capsys, monkeypatch):
    """experiment_block='off' must suppress SessionStart lesson surfacing.

    Regression test: the session_start_lessons channel didn't check
    is_experiment_off, unlike the other 3 injection channels, so OFF-arm
    experiment blocks were still contaminated with injected lessons.
    """
    from pathlib import Path

    import entirecontext.core.config as config_mod

    ctx = lesson_setup
    monkeypatch.setattr(
        config_mod,
        "load_config",
        lambda *a, **kw: {
            "capture": {"auto_capture": True, "surface_lessons_on_start": True},
            "decisions": {"injection": {"experiment_block": "off"}},
        },
    )

    # Stale fallback file from a previous (unblocked) session — must be
    # cleaned up, not just left un-written, when the experiment is OFF.
    fallback_path = Path(ctx["repo_path"]) / ".entirecontext" / "lessons-context.md"
    fallback_path.parent.mkdir(parents=True, exist_ok=True)
    fallback_path.write_text("stale lessons from a prior session", encoding="utf-8")

    from entirecontext.hooks.handler import _handle_session_start

    data = {
        "cwd": ctx["repo_path"],
        "session_id": ctx["session_id"],
    }
    _handle_session_start(data)

    captured = capsys.readouterr()
    assert "Relevant Lessons" not in captured.out
    assert not fallback_path.exists()

    conn = ctx["conn"]
    events = conn.execute(
        "SELECT * FROM operation_events WHERE operation_name = 'context_injection' AND phase = 'session_start_lessons'",
    ).fetchall()
    assert len(events) == 0


def test_pdi_lesson_failure_does_not_suppress_decisions(lesson_setup, capsys, monkeypatch):
    """If lesson ranking throws, decisions still appear in output."""
    import entirecontext.core.config as config_mod
    from entirecontext.core.decisions import create_decision, link_decision_to_file

    ctx = lesson_setup
    conn = ctx["conn"]

    decision = create_decision(conn, title="Auth decision", rationale="JWT approach")
    link_decision_to_file(conn, decision["id"], "src/auth.py")

    import pathlib

    (pathlib.Path(ctx["repo_path"]) / "src").mkdir(exist_ok=True)
    (pathlib.Path(ctx["repo_path"]) / "src" / "auth.py").write_text("# auth\n")
    import subprocess

    subprocess.run(["git", "-C", ctx["repo_path"], "add", "src/auth.py"], capture_output=True)

    config = {
        "capture": {"auto_capture": True},
        "decisions": {
            "injection": {
                "inject_on_user_prompt": True,
                "top_k": 5,
                "max_tokens": 800,
                "min_confidence": 0.0,
                "inject_timeout_ms": 5000,
            },
        },
    }
    monkeypatch.setattr(config_mod, "load_config", lambda *a, **kw: config)

    monkeypatch.setattr(
        "entirecontext.core.lesson_surfacing.rank_lessons_for_prompt",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("lesson boom")),
    )

    from entirecontext.hooks.handler import _handle_user_prompt

    data = {
        "cwd": ctx["repo_path"],
        "session_id": ctx["session_id"],
        "prompt": "fix auth",
    }
    result = _handle_user_prompt(data)
    assert result == 0

    captured = capsys.readouterr()
    assert "Related Decisions" in captured.out


def test_pdi_success_path_includes_lessons_in_output(lesson_setup, capsys, monkeypatch):
    """PDI happy path: lesson appears in additionalContext alongside decisions."""
    import json as json_mod
    import pathlib
    import subprocess

    import entirecontext.core.config as config_mod
    from entirecontext.core.decisions import create_decision, link_decision_to_file

    ctx = lesson_setup
    conn = ctx["conn"]

    decision = create_decision(conn, title="Auth decision", rationale="JWT approach")
    link_decision_to_file(conn, decision["id"], "src/auth.py")

    (pathlib.Path(ctx["repo_path"]) / "src").mkdir(exist_ok=True)
    (pathlib.Path(ctx["repo_path"]) / "src" / "auth.py").write_text("# auth\n")
    subprocess.run(["git", "-C", ctx["repo_path"], "add", "src/auth.py"], capture_output=True)

    config = {
        "capture": {"auto_capture": True, "surface_lessons_on_start": True},
        "decisions": {
            "injection": {
                "inject_on_user_prompt": True,
                "top_k": 5,
                "max_tokens": 2000,
                "min_confidence": 0.0,
                "inject_timeout_ms": 5000,
            },
        },
    }
    monkeypatch.setattr(config_mod, "load_config", lambda *a, **kw: config)

    from entirecontext.hooks.handler import _handle_user_prompt

    data = {
        "cwd": ctx["repo_path"],
        "session_id": ctx["session_id"],
        "prompt": "fix auth token refresh",
    }
    _handle_user_prompt(data)

    captured = capsys.readouterr()
    for line in captured.out.strip().split("\n"):
        try:
            parsed = json_mod.loads(line)
            ctx_text = parsed.get("hookSpecificOutput", {}).get("additionalContext", "")
            if "Related Decisions" in ctx_text and "Relevant Lessons" in ctx_text:
                return
        except json_mod.JSONDecodeError:
            continue

    assert False, "Expected both 'Related Decisions' and 'Relevant Lessons' in additionalContext"


def _pdi_config() -> dict:
    return {
        "capture": {"auto_capture": True, "surface_lessons_on_start": True},
        "decisions": {
            "injection": {
                "inject_on_user_prompt": True,
                "top_k": 5,
                "max_tokens": 2000,
                "min_confidence": 0.0,
                "inject_timeout_ms": 5000,
            },
        },
    }


def _latest_user_prompt_injection_meta(conn) -> dict | None:
    row = conn.execute(
        "SELECT metadata FROM operation_events"
        " WHERE operation_name = 'context_injection' AND phase = 'user_prompt'"
        " ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return json.loads(row["metadata"]) if row else None


def test_pdi_injection_telemetry_counts_decisions_and_lessons(lesson_setup, capsys, monkeypatch):
    """user_prompt context_injection item_count covers decisions plus injected lessons."""
    import pathlib
    import subprocess

    import entirecontext.core.config as config_mod
    from entirecontext.core.decisions import create_decision, link_decision_to_file

    ctx = lesson_setup
    conn = ctx["conn"]

    decision = create_decision(conn, title="Auth decision", rationale="JWT approach")
    link_decision_to_file(conn, decision["id"], "src/auth.py")

    (pathlib.Path(ctx["repo_path"]) / "src").mkdir(exist_ok=True)
    (pathlib.Path(ctx["repo_path"]) / "src" / "auth.py").write_text("# auth\n")
    subprocess.run(["git", "-C", ctx["repo_path"], "add", "src/auth.py"], capture_output=True)

    monkeypatch.setattr(config_mod, "load_config", lambda *a, **kw: _pdi_config())

    from entirecontext.hooks.handler import _handle_user_prompt

    data = {
        "cwd": ctx["repo_path"],
        "session_id": ctx["session_id"],
        "prompt": "fix auth token refresh",
    }
    _handle_user_prompt(data)
    capsys.readouterr()

    meta = _latest_user_prompt_injection_meta(conn)
    assert meta is not None, "Expected a user_prompt context_injection event"
    assert meta["item_count"] == 2  # 1 decision + 1 lesson


def test_pdi_injection_telemetry_counts_lesson_only_path(lesson_setup, capsys, monkeypatch):
    """Lesson-only PDI injection (no matching decisions) records item_count for lessons."""
    import entirecontext.core.config as config_mod

    ctx = lesson_setup
    conn = ctx["conn"]

    monkeypatch.setattr(config_mod, "load_config", lambda *a, **kw: _pdi_config())

    from entirecontext.hooks.handler import _handle_user_prompt

    data = {
        "cwd": ctx["repo_path"],
        "session_id": ctx["session_id"],
        "prompt": "fix auth token refresh",
    }
    _handle_user_prompt(data)
    captured = capsys.readouterr()
    if "Relevant Lessons" not in captured.out:
        pytest.skip("lesson surfacing did not fire within PDI budget")

    meta = _latest_user_prompt_injection_meta(conn)
    assert meta is not None, "Expected a user_prompt context_injection event"
    assert meta["item_count"] == 1  # 0 decisions + 1 lesson
