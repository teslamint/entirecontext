"""Tests for Aline import feature."""

from __future__ import annotations

import sqlite3
from uuid import uuid4

import pytest

ALINE_SCHEMA = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, session_file_path TEXT, session_type TEXT,
    workspace_path TEXT, started_at TEXT, last_activity_at TEXT,
    session_title TEXT, session_summary TEXT, summary_status TEXT,
    total_turns INTEGER, agent_id TEXT, created_by TEXT, shared_by TEXT,
    total_turns_mtime TEXT
);
CREATE TABLE turns (
    id TEXT PRIMARY KEY, session_id TEXT, turn_number INTEGER,
    user_message TEXT, assistant_summary TEXT, llm_title TEXT,
    llm_description TEXT, model_name TEXT, content_hash TEXT,
    git_commit_hash TEXT, temp_title TEXT, started_at TEXT
);
CREATE TABLE turn_content (
    turn_id TEXT PRIMARY KEY, content TEXT, content_size INTEGER
);
CREATE TABLE events (
    id TEXT PRIMARY KEY, title TEXT, description TEXT, event_type TEXT,
    status TEXT, created_at TEXT, preset_questions TEXT, slack_message TEXT,
    share_url TEXT, share_id TEXT, share_admin_token TEXT,
    share_expiry_at TEXT, created_by TEXT, shared_by TEXT
);
CREATE TABLE event_sessions (
    event_id TEXT, session_id TEXT, PRIMARY KEY(event_id, session_id)
);
"""


@pytest.fixture
def aline_db(tmp_path):
    db_path = tmp_path / "aline.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(ALINE_SCHEMA)

    sid1 = str(uuid4())
    sid2 = str(uuid4())
    tid1 = str(uuid4())
    tid2 = str(uuid4())
    tid3 = str(uuid4())
    eid1 = str(uuid4())

    conn.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (sid1, "/tmp/s1.jsonl", "claude", "/workspace/project-a", "2024-01-01T10:00:00", "2024-01-01T11:00:00",
         "Fix auth bug", "Fixed authentication issue", "completed", 2, None, None, None, None),
    )
    conn.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (sid2, "/tmp/s2.jsonl", "claude", "/workspace/project-b", "2024-01-02T10:00:00", "2024-01-02T11:00:00",
         "Add tests", "Added test suite", "completed", 1, None, None, None, None),
    )

    conn.execute(
        "INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (tid1, sid1, 1, "fix the auth bug", "Fixed auth validation", "Auth fix", "Fixed auth", "claude-3",
         "hash1", "abc123", None, "2024-01-01T10:01:00"),
    )
    conn.execute(
        "INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (tid2, sid1, 2, "add error handling", "Added error handling", "Error handling", "Errors", "claude-3",
         "hash2", None, None, "2024-01-01T10:30:00"),
    )
    conn.execute(
        "INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (tid3, sid2, 1, "write tests", "Created test suite", "Tests", "Testing", "claude-3",
         "hash3", "def456", None, "2024-01-02T10:01:00"),
    )

    content1 = '{"role":"user","content":"fix the auth bug"}\n{"role":"assistant","content":"Done"}\n'
    content3 = '{"role":"user","content":"write tests"}\n{"role":"assistant","content":"Created tests"}\n'
    conn.execute("INSERT INTO turn_content VALUES (?,?,?)", (tid1, content1, len(content1)))
    conn.execute("INSERT INTO turn_content VALUES (?,?,?)", (tid3, content3, len(content3)))

    conn.execute(
        "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (eid1, "Auth Sprint", "Fix all auth issues", "task", "active", "2024-01-01T09:00:00",
         None, None, None, None, None, None, None, None),
    )
    conn.execute("INSERT INTO event_sessions VALUES (?,?)", (eid1, sid1))

    conn.commit()
    conn.close()

    return {
        "path": str(db_path),
        "session_ids": [sid1, sid2],
        "turn_ids": [tid1, tid2, tid3],
        "event_ids": [eid1],
    }


class TestImportFromAline:
    def test_full_import(self, ec_db, ec_repo, aline_db):
        from entirecontext.core.import_aline import import_from_aline

        project_id = ec_db.execute("SELECT id FROM projects").fetchone()["id"]
        result = import_from_aline(ec_db, aline_db["path"], project_id, str(ec_repo))

        assert result.sessions == 2
        assert result.turns == 3
        assert result.turn_content == 2
        assert result.checkpoints == 2
        assert result.events == 1
        assert result.event_links == 1
        assert not result.errors

        sessions = ec_db.execute("SELECT * FROM sessions WHERE project_id = ?", (project_id,)).fetchall()
        assert len(sessions) == 2

        turns = ec_db.execute("SELECT * FROM turns").fetchall()
        assert len(turns) == 3

        checkpoints = ec_db.execute("SELECT * FROM checkpoints").fetchall()
        assert len(checkpoints) == 2
        commit_hashes = {c["git_commit_hash"] for c in checkpoints}
        assert commit_hashes == {"abc123", "def456"}

    def test_idempotent(self, ec_db, ec_repo, aline_db):
        from entirecontext.core.import_aline import import_from_aline

        project_id = ec_db.execute("SELECT id FROM projects").fetchone()["id"]

        r1 = import_from_aline(ec_db, aline_db["path"], project_id, str(ec_repo))
        r2 = import_from_aline(ec_db, aline_db["path"], project_id, str(ec_repo))

        assert r1.sessions == 2
        assert r2.sessions == 0
        assert r2.turns == 0
        assert r2.turn_content == 0
        assert r2.checkpoints == 0
        assert r2.events == 0
        assert r2.event_links == 0
        assert not r2.errors

        total_sessions = ec_db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert total_sessions == 2

    def test_dry_run(self, ec_db, ec_repo, aline_db):
        from entirecontext.core.import_aline import import_from_aline

        project_id = ec_db.execute("SELECT id FROM projects").fetchone()["id"]
        result = import_from_aline(ec_db, aline_db["path"], project_id, str(ec_repo), dry_run=True)

        assert result.sessions == 2
        assert result.turns == 0

        total = ec_db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert total == 0

    def test_workspace_filter(self, ec_db, ec_repo, aline_db):
        from entirecontext.core.import_aline import import_from_aline

        project_id = ec_db.execute("SELECT id FROM projects").fetchone()["id"]
        result = import_from_aline(
            ec_db, aline_db["path"], project_id, str(ec_repo), workspace_filter="project-a"
        )

        assert result.sessions == 1
        assert result.turns == 2
        assert result.events == 1
        assert result.event_links == 1

    def test_skip_content(self, ec_db, ec_repo, aline_db):
        from entirecontext.core.import_aline import import_from_aline

        project_id = ec_db.execute("SELECT id FROM projects").fetchone()["id"]
        result = import_from_aline(ec_db, aline_db["path"], project_id, str(ec_repo), skip_content=True)

        assert result.sessions == 2
        assert result.turns == 3
        assert result.turn_content == 0

        content_count = ec_db.execute("SELECT COUNT(*) FROM turn_content").fetchone()[0]
        assert content_count == 0

    def test_db_not_found(self, ec_db, ec_repo):
        from entirecontext.core.import_aline import import_from_aline

        project_id = ec_db.execute("SELECT id FROM projects").fetchone()["id"]
        result = import_from_aline(ec_db, "/nonexistent/aline.db", project_id, str(ec_repo))

        assert len(result.errors) == 1
        assert "not found" in result.errors[0]

    def test_turn_content_written_to_disk(self, ec_db, ec_repo, aline_db):
        from entirecontext.core.import_aline import import_from_aline

        project_id = ec_db.execute("SELECT id FROM projects").fetchone()["id"]
        import_from_aline(ec_db, aline_db["path"], project_id, str(ec_repo))

        content_dir = ec_repo / ".entirecontext" / "content"
        jsonl_files = list(content_dir.glob("*.jsonl"))
        assert len(jsonl_files) == 2

        for f in jsonl_files:
            assert f.stat().st_size > 0

    def test_events_linked_correctly(self, ec_db, ec_repo, aline_db):
        from entirecontext.core.import_aline import import_from_aline

        project_id = ec_db.execute("SELECT id FROM projects").fetchone()["id"]
        import_from_aline(ec_db, aline_db["path"], project_id, str(ec_repo))

        links = ec_db.execute("SELECT * FROM event_sessions").fetchall()
        assert len(links) == 1
        assert links[0]["event_id"] == aline_db["event_ids"][0]
        assert links[0]["session_id"] == aline_db["session_ids"][0]


class TestImportCLI:
    def test_import_help(self):
        from typer.testing import CliRunner
        from entirecontext.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["import", "--help"])
        assert result.exit_code == 0
        assert "--from-aline" in result.output
        assert "--dry-run" in result.output
        assert "--skip-content" in result.output

    def test_import_no_source(self):
        from typer.testing import CliRunner
        from entirecontext.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["import"])
        assert result.exit_code == 1
        assert "Specify an import source" in result.output
