"""Tests for indexing, attribution, embedding, and session summary."""

from __future__ import annotations

import struct
from unittest.mock import patch

import pytest

from entirecontext.core.attribution import get_file_attributions, get_file_attribution_summary
from entirecontext.core.embedding import cosine_similarity
from entirecontext.core.indexing import rebuild_fts_indexes
from entirecontext.core.session import create_session
from entirecontext.core.turn import create_turn
from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import init_schema


@pytest.fixture
def db():
    conn = get_memory_db()
    init_schema(conn)
    conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test-project', '/tmp/test')")
    conn.commit()
    yield conn
    conn.close()


class TestRebuildFtsIndexes:
    def test_rebuild_empty(self, db):
        counts = rebuild_fts_indexes(db)
        assert counts["fts_turns"] == 0
        assert counts["fts_events"] == 0
        assert counts["fts_sessions"] == 0

    def test_rebuild_with_data(self, db):
        create_session(db, "p1", session_id="s1")
        create_turn(db, "s1", 1, user_message="hello", assistant_summary="world")
        create_turn(db, "s1", 2, user_message="foo", assistant_summary="bar")

        counts = rebuild_fts_indexes(db)
        assert counts["fts_turns"] == 2

    def test_rebuild_sessions_fts(self, db):
        db.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at, session_title) "
            "VALUES ('s1', 'p1', 'claude', '2025-01-01', '2025-01-01', 'My Session')"
        )
        db.commit()

        counts = rebuild_fts_indexes(db)
        assert counts["fts_sessions"] == 1

    def test_rebuild_events_fts(self, db):
        db.execute(
            "INSERT INTO events (id, title, description, event_type, status) "
            "VALUES ('e1', 'Bug Fix', 'Fixed auth bug', 'bugfix', 'active')"
        )
        db.commit()

        counts = rebuild_fts_indexes(db)
        assert counts["fts_events"] == 1

    def test_fts_search_works_after_rebuild(self, db):
        create_session(db, "p1", session_id="s1")
        create_turn(db, "s1", 1, user_message="authentication bug fix", assistant_summary="Fixed login issue")

        rebuild_fts_indexes(db)

        from entirecontext.core.search import fts_search

        results = fts_search(db, "authentication", target="turn")
        assert len(results) >= 1


class TestAttribution:
    def _seed_attributions(self, db):
        create_session(db, "p1", session_id="s1")
        db.execute("INSERT INTO agents (id, agent_type, name) VALUES ('a1', 'claude', 'Claude')")
        db.execute("INSERT INTO checkpoints (id, session_id, git_commit_hash) VALUES ('cp1', 's1', 'abc123')")
        db.execute(
            "INSERT INTO attributions (id, checkpoint_id, file_path, start_line, end_line, attribution_type, agent_id, session_id, confidence) "
            "VALUES ('at1', 'cp1', 'src/main.py', 1, 10, 'human', NULL, 's1', 1.0)"
        )
        db.execute(
            "INSERT INTO attributions (id, checkpoint_id, file_path, start_line, end_line, attribution_type, agent_id, session_id, confidence) "
            "VALUES ('at2', 'cp1', 'src/main.py', 11, 30, 'agent', 'a1', 's1', 0.95)"
        )
        db.execute(
            "INSERT INTO attributions (id, checkpoint_id, file_path, start_line, end_line, attribution_type, agent_id, session_id, confidence) "
            "VALUES ('at3', 'cp1', 'src/other.py', 1, 5, 'human', NULL, 's1', 1.0)"
        )
        db.commit()

    def test_get_file_attributions_all(self, db):
        self._seed_attributions(db)
        results = get_file_attributions(db, "src/main.py")
        assert len(results) == 2
        assert results[0]["start_line"] == 1
        assert results[1]["start_line"] == 11

    def test_get_file_attributions_line_range(self, db):
        self._seed_attributions(db)
        results = get_file_attributions(db, "src/main.py", start_line=5, end_line=15)
        assert len(results) == 2

    def test_get_file_attributions_single_range(self, db):
        self._seed_attributions(db)
        results = get_file_attributions(db, "src/main.py", start_line=15, end_line=25)
        assert len(results) == 1
        assert results[0]["attribution_type"] == "agent"

    def test_get_file_attributions_no_results(self, db):
        self._seed_attributions(db)
        results = get_file_attributions(db, "nonexistent.py")
        assert len(results) == 0

    def test_get_file_attributions_agent_name(self, db):
        self._seed_attributions(db)
        results = get_file_attributions(db, "src/main.py")
        agent_attr = [r for r in results if r["attribution_type"] == "agent"][0]
        assert agent_attr["agent_name"] == "Claude"

    def test_get_file_attribution_summary(self, db):
        self._seed_attributions(db)
        summary = get_file_attribution_summary(db, "src/main.py")
        assert summary["total_lines"] == 30
        assert summary["human_lines"] == 10
        assert summary["agent_lines"] == 20
        assert summary["human_pct"] == pytest.approx(33.3, abs=0.1)
        assert summary["agent_pct"] == pytest.approx(66.7, abs=0.1)
        assert "Claude" in summary["agents"]

    def test_get_file_attribution_summary_empty(self, db):
        summary = get_file_attribution_summary(db, "nonexistent.py")
        assert summary["total_lines"] == 0
        assert summary["human_pct"] == 0.0


