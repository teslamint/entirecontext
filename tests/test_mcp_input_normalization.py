"""Regression tests for issue #44: normalize common input shapes and friendlier query errors."""

from __future__ import annotations

import asyncio
import json

import pytest

from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import init_schema
from entirecontext.mcp import runtime
from entirecontext.mcp.tools.decisions import _ensure_list


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def mock_repo_db(db, monkeypatch):
    class _NoCloseConn:
        def __init__(self, conn):
            object.__setattr__(self, "_conn", conn)

        def close(self):
            pass

        def __getattr__(self, name):
            return getattr(object.__getattribute__(self, "_conn"), name)

    wrapper = _NoCloseConn(db)
    monkeypatch.setattr("entirecontext.mcp.runtime.get_repo_db", lambda repo_hint=None: (wrapper, "/tmp/test"))
    return wrapper


# ---------------------------------------------------------------------------
# Part 1: normalize_repo_names
# ---------------------------------------------------------------------------


class TestNormalizeRepoNames:
    def test_string_coerced_to_list(self):
        assert runtime.normalize_repo_names("myrepo") == ["myrepo"]

    def test_string_star_returns_none(self):
        assert runtime.normalize_repo_names("*") is None

    def test_list_unchanged(self):
        assert runtime.normalize_repo_names(["a", "b"]) == ["a", "b"]

    def test_list_star_returns_none(self):
        assert runtime.normalize_repo_names(["*"]) is None

    def test_none_returns_none(self):
        assert runtime.normalize_repo_names(None) is None

    def test_empty_string_returns_none(self):
        assert runtime.normalize_repo_names("") is None

    def test_empty_list_returns_none(self):
        assert runtime.normalize_repo_names([]) is None

    def test_wildcard_star_triggers_cross_repo(self):
        """repos=["*"] should still trigger cross-repo mode (bool(repos) is True)
        even though normalize returns None (meaning 'all repos')."""
        repos_input = ["*"]
        assert bool(repos_input) is True
        assert runtime.normalize_repo_names(repos_input) is None

    def test_scalar_star_triggers_cross_repo(self):
        """repos="*" should trigger cross-repo mode."""
        repos_input = "*"
        assert bool(repos_input) is True
        assert runtime.normalize_repo_names(repos_input) is None


# ---------------------------------------------------------------------------
# Part 2: FTS query error handling
# ---------------------------------------------------------------------------


class TestFtsQueryErrorHandling:
    def test_fts_turns_bad_syntax_raises_valueerror(self, db):
        from entirecontext.core.search import _fts_search_turns

        with pytest.raises(ValueError, match="Invalid FTS query"):
            _fts_search_turns(db, "AND OR NOT", None, None, None, None, 10)

    def test_fts_sessions_bad_syntax_raises_valueerror(self, db):
        from entirecontext.core.search import _fts_search_sessions

        with pytest.raises(ValueError, match="Invalid FTS query"):
            _fts_search_sessions(db, "AND OR NOT", None, 10)

    def test_fts_events_bad_syntax_raises_valueerror(self, db):
        from entirecontext.core.search import _fts_search_events

        with pytest.raises(ValueError, match="Invalid FTS query"):
            _fts_search_events(db, "AND OR NOT", None, 10)

    def test_fts_colon_punctuation_raises_valueerror(self, db):
        from entirecontext.core.search import _fts_search_turns

        with pytest.raises(ValueError, match="Invalid FTS query"):
            _fts_search_turns(db, "foo:bar", None, None, None, None, 10)

    def test_fts_valid_query_still_works(self, db):
        from entirecontext.core.search import _fts_search_turns

        results = _fts_search_turns(db, "auth", None, None, None, None, 10)
        assert isinstance(results, list)

    def test_ec_search_fts_bad_syntax_returns_error_payload(self, mock_repo_db):
        from entirecontext.mcp.tools.search import ec_search

        result = json.loads(asyncio.run(ec_search("AND OR NOT", search_type="fts")))
        assert "error" in result
        assert "Invalid FTS query" in result["error"]

    def test_ec_search_hybrid_bad_syntax_returns_error_payload(self, mock_repo_db):
        from entirecontext.mcp.tools.search import ec_search

        result = json.loads(asyncio.run(ec_search("AND OR NOT", search_type="hybrid")))
        assert "error" in result
        assert "Invalid FTS query" in result["error"]


# ---------------------------------------------------------------------------
# Part 3: Decision field coercion
# ---------------------------------------------------------------------------


class TestEnsureList:
    def test_none_passthrough(self):
        assert _ensure_list(None, "f") is None

    def test_string_to_list(self):
        assert _ensure_list("a", "f") == ["a"]

    def test_dict_to_list(self):
        assert _ensure_list({"k": "v"}, "f") == [{"k": "v"}]

    def test_list_passthrough(self):
        assert _ensure_list(["a", "b"], "f") == ["a", "b"]

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="must be a list, string, or null"):
            _ensure_list(42, "field_name")


class TestDecisionCreateCoercion:
    def test_string_alternatives_coerced(self, mock_repo_db):
        from entirecontext.mcp.tools.decisions import ec_decision_create

        result = json.loads(
            asyncio.run(
                ec_decision_create(
                    title="Test decision",
                    rejected_alternatives="single alternative",
                )
            )
        )
        assert result["rejected_alternatives"] == ["single alternative"]

    def test_dict_evidence_coerced(self, mock_repo_db):
        from entirecontext.mcp.tools.decisions import ec_decision_create

        result = json.loads(
            asyncio.run(
                ec_decision_create(
                    title="Test decision",
                    supporting_evidence={"source": "benchmark", "result": "fast"},
                )
            )
        )
        assert result["supporting_evidence"] == [{"source": "benchmark", "result": "fast"}]

    def test_invalid_type_returns_error_payload(self, mock_repo_db):
        from entirecontext.mcp.tools.decisions import ec_decision_create

        result = json.loads(
            asyncio.run(
                ec_decision_create(
                    title="Test decision",
                    rejected_alternatives=42,
                )
            )
        )
        assert "error" in result
        assert "rejected_alternatives" in result["error"]
