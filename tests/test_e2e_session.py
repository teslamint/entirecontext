"""E2E tests for full session lifecycle via hook handlers."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.search import fts_search
from entirecontext.core.session import get_session
from entirecontext.core.turn import list_turns
from entirecontext.db import get_db
from entirecontext.hooks.session_lifecycle import on_session_end, on_session_start
from entirecontext.hooks.turn_capture import on_stop, on_tool_use, on_user_prompt

runner = CliRunner()


class TestSessionLifecycle:
    def test_full_flow(self, ec_repo, transcript_file):
        cwd = str(ec_repo)
        sid = "e2e-session-001"

        # Session start
        on_session_start({"session_id": sid, "cwd": cwd, "source": "startup"})
        conn = get_db(cwd)
        assert get_session(conn, sid) is not None
        assert get_session(conn, sid)["ended_at"] is None
        conn.close()

        # Turn 1: prompt + tool use
        on_user_prompt({"session_id": sid, "cwd": cwd, "prompt": "Fix auth bug"})
        on_tool_use(
            {
                "session_id": sid,
                "cwd": cwd,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/auth.py"},
            }
        )
        conn = get_db(cwd)
        turns = list_turns(conn, sid)
        assert len(turns) == 1
        assert turns[0]["turn_status"] == "in_progress"
        assert turns[0]["user_message"] == "Fix auth bug"
        assert json.loads(turns[0]["tools_used"]) == ["Edit"]
        assert json.loads(turns[0]["files_touched"]) == ["src/auth.py"]
        conn.close()

        # Turn 1: stop
        t1_path = transcript_file(
            [
                {"role": "user", "content": "Fix auth bug"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I fixed the authentication bug in src/auth.py"},
                    ],
                },
            ],
            name="t1.jsonl",
        )
        on_stop({"session_id": sid, "cwd": cwd, "transcript_path": t1_path})
        conn = get_db(cwd)
        turns = list_turns(conn, sid)
        assert turns[0]["turn_status"] == "completed"
        assert "authentication bug" in turns[0]["assistant_summary"]
        conn.close()

        # Turn 2
        on_user_prompt({"session_id": sid, "cwd": cwd, "prompt": "Add tests"})
        t2_path = transcript_file(
            [
                {"role": "user", "content": "Add tests"},
                {"role": "assistant", "content": "I added comprehensive tests for the auth module"},
            ],
            name="t2.jsonl",
        )
        on_stop({"session_id": sid, "cwd": cwd, "transcript_path": t2_path})

        # Session end
        on_session_end({"session_id": sid, "cwd": cwd})

        # Verify final state
        conn = get_db(cwd)

        session = get_session(conn, sid)
        assert session["ended_at"] is not None

        turns = list_turns(conn, sid)
        assert len(turns) == 2
        assert all(t["turn_status"] == "completed" for t in turns)

        content_rows = conn.execute("SELECT * FROM turn_content").fetchall()
        assert len(content_rows) == 2
        for row in content_rows:
            full_path = ec_repo / ".entirecontext" / row["content_path"]
            assert full_path.exists()

        for t in turns:
            assert t["content_hash"]

        conn.close()

    def test_fts_populated_by_triggers(self, ec_repo, transcript_file):
        cwd = str(ec_repo)
        sid = "e2e-fts-session"

        on_session_start({"session_id": sid, "cwd": cwd, "source": "startup"})

        on_user_prompt({"session_id": sid, "cwd": cwd, "prompt": "Fix auth bug"})
        t1 = transcript_file(
            [
                {"role": "user", "content": "Fix auth bug"},
                {"role": "assistant", "content": "Fixed the authentication issue"},
            ],
            name="fts_t1.jsonl",
        )
        on_stop({"session_id": sid, "cwd": cwd, "transcript_path": t1})

        on_user_prompt({"session_id": sid, "cwd": cwd, "prompt": "Add database migration"})
        t2 = transcript_file(
            [
                {"role": "user", "content": "Add database migration"},
                {"role": "assistant", "content": "Added migration for user table"},
            ],
            name="fts_t2.jsonl",
        )
        on_stop({"session_id": sid, "cwd": cwd, "transcript_path": t2})

        conn = get_db(cwd)
        auth_results = fts_search(conn, "auth", target="turn")
        assert len(auth_results) >= 1
        assert any("auth" in (r.get("user_message") or "").lower() for r in auth_results)

        migration_results = fts_search(conn, "migration", target="turn")
        assert len(migration_results) >= 1
        conn.close()

    def test_session_list_cli(self, ec_repo, transcript_file, monkeypatch):
        monkeypatch.chdir(ec_repo)
        cwd = str(ec_repo)
        sid = "e2e-cli-session"

        on_session_start({"session_id": sid, "cwd": cwd, "source": "startup"})
        on_user_prompt({"session_id": sid, "cwd": cwd, "prompt": "Test prompt"})
        t1 = transcript_file(
            [
                {"role": "user", "content": "Test prompt"},
                {"role": "assistant", "content": "Done"},
            ],
            name="cli_t1.jsonl",
        )
        on_stop({"session_id": sid, "cwd": cwd, "transcript_path": t1})

        result = runner.invoke(app, ["session", "list"])
        assert result.exit_code == 0
        assert sid[:12] in result.output

    def test_session_show_cli(self, ec_repo, transcript_file, monkeypatch):
        monkeypatch.chdir(ec_repo)
        cwd = str(ec_repo)
        sid = "e2e-show-session"

        on_session_start({"session_id": sid, "cwd": cwd, "source": "startup"})
        on_user_prompt({"session_id": sid, "cwd": cwd, "prompt": "First prompt"})
        t1 = transcript_file(
            [
                {"role": "user", "content": "First prompt"},
                {"role": "assistant", "content": "First response"},
            ],
            name="show_t1.jsonl",
        )
        on_stop({"session_id": sid, "cwd": cwd, "transcript_path": t1})

        on_user_prompt({"session_id": sid, "cwd": cwd, "prompt": "Second prompt"})
        t2 = transcript_file(
            [
                {"role": "user", "content": "Second prompt"},
                {"role": "assistant", "content": "Second response"},
            ],
            name="show_t2.jsonl",
        )
        on_stop({"session_id": sid, "cwd": cwd, "transcript_path": t2})

        result = runner.invoke(app, ["session", "show", sid])
        assert result.exit_code == 0
        assert "First prompt" in result.output
        assert "Second prompt" in result.output
