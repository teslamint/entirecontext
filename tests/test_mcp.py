"""Tests for MCP server tool functions (unit tests with mock DB)."""

from __future__ import annotations

import json

import pytest

from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import init_schema


@pytest.fixture
def db():
    conn = get_memory_db()
    init_schema(conn)
    conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', '/tmp/test')")
    conn.execute(
        "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at, session_title, session_summary, total_turns) "
        "VALUES ('s1', 'p1', 'claude', '2025-01-01', '2025-01-01', 'Test Session', 'A test session', 3)"
    )
    conn.execute(
        "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, content_hash, timestamp) "
        "VALUES ('t1', 's1', 1, 'fix auth bug', 'Fixed authentication', 'hash1', '2025-01-01')"
    )
    conn.execute(
        "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, content_hash, timestamp) "
        "VALUES ('t2', 's1', 2, 'add tests', 'Added unit tests', 'hash2', '2025-01-02')"
    )
    conn.commit()
    yield conn
    conn.close()


class TestMCPDetectCurrentSession:
    def test_detect_current_session(self, db):
        from entirecontext.mcp.server import _detect_current_session

        session_id = _detect_current_session(db)
        assert session_id == "s1"

    def test_detect_no_session(self):
        conn = get_memory_db()
        init_schema(conn)
        from entirecontext.mcp.server import _detect_current_session

        session_id = _detect_current_session(conn)
        assert session_id is None
        conn.close()


class TestMCPToolsDirectCalls:
    """Test the underlying logic that MCP tools use, without requiring mcp package."""

    def test_search_regex(self, db):
        from entirecontext.core.search import regex_search

        results = regex_search(db, "auth", target="turn")
        assert len(results) >= 1
        assert any("auth" in r.get("user_message", "").lower() for r in results)

    def test_search_fts(self, db):
        from entirecontext.core.search import fts_search

        results = fts_search(db, "authentication", target="turn")
        assert len(results) >= 1

    def test_session_context(self, db):
        session = db.execute("SELECT * FROM sessions WHERE id = 's1'").fetchone()
        assert session is not None
        assert session["session_title"] == "Test Session"

        turns = db.execute("SELECT * FROM turns WHERE session_id = 's1' ORDER BY turn_number DESC LIMIT 10").fetchall()
        assert len(turns) == 2

    def test_checkpoint_list_empty(self, db):
        checkpoints = db.execute("SELECT * FROM checkpoints").fetchall()
        assert len(checkpoints) == 0

    def test_attribution_query(self, db):
        db.execute("INSERT INTO checkpoints (id, session_id, git_commit_hash) VALUES ('cp1', 's1', 'abc')")
        db.execute("INSERT INTO agents (id, agent_type, name) VALUES ('a1', 'claude', 'Claude')")
        db.execute(
            "INSERT INTO attributions (id, checkpoint_id, file_path, start_line, end_line, attribution_type, agent_id) "
            "VALUES ('attr1', 'cp1', 'src/main.py', 1, 10, 'agent', 'a1')"
        )
        db.commit()

        rows = db.execute(
            "SELECT a.*, ag.name as agent_name FROM attributions a LEFT JOIN agents ag ON a.agent_id = ag.id WHERE a.file_path = ?",
            ("src/main.py",),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["agent_name"] == "Claude"

    def test_related_by_files(self, db):
        db.execute(
            "UPDATE turns SET files_touched = ? WHERE id = 't1'",
            (json.dumps(["src/auth.py"]),),
        )
        db.commit()

        rows = db.execute(
            "SELECT * FROM turns WHERE files_touched LIKE ?",
            ("%auth.py%",),
        ).fetchall()
        assert len(rows) == 1
