"""E2E tests for multi-session scenarios."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.search import regex_search
from entirecontext.core.session import get_current_session, list_sessions
from entirecontext.core.turn import list_turns
from entirecontext.db import get_db
from entirecontext.hooks.session_lifecycle import on_session_end, on_session_start
from entirecontext.hooks.turn_capture import on_stop, on_user_prompt

runner = CliRunner()


@pytest.fixture
def multi_session_repo(ec_repo, transcript_file):
    """EC repo with two sessions: s1 (ended, 2 turns) and s2 (active, 1 turn)."""
    cwd = str(ec_repo)

    on_session_start({"session_id": "s1", "cwd": cwd, "source": "startup"})
    on_user_prompt({"session_id": "s1", "cwd": cwd, "prompt": "Fix auth bug"})
    t1 = transcript_file(
        [
            {"role": "user", "content": "Fix auth bug"},
            {"role": "assistant", "content": "Fixed auth"},
        ],
        name="ms_t1.jsonl",
    )
    on_stop({"session_id": "s1", "cwd": cwd, "transcript_path": t1})

    on_user_prompt({"session_id": "s1", "cwd": cwd, "prompt": "Add logging"})
    t2 = transcript_file(
        [
            {"role": "user", "content": "Add logging"},
            {"role": "assistant", "content": "Added logging"},
        ],
        name="ms_t2.jsonl",
    )
    on_stop({"session_id": "s1", "cwd": cwd, "transcript_path": t2})
    on_session_end({"session_id": "s1", "cwd": cwd})

    on_session_start({"session_id": "s2", "cwd": cwd, "source": "startup"})
    on_user_prompt({"session_id": "s2", "cwd": cwd, "prompt": "Refactor auth module"})
    t3 = transcript_file(
        [
            {"role": "user", "content": "Refactor auth module"},
            {"role": "assistant", "content": "Refactored auth"},
        ],
        name="ms_t3.jsonl",
    )
    on_stop({"session_id": "s2", "cwd": cwd, "transcript_path": t3})

    return ec_repo


class TestMultiSession:
    def test_current_session_is_latest(self, multi_session_repo):
        conn = get_db(str(multi_session_repo))
        current = get_current_session(conn)
        conn.close()
        assert current is not None
        assert current["id"] == "s2"

    def test_search_spans_sessions(self, multi_session_repo):
        conn = get_db(str(multi_session_repo))
        results = regex_search(conn, "auth")
        conn.close()
        session_ids = {r["session_id"] for r in results}
        assert "s1" in session_ids
        assert "s2" in session_ids

    def test_list_sessions_shows_both(self, multi_session_repo):
        conn = get_db(str(multi_session_repo))
        project = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
        sessions = list_sessions(conn, project_id=project["id"])
        conn.close()
        assert len(sessions) == 2
        by_id = {s["id"]: s for s in sessions}
        assert by_id["s1"]["ended_at"] is not None
        assert by_id["s2"]["ended_at"] is None

    def test_turn_counts_correct(self, multi_session_repo):
        conn = get_db(str(multi_session_repo))
        assert len(list_turns(conn, "s1")) == 2
        assert len(list_turns(conn, "s2")) == 1
        conn.close()

    def test_session_list_cli(self, multi_session_repo, monkeypatch):
        monkeypatch.chdir(multi_session_repo)
        result = runner.invoke(app, ["session", "list"])
        assert result.exit_code == 0
        assert "s1" in result.output
        assert "s2" in result.output

    def test_session_current_cli(self, multi_session_repo, monkeypatch):
        monkeypatch.chdir(multi_session_repo)
        result = runner.invoke(app, ["session", "current"])
        assert result.exit_code == 0
        assert "s2" in result.output
