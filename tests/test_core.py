"""Tests for core business logic — session, turn, search, config, security."""

from __future__ import annotations

import json

import pytest

from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import init_schema
from entirecontext.core.session import create_session, get_current_session, update_session
from entirecontext.core.turn import create_turn, content_hash
from entirecontext.core.search import regex_search, fts_search
from entirecontext.core.config import _deep_merge
from entirecontext.core.security import filter_secrets


@pytest.fixture
def db():
    conn = get_memory_db()
    init_schema(conn)
    conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test-project', '/tmp/test')")
    conn.commit()
    yield conn
    conn.close()


class TestSession:
    def test_get_current_session_none_when_ended(self, db):
        create_session(db, "p1", session_id="s1")
        update_session(db, "s1", ended_at="2025-01-01T00:00:00Z")
        current = get_current_session(db)
        assert current is None


class TestTurn:
    def test_content_hash_calculation(self):
        h1 = content_hash("hello", "world")
        h2 = content_hash("hello", "world")
        h3 = content_hash("different", "message")
        assert h1 == h2
        assert h1 != h3


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

    def test_regex_search_commit_filter(self, db):
        self._seed_data(db)
        results = regex_search(db, "deploy", target="turn", commit_filter="abc123")
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
    def test_deep_merge(self):
        base = {"a": {"b": 1, "c": 2}, "d": 3}
        override = {"a": {"b": 10, "e": 5}}
        result = _deep_merge(base, override)
        assert result["a"]["b"] == 10
        assert result["a"]["c"] == 2
        assert result["a"]["e"] == 5
        assert result["d"] == 3


class TestSecurity:
    def test_custom_patterns(self):
        text = "CUSTOM_SECRET_12345"
        result = filter_secrets(text, patterns=[r"CUSTOM_SECRET_\d+"])
        assert "CUSTOM_SECRET_12345" not in result
