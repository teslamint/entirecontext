"""Integration tests for TQL — temporal filters against real DB and git repos."""

from __future__ import annotations

import sqlite3
from uuid import uuid4

import pytest

from entirecontext.core.search import fts_search, hybrid_search, regex_search
from entirecontext.core.tql import TQLContext, resolve_temporal_ref


@pytest.fixture
def conn_with_turns(tmp_path):
    """Create an in-memory DB with turns at different timestamps."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE projects (id TEXT, repo_path TEXT)")
    db.execute("INSERT INTO projects (id, repo_path) VALUES ('p1', ?)", (str(tmp_path),))
    db.execute(
        """CREATE TABLE sessions (
            id TEXT PRIMARY KEY, session_title TEXT, session_summary TEXT,
            session_type TEXT, started_at TEXT, last_activity_at TEXT
        )"""
    )
    db.execute(
        """CREATE TABLE turns (
            id TEXT PRIMARY KEY, session_id TEXT, user_message TEXT,
            assistant_summary TEXT, timestamp TEXT, files_touched TEXT,
            git_commit_hash TEXT
        )"""
    )
    db.execute(
        """CREATE TABLE events (
            id TEXT PRIMARY KEY, event_type TEXT, title TEXT,
            description TEXT, status TEXT, created_at TEXT
        )"""
    )
    db.execute(
        """CREATE VIRTUAL TABLE fts_turns USING fts5(
            user_message, assistant_summary, content='turns', content_rowid='rowid'
        )"""
    )
    db.execute(
        """CREATE VIRTUAL TABLE fts_sessions USING fts5(
            session_title, session_summary, content='sessions', content_rowid='rowid'
        )"""
    )
    db.execute(
        """CREATE VIRTUAL TABLE fts_events USING fts5(
            title, description, content='events', content_rowid='rowid'
        )"""
    )

    sid = str(uuid4())
    db.execute(
        "INSERT INTO sessions VALUES (?, 'test session', 'summary', 'human', '2026-01-01 00:00:00', '2026-06-01')",
        (sid,),
    )

    turns = [
        (str(uuid4()), sid, "implement auth module", "added auth", "2026-01-15 10:00:00", None, None),
        (str(uuid4()), sid, "fix auth bug", "fixed login", "2026-03-20 14:00:00", None, None),
        (str(uuid4()), sid, "refactor auth layer", "refactored auth", "2026-05-10 09:00:00", None, None),
        (str(uuid4()), sid, "deploy auth service", "deployed", "2026-07-01 16:00:00", None, None),
    ]
    for t in turns:
        db.execute("INSERT INTO turns VALUES (?, ?, ?, ?, ?, ?, ?)", t)
        db.execute("INSERT INTO fts_turns(rowid, user_message, assistant_summary) VALUES (last_insert_rowid(), ?, ?)", (t[2], t[3]))

    events = [
        (str(uuid4()), "milestone", "auth v1", "first auth release", "done", "2026-02-01 00:00:00"),
        (str(uuid4()), "milestone", "auth v2", "second auth release", "done", "2026-06-15 00:00:00"),
    ]
    for e in events:
        db.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)", e)
        db.execute("INSERT INTO fts_events(rowid, title, description) VALUES (last_insert_rowid(), ?, ?)", (e[2], e[3]))

    db.commit()
    return db, turns, events


class TestSearchUntil:
    def test_regex_search_until(self, conn_with_turns):
        conn, turns, _ = conn_with_turns
        results = regex_search(conn, "auth", until="2026-04-01 00:00:00")
        assert len(results) == 2
        timestamps = [r["timestamp"] for r in results]
        assert all(t <= "2026-04-01 00:00:00" for t in timestamps)

    def test_regex_search_since_and_until(self, conn_with_turns):
        conn, turns, _ = conn_with_turns
        results = regex_search(conn, "auth", since="2026-03-01 00:00:00", until="2026-06-01 00:00:00")
        assert len(results) == 2

    def test_fts_search_until(self, conn_with_turns):
        conn, turns, _ = conn_with_turns
        results = fts_search(conn, "auth", until="2026-04-01 00:00:00")
        assert len(results) == 2

    def test_fts_search_events_until(self, conn_with_turns):
        conn, _, events = conn_with_turns
        results = fts_search(conn, "auth", target="event", until="2026-03-01 00:00:00")
        assert len(results) == 1
        assert results[0]["title"] == "auth v1"

    def test_hybrid_search_until(self, conn_with_turns):
        conn, turns, _ = conn_with_turns
        results = hybrid_search(conn, "auth", until="2026-04-01 00:00:00")
        assert len(results) == 2

    def test_until_excludes_future(self, conn_with_turns):
        conn, turns, _ = conn_with_turns
        results = regex_search(conn, "auth", until="2026-01-01 00:00:00")
        assert len(results) == 0

    def test_until_exclusive_date_only(self, conn_with_turns):
        """Date-only --until with exclusive=True includes all of that day."""
        conn, turns, _ = conn_with_turns
        # Turn at 2026-03-20 14:00:00 should be included with < 2026-03-21 00:00:00
        results = regex_search(conn, "auth", until="2026-03-21 00:00:00", until_exclusive=True)
        assert len(results) == 2  # Jan 15 + Mar 20

    def test_until_inclusive_datetime(self, conn_with_turns):
        """Datetime --until with exclusive=False uses <=."""
        conn, turns, _ = conn_with_turns
        results = regex_search(conn, "auth", until="2026-03-20 14:00:00", until_exclusive=False)
        assert len(results) == 2  # Jan 15 + Mar 20 (inclusive)


class TestDecisionsTemporalFilter:
    @pytest.fixture
    def decision_db(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute(
            """CREATE TABLE decisions (
                id TEXT PRIMARY KEY, title TEXT, rationale TEXT,
                scope TEXT, staleness_status TEXT, created_at TEXT,
                updated_at TEXT, superseded_by_id TEXT,
                alternatives TEXT, context_refs TEXT,
                auto_promotion_reset_at TEXT
            )"""
        )
        db.execute(
            """CREATE VIRTUAL TABLE fts_decisions USING fts5(
                title, rationale, content='decisions', content_rowid='rowid'
            )"""
        )

        decisions = [
            ("d1", "use REST API", "simplicity", "api", "fresh", "2026-01-10 00:00:00", "2026-06-01 00:00:00"),
            ("d2", "add GraphQL", "flexibility", "api", "fresh", "2026-03-15 00:00:00", "2026-03-15 00:00:00"),
            ("d3", "switch to gRPC", "performance", "api", "fresh", "2026-05-20 00:00:00", "2026-05-20 00:00:00"),
        ]
        for d in decisions:
            db.execute(
                "INSERT INTO decisions (id, title, rationale, scope, staleness_status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                d,
            )
            db.execute(
                "INSERT INTO fts_decisions(rowid, title, rationale) VALUES (last_insert_rowid(), ?, ?)",
                (d[1], d[2]),
            )
        db.commit()
        return db

    def test_fts_search_decisions_created_at_semantic(self, decision_db):
        """Decision created before --since but updated after must NOT appear."""
        from entirecontext.core.decisions import fts_search_decisions

        results = fts_search_decisions(decision_db, "API OR GraphQL OR gRPC", since="2026-03-01 00:00:00")
        ids = [r["id"] for r in results]
        assert "d1" not in ids
        assert "d2" in ids
        assert "d3" in ids

    def test_fts_search_decisions_until(self, decision_db):
        from entirecontext.core.decisions import fts_search_decisions

        results = fts_search_decisions(decision_db, "API OR GraphQL OR gRPC", until="2026-04-01 00:00:00")
        ids = [r["id"] for r in results]
        assert "d1" in ids
        assert "d2" in ids
        assert "d3" not in ids

    def test_list_decisions_since_until(self, decision_db):
        from entirecontext.core.decisions import list_decisions

        results = list_decisions(decision_db, since="2026-02-01 00:00:00", until="2026-04-01 00:00:00")
        ids = [r["id"] for r in results]
        assert ids == ["d2"]


class TestMixedTimestampFormats:
    """Verify datetime() normalization handles mixed stored formats."""

    @pytest.fixture
    def mixed_format_db(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute(
            """CREATE TABLE sessions (
                id TEXT PRIMARY KEY, session_title TEXT, session_summary TEXT,
                session_type TEXT, started_at TEXT, last_activity_at TEXT
            )"""
        )
        db.execute(
            """CREATE TABLE turns (
                id TEXT PRIMARY KEY, session_id TEXT, user_message TEXT,
                assistant_summary TEXT, timestamp TEXT, files_touched TEXT,
                git_commit_hash TEXT
            )"""
        )
        db.execute(
            """CREATE VIRTUAL TABLE fts_turns USING fts5(
                user_message, assistant_summary, content='turns', content_rowid='rowid'
            )"""
        )

        sid = str(uuid4())
        db.execute(
            "INSERT INTO sessions VALUES (?, 'mix test', 'summary', 'human', '2026-01-01T00:00:00+00:00', '2026-06-01')",
            (sid,),
        )

        turns = [
            (str(uuid4()), sid, "task A", "did A", "2026-03-01T10:00:00+00:00", None, None),
            (str(uuid4()), sid, "task B", "did B", "2026-03-01 12:00:00", None, None),
            (str(uuid4()), sid, "task C", "did C", "2026-04-15 08:00:00", None, None),
        ]
        for t in turns:
            db.execute("INSERT INTO turns VALUES (?, ?, ?, ?, ?, ?, ?)", t)
            db.execute(
                "INSERT INTO fts_turns(rowid, user_message, assistant_summary) VALUES (last_insert_rowid(), ?, ?)",
                (t[2], t[3]),
            )
        db.commit()
        return db

    def test_since_with_mixed_formats(self, mixed_format_db):
        results = fts_search(mixed_format_db, "task", since="2026-03-01 11:00:00")
        assert len(results) == 2

    def test_until_with_mixed_formats(self, mixed_format_db):
        results = fts_search(mixed_format_db, "task", until="2026-03-01 11:00:00")
        assert len(results) == 1


class TestResolveGitRef:
    def test_resolve_real_git_ref(self, tmp_path):
        """Test resolving a real git tag against a real repo."""
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "tag", "v1.0"], cwd=tmp_path, capture_output=True)

        ts, is_date = resolve_temporal_ref("v1.0", repo_path=str(tmp_path))
        assert ts is not None
        assert is_date is False
        assert len(ts) == 19
