"""Tests for MCP server tool functions (unit tests with mock DB)."""

from __future__ import annotations

import asyncio
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


class TestMCPToolIntegration:
    """Integration tests calling MCP tool functions directly via asyncio.run()."""

    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp")

    @pytest.fixture
    def mock_repo_db(self, db, monkeypatch):
        monkeypatch.setattr("entirecontext.mcp.server._get_repo_db", lambda: (db, "/tmp/test"))
        return db

    def test_search_regex_hit(self, mock_repo_db):
        from entirecontext.mcp.server import ec_search

        result = json.loads(asyncio.run(ec_search("auth")))
        assert result["count"] >= 1
        assert any("auth" in r["summary"].lower() for r in result["results"])

    def test_search_regex_miss(self, mock_repo_db):
        from entirecontext.mcp.server import ec_search

        result = json.loads(asyncio.run(ec_search("nonexistent_xyz_999")))
        assert result["count"] == 0

    def test_search_fts_hit(self, mock_repo_db):
        from entirecontext.mcp.server import ec_search

        result = json.loads(asyncio.run(ec_search("authentication", search_type="fts")))
        assert result["count"] >= 1

    def test_checkpoint_list_empty(self, mock_repo_db):
        from entirecontext.mcp.server import ec_checkpoint_list

        result = json.loads(asyncio.run(ec_checkpoint_list()))
        assert result["count"] == 0
        assert result["checkpoints"] == []

    def test_checkpoint_list_with_data(self, mock_repo_db):
        from entirecontext.mcp.server import ec_checkpoint_list

        mock_repo_db.execute(
            "INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch, created_at, diff_summary) "
            "VALUES ('cp1', 's1', 'abc123', 'main', '2025-01-01', 'Added auth')"
        )
        mock_repo_db.commit()
        result = json.loads(asyncio.run(ec_checkpoint_list()))
        assert result["count"] == 1
        assert result["checkpoints"][0]["commit_hash"] == "abc123"

    def test_session_context_auto_detect(self, mock_repo_db):
        from entirecontext.mcp.server import ec_session_context

        result = json.loads(asyncio.run(ec_session_context()))
        assert result["session_id"] == "s1"
        assert result["session_title"] == "Test Session"
        assert len(result["recent_turns"]) == 2

    def test_session_context_explicit_id(self, mock_repo_db):
        from entirecontext.mcp.server import ec_session_context

        result = json.loads(asyncio.run(ec_session_context(session_id="s1")))
        assert result["session_id"] == "s1"
        assert result["total_turns"] == 3

    def test_session_context_not_found(self, mock_repo_db):
        from entirecontext.mcp.server import ec_session_context

        result = json.loads(asyncio.run(ec_session_context(session_id="nonexistent")))
        assert "error" in result

    def test_attribution_with_data(self, mock_repo_db):
        from entirecontext.mcp.server import ec_attribution

        mock_repo_db.execute("INSERT INTO checkpoints (id, session_id, git_commit_hash) VALUES ('cp1', 's1', 'abc')")
        mock_repo_db.execute("INSERT INTO agents (id, agent_type, name) VALUES ('a1', 'claude', 'Claude')")
        mock_repo_db.execute(
            "INSERT INTO attributions (id, checkpoint_id, file_path, start_line, end_line, attribution_type, agent_id, session_id) "
            "VALUES ('attr1', 'cp1', 'src/main.py', 1, 10, 'agent', 'a1', 's1')"
        )
        mock_repo_db.commit()
        result = json.loads(asyncio.run(ec_attribution("src/main.py")))
        assert result["file_path"] == "src/main.py"
        assert len(result["attributions"]) == 1
        assert result["attributions"][0]["agent_name"] == "Claude"

    def test_attribution_empty(self, mock_repo_db):
        from entirecontext.mcp.server import ec_attribution

        result = json.loads(asyncio.run(ec_attribution("nonexistent.py")))
        assert result["file_path"] == "nonexistent.py"
        assert len(result["attributions"]) == 0

    def test_rewind_valid_checkpoint(self, mock_repo_db):
        from entirecontext.mcp.server import ec_rewind

        mock_repo_db.execute(
            "INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch, diff_summary) "
            "VALUES ('cp1', 's1', 'abc123', 'main', 'Added auth')"
        )
        mock_repo_db.commit()
        result = json.loads(asyncio.run(ec_rewind("cp1")))
        assert result["checkpoint_id"] == "cp1"
        assert result["commit_hash"] == "abc123"
        assert result["session"]["title"] == "Test Session"

    def test_rewind_not_found(self, mock_repo_db):
        from entirecontext.mcp.server import ec_rewind

        result = json.loads(asyncio.run(ec_rewind("nonexistent")))
        assert "error" in result

    def test_related_by_query(self, mock_repo_db):
        from entirecontext.mcp.server import ec_related

        result = json.loads(asyncio.run(ec_related(query="auth")))
        assert result["count"] >= 1
        assert any("auth" in r["summary"].lower() for r in result["related"])

    def test_related_by_files(self, mock_repo_db):
        from entirecontext.mcp.server import ec_related

        mock_repo_db.execute("UPDATE turns SET files_touched = ? WHERE id = 't1'", (json.dumps(["src/auth.py"]),))
        mock_repo_db.commit()
        result = json.loads(asyncio.run(ec_related(files=["src/auth.py"])))
        assert result["count"] >= 1
        assert any(r["relevance"] == "file:src/auth.py" for r in result["related"])

    def test_turn_content_valid(self, mock_repo_db):
        from entirecontext.mcp.server import ec_turn_content

        result = json.loads(asyncio.run(ec_turn_content("t1")))
        assert result["turn_id"] == "t1"
        assert result["user_message"] == "fix auth bug"
        assert result["content"] is None
        assert result["content_path"] is None

    def test_turn_content_not_found(self, mock_repo_db):
        from entirecontext.mcp.server import ec_turn_content

        result = json.loads(asyncio.run(ec_turn_content("nonexistent")))
        assert "error" in result

    def test_ec_search_semantic(self, mock_repo_db):
        import struct
        from unittest.mock import patch

        from entirecontext.mcp.server import ec_search

        fake_vec = struct.pack("3f", 1.0, 1.0, 1.0)
        mock_repo_db.execute(
            "INSERT INTO embeddings (id, source_type, source_id, model_name, vector, dimensions, text_hash) "
            "VALUES ('emb1', 'turn', 't1', 'all-MiniLM-L6-v2', ?, 3, 'hash')",
            (fake_vec,),
        )
        mock_repo_db.commit()

        with patch("entirecontext.core.embedding.embed_text", return_value=fake_vec):
            result = json.loads(asyncio.run(ec_search("auth", search_type="semantic")))
        assert result["count"] >= 1

    def test_ec_search_semantic_import_error(self, mock_repo_db):
        from unittest.mock import patch

        from entirecontext.mcp.server import ec_search

        with patch(
            "entirecontext.core.embedding.semantic_search",
            side_effect=ImportError("sentence-transformers is required"),
        ):
            result = json.loads(asyncio.run(ec_search("auth", search_type="semantic")))
        assert "error" in result
        assert "sentence-transformers" in result["error"]

    def test_no_repo_returns_error(self, monkeypatch):
        from entirecontext.mcp.server import ec_search

        monkeypatch.setattr("entirecontext.mcp.server._get_repo_db", lambda: (None, None))
        result = json.loads(asyncio.run(ec_search("test")))
        assert "error" in result
        assert "Not in an EntireContext-initialized repo" in result["error"]


