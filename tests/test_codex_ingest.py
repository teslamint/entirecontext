"""Tests for Codex notify ingestion."""

from __future__ import annotations

import json
from pathlib import Path

from entirecontext.db import get_db
from entirecontext.hooks.codex_ingest import _save_state, ingest_codex_notify_event


def _write_codex_session_file(codex_home: Path, *, session_id: str, cwd: str) -> Path:
    session_dir = codex_home / "sessions" / "2026" / "02" / "24"
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / f"rollout-2026-02-24T00-00-00-{session_id}.jsonl"
    records = [
        {
            "timestamp": "2026-02-24T00:00:00Z",
            "type": "session_meta",
            "payload": {"id": session_id, "timestamp": "2026-02-24T00:00:00Z", "cwd": cwd},
        },
        {
            "timestamp": "2026-02-24T00:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            },
        },
        {
            "timestamp": "2026-02-24T00:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "world"}],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _enable_codex_notify(repo: Path) -> None:
    # Presence of the repo-local codex_notify.json marks the repo as
    # Codex-notify-enabled (see codex_ingest._is_repo_enabled, which gates
    # ingestion). The gate checks file existence only, so an empty state
    # dict is sufficient.
    _save_state(str(repo), {})


def test_ingest_codex_notify_event_creates_session_and_turn(ec_repo):
    codex_home = ec_repo.parent / "codex-home"
    session_id = "s-codex-1"
    _write_codex_session_file(codex_home, session_id=session_id, cwd=str(ec_repo))
    _enable_codex_notify(ec_repo)

    ingest_codex_notify_event(
        {"thread_id": session_id, "cwd": str(ec_repo), "codex_home": str(codex_home)},
        payload_text='{"thread_id":"s-codex-1"}',
    )

    conn = get_db(str(ec_repo))
    session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    turn = conn.execute("SELECT * FROM turns WHERE session_id = ?", (session_id,)).fetchone()
    content = conn.execute("SELECT * FROM turn_content WHERE turn_id = ?", (turn["id"],)).fetchone()
    conn.close()

    assert session is not None
    assert session["session_type"] == "codex"
    assert turn is not None
    assert turn["user_message"] == "hello"
    assert turn["assistant_summary"] == "world"
    assert content is not None


def test_ingest_codex_notify_event_is_idempotent(ec_repo):
    codex_home = ec_repo.parent / "codex-home"
    session_id = "s-codex-2"
    _write_codex_session_file(codex_home, session_id=session_id, cwd=str(ec_repo))
    _enable_codex_notify(ec_repo)

    payload = {"thread_id": session_id, "cwd": str(ec_repo), "codex_home": str(codex_home)}
    ingest_codex_notify_event(payload, payload_text="{}")
    ingest_codex_notify_event(payload, payload_text="{}")

    conn = get_db(str(ec_repo))
    turn_count = conn.execute("SELECT COUNT(*) FROM turns WHERE session_id = ?", (session_id,)).fetchone()[0]
    conn.close()
    assert turn_count == 1


def test_run_upstream_notify_skips_when_reentrance_guard_set(ec_repo, tmp_path, monkeypatch):
    """Re-entrance guard: if EC_CODEX_NOTIFY_RUNNING is set, upstream must not run."""
    from unittest.mock import patch

    from entirecontext.hooks.codex_ingest import _run_upstream_notify, _save_state

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    _save_state(str(ec_repo), {"upstream_notify": ["echo", "should-not-run"]})
    monkeypatch.setenv("EC_CODEX_NOTIFY_RUNNING", "1")

    with patch("entirecontext.hooks.codex_ingest.subprocess.run") as mock_run:
        _run_upstream_notify(str(ec_repo), "test")
        mock_run.assert_not_called()


def test_run_upstream_notify_sets_reentrance_guard_in_child_env(ec_repo, tmp_path, monkeypatch):
    """Upstream subprocess must inherit EC_CODEX_NOTIFY_RUNNING=1."""
    from unittest.mock import patch

    from entirecontext.hooks.codex_ingest import _run_upstream_notify, _save_state

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("EC_CODEX_NOTIFY_RUNNING", raising=False)

    _save_state(str(ec_repo), {"upstream_notify": ["echo", "hello"]})

    with patch("entirecontext.hooks.codex_ingest.subprocess.run") as mock_run:
        _run_upstream_notify(str(ec_repo), "")
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
        assert env is not None
        assert env.get("EC_CODEX_NOTIFY_RUNNING") == "1"


def test_duplicate_notify_does_not_refresh_last_activity_at(ec_repo):
    """Commit 150faab: duplicate notify events must not update last_activity_at."""
    import time

    codex_home = ec_repo.parent / "codex-home"
    session_id = "s-codex-dup"
    _write_codex_session_file(codex_home, session_id=session_id, cwd=str(ec_repo))
    _enable_codex_notify(ec_repo)

    payload = {"thread_id": session_id, "cwd": str(ec_repo), "codex_home": str(codex_home)}

    # First ingest
    ingest_codex_notify_event(payload, payload_text="{}")

    conn = get_db(str(ec_repo))
    row1 = conn.execute("SELECT last_activity_at, total_turns FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    assert row1 is not None
    assert row1["total_turns"] == 1
    first_activity = row1["last_activity_at"]

    time.sleep(0.05)

    # Second ingest — duplicate
    ingest_codex_notify_event(payload, payload_text="{}")

    conn = get_db(str(ec_repo))
    row2 = conn.execute("SELECT last_activity_at, total_turns FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    assert row2["total_turns"] == 1, "Turn count should not change on duplicate"
    assert row2["last_activity_at"] == first_activity, "last_activity_at must not change on duplicate"
