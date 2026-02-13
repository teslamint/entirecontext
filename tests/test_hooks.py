"""Tests for hook handlers — stdin JSON parsing, turn capture, session lifecycle."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import init_schema
from entirecontext.hooks.transcript_parser import extract_last_response, extract_transcript_content


class _NonClosingConnection:
    """Wrapper around sqlite3.Connection that ignores close() calls."""

    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _non_closing_db():
    """Create an in-memory DB whose close() is a no-op (for testing hooks that call conn.close())."""
    conn = get_memory_db()
    return _NonClosingConnection(conn)


@pytest.fixture
def db():
    conn = get_memory_db()
    init_schema(conn)
    conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', '/tmp/test')")
    conn.commit()
    yield conn
    conn.close()


class TestTranscriptParser:
    def test_extract_last_response_text(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"role": "user", "content": "hello"}),
            json.dumps({"role": "assistant", "content": "Hi there! How can I help?"}),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        result = extract_last_response(str(transcript))
        assert "Hi there" in result

    def test_extract_last_response_content_blocks(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps(
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "First part."},
                        {"type": "text", "text": "Second part."},
                    ],
                }
            ),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        result = extract_last_response(str(transcript))
        assert "First part" in result
        assert "Second part" in result

    def test_extract_last_response_truncates(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        long_text = "x" * 1000
        lines = [json.dumps({"role": "assistant", "content": long_text})]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        result = extract_last_response(str(transcript))
        assert len(result) <= 503
        assert result.endswith("...")

    def test_extract_last_response_missing_file(self):
        result = extract_last_response("/nonexistent/path.jsonl")
        assert result == ""

    def test_extract_transcript_content(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        content = '{"role":"user"}\n{"role":"assistant"}\n'
        transcript.write_text(content, encoding="utf-8")

        result = extract_transcript_content(str(transcript))
        assert result == content

    def test_extract_transcript_content_missing_file(self):
        result = extract_transcript_content("/nonexistent/path.jsonl")
        assert result == ""


class TestHandlerDispatch:
    def test_handle_hook_unknown_type(self):
        from entirecontext.hooks.handler import handle_hook

        result = handle_hook("UnknownHookType")
        assert result == 0

    def test_handle_hook_none_type(self):
        from entirecontext.hooks.handler import handle_hook

        result = handle_hook(None)
        assert result == 0


class TestSessionLifecycle:
    @patch("entirecontext.hooks.session_lifecycle._find_git_root")
    @patch("entirecontext.db.get_db")
    @patch("entirecontext.db.check_and_migrate")
    def test_on_session_start_creates_session(self, mock_migrate, mock_get_db, mock_git_root):
        conn = _non_closing_db()
        init_schema(conn)
        conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', '/tmp/test')")
        conn.commit()

        mock_git_root.return_value = "/tmp/test"
        mock_get_db.return_value = conn

        from entirecontext.hooks.session_lifecycle import on_session_start

        on_session_start(
            {
                "session_id": "test-session-123",
                "cwd": "/tmp/test",
                "source": "startup",
            }
        )

        session = conn.execute("SELECT * FROM sessions WHERE id = 'test-session-123'").fetchone()
        assert session is not None
        assert session["session_type"] == "claude"

    @patch("entirecontext.hooks.session_lifecycle._find_git_root")
    @patch("entirecontext.db.get_db")
    def test_on_session_end_sets_ended_at(self, mock_get_db, mock_git_root):
        conn = _non_closing_db()
        init_schema(conn)
        conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', '/tmp/test')")
        conn.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at) "
            "VALUES ('s1', 'p1', 'claude', '2025-01-01', '2025-01-01')"
        )
        conn.commit()

        mock_git_root.return_value = "/tmp/test"
        mock_get_db.return_value = conn

        from entirecontext.hooks.session_lifecycle import on_session_end

        on_session_end({"session_id": "s1", "cwd": "/tmp/test"})

        session = conn.execute("SELECT * FROM sessions WHERE id = 's1'").fetchone()
        assert session["ended_at"] is not None


class TestTurnCapture:
    @patch("entirecontext.hooks.turn_capture._find_git_root")
    @patch("entirecontext.db.get_db")
    def test_on_user_prompt_creates_turn(self, mock_get_db, mock_git_root):
        conn = _non_closing_db()
        init_schema(conn)
        conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', '/tmp/test')")
        conn.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at) "
            "VALUES ('s1', 'p1', 'claude', '2025-01-01', '2025-01-01')"
        )
        conn.commit()

        mock_git_root.return_value = "/tmp/test"
        mock_get_db.return_value = conn

        from entirecontext.hooks.turn_capture import on_user_prompt

        on_user_prompt(
            {
                "session_id": "s1",
                "cwd": "/tmp/test",
                "prompt": "Fix the login bug",
            }
        )

        turn = conn.execute("SELECT * FROM turns WHERE session_id = 's1'").fetchone()
        assert turn is not None
        assert turn["user_message"] == "Fix the login bug"
        assert turn["turn_status"] == "in_progress"

    @patch("entirecontext.hooks.turn_capture._find_git_root")
    @patch("entirecontext.db.get_db")
    def test_on_tool_use_tracks_tools(self, mock_get_db, mock_git_root):
        conn = _non_closing_db()
        init_schema(conn)
        conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', '/tmp/test')")
        conn.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at) "
            "VALUES ('s1', 'p1', 'claude', '2025-01-01', '2025-01-01')"
        )
        conn.execute(
            "INSERT INTO turns (id, session_id, turn_number, content_hash, timestamp, turn_status) "
            "VALUES ('t1', 's1', 1, 'hash', '2025-01-01', 'in_progress')"
        )
        conn.commit()

        mock_git_root.return_value = "/tmp/test"
        mock_get_db.return_value = conn

        from entirecontext.hooks.turn_capture import on_tool_use

        on_tool_use(
            {
                "session_id": "s1",
                "cwd": "/tmp/test",
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/main.py"},
                "tool_response": "ok",
            }
        )

        turn = conn.execute("SELECT * FROM turns WHERE id = 't1'").fetchone()
        tools = json.loads(turn["tools_used"])
        files = json.loads(turn["files_touched"])
        assert "Edit" in tools
        assert "src/main.py" in files
