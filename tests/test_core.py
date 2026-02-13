"""Tests for core business logic — session, turn, search, config, security."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import init_schema
from entirecontext.core.session import create_session, get_session, list_sessions, get_current_session, update_session
from entirecontext.core.turn import create_turn, get_turn, list_turns, content_hash, save_turn_content
from entirecontext.core.search import regex_search, fts_search
from entirecontext.core.config import _deep_merge, get_config_value, DEFAULT_CONFIG
from entirecontext.core.security import filter_secrets, scan_for_secrets


@pytest.fixture
def db():
    conn = get_memory_db()
    init_schema(conn)
    conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test-project', '/tmp/test')")
    conn.commit()
    yield conn
    conn.close()


class TestSession:
    def test_create_session(self, db):
        result = create_session(db, "p1")
        assert result["project_id"] == "p1"
        assert result["id"] is not None

    def test_get_session(self, db):
        create_session(db, "p1", session_id="test-session")
        fetched = get_session(db, "test-session")
        assert fetched is not None
        assert fetched["id"] == "test-session"

    def test_list_sessions(self, db):
        create_session(db, "p1", session_id="s1")
        create_session(db, "p1", session_id="s2")
        sessions = list_sessions(db, project_id="p1")
        assert len(sessions) == 2

    def test_get_current_session(self, db):
        create_session(db, "p1", session_id="s1")
        current = get_current_session(db)
        assert current is not None
        assert current["id"] == "s1"

    def test_get_current_session_none_when_ended(self, db):
        create_session(db, "p1", session_id="s1")
        update_session(db, "s1", ended_at="2025-01-01T00:00:00Z")
        current = get_current_session(db)
        assert current is None

    def test_update_session(self, db):
        create_session(db, "p1", session_id="s1")
        update_session(db, "s1", session_title="My Session")
        s = get_session(db, "s1")
        assert s["session_title"] == "My Session"


class TestTurn:
    def test_create_turn(self, db):
        create_session(db, "p1", session_id="s1")
        turn = create_turn(db, "s1", 1, user_message="hello", assistant_summary="hi there")
        assert turn["session_id"] == "s1"
        assert turn["turn_number"] == 1

    def test_content_hash_calculation(self):
        h1 = content_hash("hello", "world")
        h2 = content_hash("hello", "world")
        h3 = content_hash("different", "message")
        assert h1 == h2
        assert h1 != h3

    def test_content_hash_handles_none(self):
        h = content_hash(None, None)
        assert isinstance(h, str)
        assert len(h) == 32

    def test_get_turn(self, db):
        create_session(db, "p1", session_id="s1")
        create_turn(db, "s1", 1, user_message="test", turn_id="t1")
        fetched = get_turn(db, "t1")
        assert fetched is not None
        assert fetched["user_message"] == "test"

    def test_list_turns(self, db):
        create_session(db, "p1", session_id="s1")
        create_turn(db, "s1", 1, user_message="first")
        create_turn(db, "s1", 2, user_message="second")
        turns = list_turns(db, "s1")
        assert len(turns) == 2
        assert turns[0]["turn_number"] == 1

    def test_save_turn_content(self, db):
        create_session(db, "p1", session_id="s1")
        create_turn(db, "s1", 1, turn_id="t1")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = tmpdir
            db.execute("UPDATE projects SET repo_path = ? WHERE id = 'p1'", (repo_path,))
            db.commit()

            content = '{"role":"user","content":"hello"}\n{"role":"assistant","content":"hi"}\n'
            rel_path = save_turn_content(repo_path, db, "t1", "s1", content)

            assert "content/s1/t1.jsonl" in rel_path

            row = db.execute("SELECT * FROM turn_content WHERE turn_id = 't1'").fetchone()
            assert row is not None
            assert row["content_size"] > 0

            full_path = Path(repo_path) / ".entirecontext" / rel_path
            assert full_path.exists()
            assert full_path.read_text() == content


class TestSearch:
    def _seed_data(self, db):
        create_session(db, "p1", session_id="s1")
        create_turn(
            db, "s1", 1, user_message="fix the authentication bug", assistant_summary="Fixed auth issue in login.py"
        )
        create_turn(
            db,
            "s1",
            2,
            user_message="add rate limiting",
            assistant_summary="Added rate limiter middleware",
            files_touched=json.dumps(["src/middleware.py"]),
        )
        create_turn(
            db,
            "s1",
            3,
            user_message="deploy to staging",
            assistant_summary="Deployed version 2.1",
            git_commit_hash="abc123",
        )

    def test_regex_search_basic(self, db):
        self._seed_data(db)
        results = regex_search(db, "auth", target="turn")
        assert len(results) >= 1
        assert any("auth" in (r.get("user_message", "") + r.get("assistant_summary", "")).lower() for r in results)

    def test_regex_search_file_filter(self, db):
        self._seed_data(db)
        results = regex_search(db, "rate", target="turn", file_filter="middleware.py")
        assert len(results) >= 1

    def test_regex_search_commit_filter(self, db):
        self._seed_data(db)
        results = regex_search(db, "deploy", target="turn", commit_filter="abc123")
        assert len(results) >= 1

    def test_regex_search_no_results(self, db):
        self._seed_data(db)
        results = regex_search(db, "nonexistent_term_xyz", target="turn")
        assert len(results) == 0

    def test_fts_search_basic(self, db):
        self._seed_data(db)
        results = fts_search(db, "authentication", target="turn")
        assert len(results) >= 1

    def test_fts_search_session(self, db):
        db.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p2', 'test2', '/tmp/test2')")
        db.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at, session_title, session_summary) "
            "VALUES ('s2', 'p2', 'claude', '2025-01-01', '2025-01-01', 'Database migration', 'Migrated to new schema')"
        )
        db.commit()
        results = fts_search(db, "migration", target="session")
        assert len(results) >= 1


class TestConfig:
    def test_default_config(self):
        assert DEFAULT_CONFIG["capture"]["auto_capture"] is True
        assert DEFAULT_CONFIG["search"]["default_mode"] == "regex"

    def test_deep_merge(self):
        base = {"a": {"b": 1, "c": 2}, "d": 3}
        override = {"a": {"b": 10, "e": 5}}
        result = _deep_merge(base, override)
        assert result["a"]["b"] == 10
        assert result["a"]["c"] == 2
        assert result["a"]["e"] == 5
        assert result["d"] == 3

    def test_get_config_value(self):
        config = {"a": {"b": {"c": 42}}}
        assert get_config_value(config, "a.b.c") == 42
        assert get_config_value(config, "a.b") == {"c": 42}
        assert get_config_value(config, "nonexistent") is None


class TestSecurity:
    def test_filter_api_key(self):
        text = "API_KEY=sk-1234567890abcdef"
        result = filter_secrets(text)
        assert "sk-1234567890abcdef" not in result
        assert "[REDACTED]" in result

    def test_filter_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOi.token.here"
        result = filter_secrets(text)
        assert "eyJhbGciOi" not in result

    def test_filter_github_pat(self):
        text = "token = ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
        result = filter_secrets(text)
        assert "ghp_" not in result

    def test_no_false_positive_on_normal_text(self):
        text = "This is a normal message about authentication patterns."
        result = filter_secrets(text)
        assert result == text

    def test_scan_for_secrets(self):
        text = "password=mysecret123 and api_key=abcdef"
        findings = scan_for_secrets(text)
        assert len(findings) >= 1

    def test_custom_patterns(self):
        text = "CUSTOM_SECRET_12345"
        result = filter_secrets(text, patterns=[r"CUSTOM_SECRET_\d+"])
        assert "CUSTOM_SECRET_12345" not in result
