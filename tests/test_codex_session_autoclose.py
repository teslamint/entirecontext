"""Tests for codex session auto-close (close_stale_sessions)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from entirecontext.core.project import get_project
from entirecontext.core.session import close_stale_sessions, create_session
from entirecontext.db import get_db
from entirecontext.hooks.codex_ingest import _save_state, ingest_codex_notify_event


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _two_hours_ago() -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(hours=2))


def _just_now() -> str:
    return _iso(datetime.now(timezone.utc))


def test_close_stale_sessions_closes_idle_codex(ec_repo, ec_db):
    project = get_project(str(ec_repo))
    stale_time = _two_hours_ago()

    session = create_session(ec_db, project["id"], session_type="codex", session_id="stale-codex-1")
    ec_db.execute(
        "UPDATE sessions SET last_activity_at = ? WHERE id = ?",
        (stale_time, session["id"]),
    )

    closed = close_stale_sessions(ec_db, idle_minutes=60, session_type="codex")

    assert closed == 1
    row = ec_db.execute("SELECT ended_at, last_activity_at FROM sessions WHERE id = ?", (session["id"],)).fetchone()
    assert row["ended_at"] == row["last_activity_at"]
    assert row["ended_at"] == stale_time


def test_close_stale_sessions_skips_recent_codex(ec_repo, ec_db):
    project = get_project(str(ec_repo))

    session = create_session(ec_db, project["id"], session_type="codex", session_id="recent-codex-1")
    ec_db.execute(
        "UPDATE sessions SET last_activity_at = ? WHERE id = ?",
        (_just_now(), session["id"]),
    )

    closed = close_stale_sessions(ec_db, idle_minutes=60, session_type="codex")

    assert closed == 0


def test_close_stale_sessions_skips_claude_sessions(ec_repo, ec_db):
    project = get_project(str(ec_repo))
    stale_time = _two_hours_ago()

    session = create_session(ec_db, project["id"], session_type="claude", session_id="stale-claude-1")
    ec_db.execute(
        "UPDATE sessions SET last_activity_at = ? WHERE id = ?",
        (stale_time, session["id"]),
    )

    closed = close_stale_sessions(ec_db, idle_minutes=60, session_type="codex")

    assert closed == 0


def test_close_stale_sessions_skips_already_closed(ec_repo, ec_db):
    project = get_project(str(ec_repo))
    stale_time = _two_hours_ago()

    session = create_session(ec_db, project["id"], session_type="codex", session_id="closed-codex-1")
    ec_db.execute(
        "UPDATE sessions SET last_activity_at = ?, ended_at = ? WHERE id = ?",
        (stale_time, stale_time, session["id"]),
    )

    closed = close_stale_sessions(ec_db, idle_minutes=60, session_type="codex")

    assert closed == 0


def test_close_stale_sessions_optimistic_concurrency(ec_repo, ec_db):
    project = get_project(str(ec_repo))
    stale_time = _two_hours_ago()
    fresh_time = _just_now()

    session = create_session(ec_db, project["id"], session_type="codex", session_id="concurrent-codex-1")
    ec_db.execute(
        "UPDATE sessions SET last_activity_at = ? WHERE id = ?",
        (stale_time, session["id"]),
    )

    original_execute = ec_db.execute

    def intercepting_execute(sql, params=()):
        if isinstance(sql, str) and sql.startswith("UPDATE sessions SET ended_at"):
            original_execute(
                "UPDATE sessions SET last_activity_at = ? WHERE id = ?",
                (fresh_time, session["id"]),
            )
        return original_execute(sql, params)

    ec_db.execute = intercepting_execute  # type: ignore[assignment]
    try:
        closed = close_stale_sessions(ec_db, idle_minutes=60, session_type="codex")
    finally:
        ec_db.execute = original_execute  # type: ignore[assignment]

    assert closed == 0
    row = original_execute("SELECT ended_at FROM sessions WHERE id = ?", (session["id"],)).fetchone()
    assert row["ended_at"] is None


def test_codex_ingest_auto_closes_stale_sessions(ec_repo, ec_db):
    project = get_project(str(ec_repo))
    stale_time = _two_hours_ago()

    stale_session = create_session(ec_db, project["id"], session_type="codex", session_id="stale-ingest-1")
    ec_db.execute(
        "UPDATE sessions SET last_activity_at = ? WHERE id = ?",
        (stale_time, stale_session["id"]),
    )

    ec_db.close()

    _save_state(str(ec_repo), {})

    codex_home = ec_repo.parent / "codex-home"
    session_dir = codex_home / "sessions" / "2026" / "06" / "07"
    session_dir.mkdir(parents=True, exist_ok=True)
    new_session_id = "new-codex-ingest-1"
    session_file = session_dir / f"rollout-2026-06-07T00-00-00-{new_session_id}.jsonl"
    records = [
        {
            "timestamp": "2026-06-07T00:00:00Z",
            "type": "session_meta",
            "payload": {"id": new_session_id, "timestamp": "2026-06-07T00:00:00Z", "cwd": str(ec_repo)},
        },
        {
            "timestamp": "2026-06-07T00:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "test prompt"}],
            },
        },
        {
            "timestamp": "2026-06-07T00:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "test response"}],
            },
        },
    ]
    session_file.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    ingest_codex_notify_event(
        {"thread_id": new_session_id, "cwd": str(ec_repo), "codex_home": str(codex_home)},
        payload_text=json.dumps({"thread_id": new_session_id}),
    )

    conn = get_db(str(ec_repo))
    try:
        stale_row = conn.execute(
            "SELECT ended_at, last_activity_at FROM sessions WHERE id = ?",
            (stale_session["id"],),
        ).fetchone()
        assert stale_row is not None
        assert stale_row["ended_at"] is not None
        assert stale_row["ended_at"] == stale_row["last_activity_at"]
    finally:
        conn.close()


def test_codex_ingest_reopens_closed_session_on_new_turns(ec_repo, ec_db):
    """When a closed codex session receives new turns, ended_at is cleared."""
    project = get_project(str(ec_repo))
    stale_time = _two_hours_ago()

    session_id = "reopen-codex-1"
    create_session(ec_db, project["id"], session_type="codex", session_id=session_id)
    ec_db.execute(
        "UPDATE sessions SET last_activity_at = ?, ended_at = ? WHERE id = ?",
        (stale_time, stale_time, session_id),
    )
    ec_db.close()

    _save_state(str(ec_repo), {})

    codex_home = ec_repo.parent / "codex-home-reopen"
    session_dir = codex_home / "sessions" / "2026" / "06" / "07"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_file = session_dir / f"rollout-2026-06-07T00-00-00-{session_id}.jsonl"
    records = [
        {
            "timestamp": "2026-06-07T00:00:00Z",
            "type": "session_meta",
            "payload": {"id": session_id, "timestamp": "2026-06-07T00:00:00Z", "cwd": str(ec_repo)},
        },
        {
            "timestamp": "2026-06-07T00:00:01Z",
            "type": "response_item",
            "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "new prompt"}]},
        },
        {
            "timestamp": "2026-06-07T00:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "new response"}],
            },
        },
    ]
    session_file.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    ingest_codex_notify_event(
        {"thread_id": session_id, "cwd": str(ec_repo), "codex_home": str(codex_home)},
        payload_text=json.dumps({"thread_id": session_id}),
    )

    conn = get_db(str(ec_repo))
    try:
        row = conn.execute("SELECT ended_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
        assert row["ended_at"] is None
    finally:
        conn.close()