class TestMcpQueryRedaction:
    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp")

    @pytest.fixture
    def mock_repo_db_with_secret(self, db, monkeypatch):
        db.execute(
            "UPDATE turns SET user_message = 'fix password=secret123', assistant_summary = 'Fixed token=abc123' WHERE id = 't1'"
        )
        db.commit()
        monkeypatch.setattr("entirecontext.mcp.server._get_repo_db", lambda: (db, "/tmp/test"))
        redaction_config = {
            "filtering": {
                "query_redaction": {
                    "enabled": True,
                    "patterns": [r"password\s*=\s*\S+", r"token\s*=\s*\S+"],
                    "replacement": "[FILTERED]",
                }
            },
            "capture": {"exclusions": {"enabled": False}},
        }
        monkeypatch.setattr("entirecontext.core.config.load_config", lambda *a, **kw: redaction_config)
        return db

    def test_ec_search_applies_redaction(self, mock_repo_db_with_secret):
        from entirecontext.mcp.server import ec_search

        result = json.loads(asyncio.run(ec_search("password")))
        assert result["count"] >= 1
        for r in result["results"]:
            assert "secret123" not in r.get("summary", "")

    def test_ec_turn_content_applies_redaction(self, mock_repo_db_with_secret):
        from entirecontext.mcp.server import ec_turn_content

        result = json.loads(asyncio.run(ec_turn_content("t1")))
        assert "secret123" not in result.get("user_message", "")
        assert "abc123" not in result.get("assistant_summary", "")