class TestCosineSimilarity:
    def test_identical_vectors(self):
        vec = struct.pack("3f", 1.0, 2.0, 3.0)
        assert cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = struct.pack("2f", 1.0, 0.0)
        b = struct.pack("2f", 0.0, 1.0)
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = struct.pack("2f", 1.0, 0.0)
        b = struct.pack("2f", -1.0, 0.0)
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector(self):
        a = struct.pack("2f", 0.0, 0.0)
        b = struct.pack("2f", 1.0, 1.0)
        assert cosine_similarity(a, b) == 0.0

    def test_dimension_mismatch(self):
        a = struct.pack("2f", 1.0, 0.0)
        b = struct.pack("3f", 1.0, 0.0, 0.0)
        with pytest.raises(ValueError, match="Dimension mismatch"):
            cosine_similarity(a, b)


class TestEmbedText:
    def test_embed_text_import_error(self):
        from entirecontext.core.embedding import embed_text

        with patch.dict("sys.modules", {"sentence_transformers": None}):
            with pytest.raises(ImportError, match="sentence-transformers"):
                embed_text("test")


class TestGenerateEmbeddings:
    def test_generate_embeddings_import_error(self, db):
        from entirecontext.core.indexing import generate_embeddings

        with patch.dict("sys.modules", {"sentence_transformers": None}):
            with pytest.raises(ImportError, match="sentence-transformers"):
                generate_embeddings(db, "/tmp/test")


class TestSessionSummaryPopulation:
    def test_populate_on_session_end(self, db):
        create_session(db, "p1", session_id="s1")
        create_turn(db, "s1", 1, user_message="fix the login bug", assistant_summary="Fixed authentication issue")
        create_turn(db, "s1", 2, user_message="add tests", assistant_summary="Added unit tests for auth")

        from entirecontext.hooks.session_lifecycle import _populate_session_summary

        _populate_session_summary(db, "s1")

        session = db.execute("SELECT session_title, session_summary FROM sessions WHERE id = 's1'").fetchone()
        assert session["session_title"] == "fix the login bug"
        assert "Fixed authentication issue" in session["session_summary"]
        assert "Added unit tests for auth" in session["session_summary"]

    def test_populate_skips_if_already_set(self, db):
        db.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at, session_title, session_summary) "
            "VALUES ('s2', 'p1', 'claude', '2025-01-01', '2025-01-01', 'Existing Title', 'Existing Summary')"
        )
        db.commit()
        create_turn(db, "s2", 1, user_message="different message", assistant_summary="different summary")

        from entirecontext.hooks.session_lifecycle import _populate_session_summary

        _populate_session_summary(db, "s2")

        session = db.execute("SELECT session_title, session_summary FROM sessions WHERE id = 's2'").fetchone()
        assert session["session_title"] == "Existing Title"
        assert session["session_summary"] == "Existing Summary"

    def test_populate_no_turns(self, db):
        create_session(db, "p1", session_id="s3")

        from entirecontext.hooks.session_lifecycle import _populate_session_summary

        _populate_session_summary(db, "s3")

        session = db.execute("SELECT session_title, session_summary FROM sessions WHERE id = 's3'").fetchone()
        assert session["session_title"] is None
        assert session["session_summary"] is None

    def test_populate_truncates_long_title(self, db):
        create_session(db, "p1", session_id="s4")
        long_message = "x" * 200
        create_turn(db, "s4", 1, user_message=long_message, assistant_summary="summary")

        from entirecontext.hooks.session_lifecycle import _populate_session_summary

        _populate_session_summary(db, "s4")

        session = db.execute("SELECT session_title FROM sessions WHERE id = 's4'").fetchone()
        assert len(session["session_title"]) == 100

    def test_populate_combines_summaries(self, db):
        create_session(db, "p1", session_id="s5")
        create_turn(db, "s5", 1, user_message="msg1", assistant_summary="summary1")
        create_turn(db, "s5", 2, user_message="msg2", assistant_summary="summary2")
        create_turn(db, "s5", 3, user_message="msg3", assistant_summary="summary3")

        from entirecontext.hooks.session_lifecycle import _populate_session_summary

        _populate_session_summary(db, "s5")

        session = db.execute("SELECT session_summary FROM sessions WHERE id = 's5'").fetchone()
        assert "summary1" in session["session_summary"]
        assert "summary2" in session["session_summary"]
        assert "summary3" in session["session_summary"]
        assert " | " in session["session_summary"]

    def test_populate_nonexistent_session(self, db):
        from entirecontext.hooks.session_lifecycle import _populate_session_summary

        _populate_session_summary(db, "nonexistent")
