"""Tests for purge operations."""

from __future__ import annotations

import pytest

from entirecontext.core.purge import ActiveSessionError, purge_by_pattern, purge_session, purge_turns
from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import init_schema


@pytest.fixture
def db_with_data(tmp_path):
    conn = get_memory_db()
    init_schema(conn)
    repo_path = str(tmp_path / "repo")

    conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', ?)", (repo_path,))
    conn.execute(
        "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at, ended_at) "
        "VALUES ('s1', 'p1', 'claude', '2025-01-01', '2025-01-01', '2025-01-02')"
    )
    conn.execute(
        "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, content_hash, timestamp) "
        "VALUES ('t1', 's1', 1, 'fix auth bug', 'Fixed authentication', 'hash1', '2025-01-01')"
    )
    conn.execute(
        "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, content_hash, timestamp) "
        "VALUES ('t2', 's1', 2, 'add password=secret123 handling', 'Added password handling', 'hash2', '2025-01-02')"
    )
    conn.execute(
        "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, content_hash, timestamp) "
        "VALUES ('t3', 's1', 3, 'refactor code', 'Refactored modules', 'hash3', '2025-01-03')"
    )

    content_dir = tmp_path / "repo" / ".entirecontext" / "content" / "s1"
    content_dir.mkdir(parents=True)
    (content_dir / "t1.jsonl").write_text('{"role":"user"}\n', encoding="utf-8")
    conn.execute(
        "INSERT INTO turn_content (turn_id, content_path, content_size, content_hash) "
        "VALUES ('t1', 'content/s1/t1.jsonl', 16, 'chash1')"
    )

    (content_dir / "t2.jsonl").write_text('{"role":"user"}\n', encoding="utf-8")
    conn.execute(
        "INSERT INTO turn_content (turn_id, content_path, content_size, content_hash) "
        "VALUES ('t2', 'content/s1/t2.jsonl', 16, 'chash2')"
    )

    conn.commit()
    yield conn, repo_path
    conn.close()


class TestPurgeTurns:
    def test_dry_run(self, db_with_data):
        conn, repo_path = db_with_data
        result = purge_turns(conn, repo_path, ["t1"], dry_run=True)
        assert result["matched_turns"] == 1
        assert result["deleted"] == 0
        assert result["dry_run"] is True
        assert conn.execute("SELECT * FROM turns WHERE id = 't1'").fetchone() is not None

    def test_execute(self, db_with_data):
        conn, repo_path = db_with_data
        result = purge_turns(conn, repo_path, ["t1"], dry_run=False)
        assert result["matched_turns"] == 1
        assert result["deleted"] == 1
        assert conn.execute("SELECT * FROM turns WHERE id = 't1'").fetchone() is None
        assert conn.execute("SELECT * FROM turn_content WHERE turn_id = 't1'").fetchone() is None
        from pathlib import Path

        assert not (Path(repo_path) / ".entirecontext" / "content" / "s1" / "t1.jsonl").exists()

    def test_fts_cleanup(self, db_with_data):
        conn, repo_path = db_with_data
        purge_turns(conn, repo_path, ["t1"], dry_run=False)
        results = conn.execute("SELECT * FROM fts_turns WHERE fts_turns MATCH 'authentication'").fetchall()
        assert len(results) == 0

    def test_nonexistent_id(self, db_with_data):
        conn, repo_path = db_with_data
        result = purge_turns(conn, repo_path, ["nonexistent"], dry_run=False)
        assert result["matched_turns"] == 0
        assert result["deleted"] == 0


class TestPurgeSession:
    def test_dry_run(self, db_with_data):
        conn, repo_path = db_with_data
        result = purge_session(conn, repo_path, "s1", dry_run=True)
        assert result["matched_turns"] == 3
        assert result["deleted"] == 0
        assert conn.execute("SELECT * FROM sessions WHERE id = 's1'").fetchone() is not None

    def test_execute_cascade(self, db_with_data):
        conn, repo_path = db_with_data
        conn.execute("INSERT INTO checkpoints (id, session_id, git_commit_hash) VALUES ('cp1', 's1', 'abc')")
        conn.commit()

        result = purge_session(conn, repo_path, "s1", dry_run=False)
        assert result["deleted"] == 3
        assert conn.execute("SELECT * FROM sessions WHERE id = 's1'").fetchone() is None
        assert conn.execute("SELECT * FROM turns WHERE session_id = 's1'").fetchone() is None
        assert conn.execute("SELECT * FROM turn_content WHERE turn_id = 't1'").fetchone() is None
        assert conn.execute("SELECT * FROM checkpoints WHERE session_id = 's1'").fetchone() is None

    def test_active_session(self, db_with_data):
        conn, repo_path = db_with_data
        conn.execute("UPDATE sessions SET ended_at = NULL WHERE id = 's1'")
        conn.commit()
        with pytest.raises(ActiveSessionError):
            purge_session(conn, repo_path, "s1", dry_run=False)


class TestPurgeByPattern:
    def test_dry_run(self, db_with_data):
        conn, repo_path = db_with_data
        result = purge_by_pattern(conn, repo_path, "password", dry_run=True)
        assert result["matched_turns"] == 1
        assert result["deleted"] == 0

    def test_no_match(self, db_with_data):
        conn, repo_path = db_with_data
        result = purge_by_pattern(conn, repo_path, "nonexistent_xyz_pattern")
        assert result["matched_turns"] == 0

    def test_execute(self, db_with_data):
        conn, repo_path = db_with_data
        result = purge_by_pattern(conn, repo_path, "password", dry_run=False)
        assert result["matched_turns"] == 1
        assert result["deleted"] == 1
        assert conn.execute("SELECT * FROM turns WHERE id = 't2'").fetchone() is None
        assert conn.execute("SELECT * FROM turns WHERE id = 't1'").fetchone() is not None
        assert conn.execute("SELECT * FROM turns WHERE id = 't3'").fetchone() is not None
