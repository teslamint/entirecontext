"""Tests for database schema, FTS triggers, FK constraints, and migration."""

from __future__ import annotations

import sqlite3

import pytest

from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import check_and_migrate, get_current_version, init_schema
from entirecontext.db.schema import SCHEMA_VERSION


@pytest.fixture
def db():
    conn = get_memory_db()
    init_schema(conn)
    yield conn
    conn.close()


class TestSchemaCreation:
    def test_all_tables_exist(self, db):
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        expected = {
            "schema_version",
            "projects",
            "agents",
            "sessions",
            "turns",
            "turn_content",
            "checkpoints",
            "events",
            "event_sessions",
            "event_checkpoints",
            "attributions",
            "embeddings",
            "sync_metadata",
        }
        assert expected.issubset(tables)

    def test_fts_tables_exist(self, db):
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fts_%'").fetchall()
        }
        assert {"fts_turns", "fts_events", "fts_sessions"}.issubset(tables)

    def test_schema_version_set(self, db):
        version = get_current_version(db)
        assert version == SCHEMA_VERSION

    def test_foreign_keys_enabled(self, db):
        result = db.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1


class TestFTSTriggers:
    def _insert_session(self, db):
        db.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', '/tmp/test')")
        db.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at) "
            "VALUES ('s1', 'p1', 'claude', '2025-01-01', '2025-01-01')"
        )

    def test_fts_turns_insert(self, db):
        self._insert_session(db)
        db.execute(
            "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, content_hash, timestamp) "
            "VALUES ('t1', 's1', 1, 'fix the auth bug', 'fixed authentication issue', 'abc123', '2025-01-01')"
        )
        db.commit()

        result = db.execute("SELECT * FROM fts_turns WHERE fts_turns MATCH 'auth'").fetchall()
        assert len(result) == 1

    def test_fts_turns_update(self, db):
        self._insert_session(db)
        db.execute(
            "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, content_hash, timestamp) "
            "VALUES ('t1', 's1', 1, 'fix the auth bug', 'old summary', 'abc123', '2025-01-01')"
        )
        db.commit()

        db.execute("UPDATE turns SET assistant_summary = 'new database migration' WHERE id = 't1'")
        db.commit()

        old_results = db.execute("SELECT * FROM fts_turns WHERE fts_turns MATCH 'old'").fetchall()
        assert len(old_results) == 0

        new_results = db.execute("SELECT * FROM fts_turns WHERE fts_turns MATCH 'migration'").fetchall()
        assert len(new_results) == 1

    def test_fts_turns_delete(self, db):
        self._insert_session(db)
        db.execute(
            "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, content_hash, timestamp) "
            "VALUES ('t1', 's1', 1, 'hello world', 'greeting', 'abc', '2025-01-01')"
        )
        db.commit()

        db.execute("DELETE FROM turns WHERE id = 't1'")
        db.commit()

        result = db.execute("SELECT * FROM fts_turns WHERE fts_turns MATCH 'hello'").fetchall()
        assert len(result) == 0

    def test_fts_sessions_insert(self, db):
        db.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', '/tmp/test')")
        db.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at, session_title, session_summary) "
            "VALUES ('s1', 'p1', 'claude', '2025-01-01', '2025-01-01', 'Auth refactor', 'Refactored authentication module')"
        )
        db.commit()

        result = db.execute("SELECT * FROM fts_sessions WHERE fts_sessions MATCH 'authentication'").fetchall()
        assert len(result) == 1

    def test_fts_events_insert(self, db):
        db.execute(
            "INSERT INTO events (id, title, description, event_type) "
            "VALUES ('e1', 'Deploy v2.0', 'Major version deployment', 'milestone')"
        )
        db.commit()

        result = db.execute("SELECT * FROM fts_events WHERE fts_events MATCH 'deployment'").fetchall()
        assert len(result) == 1


class TestForeignKeys:
    def _setup_data(self, db):
        db.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', '/tmp/test')")
        db.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at) "
            "VALUES ('s1', 'p1', 'claude', '2025-01-01', '2025-01-01')"
        )
        db.execute(
            "INSERT INTO turns (id, session_id, turn_number, content_hash, timestamp) "
            "VALUES ('t1', 's1', 1, 'hash1', '2025-01-01')"
        )
        db.commit()

    def test_cascade_delete_session_deletes_turns(self, db):
        self._setup_data(db)
        db.execute("DELETE FROM sessions WHERE id = 's1'")
        db.commit()

        turns = db.execute("SELECT * FROM turns WHERE session_id = 's1'").fetchall()
        assert len(turns) == 0

    def test_cascade_delete_session_deletes_turn_content(self, db):
        self._setup_data(db)
        db.execute(
            "INSERT INTO turn_content (turn_id, content_path, content_size, content_hash) "
            "VALUES ('t1', 'content/s1/t1.jsonl', 100, 'hash1')"
        )
        db.commit()

        db.execute("DELETE FROM sessions WHERE id = 's1'")
        db.commit()

        content = db.execute("SELECT * FROM turn_content WHERE turn_id = 't1'").fetchall()
        assert len(content) == 0

    def test_checkpoint_parent_set_null_on_delete(self, db):
        self._setup_data(db)
        db.execute("INSERT INTO checkpoints (id, session_id, git_commit_hash) VALUES ('cp1', 's1', 'aaa111')")
        db.execute(
            "INSERT INTO checkpoints (id, session_id, git_commit_hash, parent_checkpoint_id) "
            "VALUES ('cp2', 's1', 'bbb222', 'cp1')"
        )
        db.commit()

        db.execute("DELETE FROM checkpoints WHERE id = 'cp1'")
        db.commit()

        child = db.execute("SELECT * FROM checkpoints WHERE id = 'cp2'").fetchone()
        assert child is not None
        assert child["parent_checkpoint_id"] is None

    def test_attribution_fk_set_null_on_delete(self, db):
        self._setup_data(db)
        db.execute("INSERT INTO agents (id, agent_type) VALUES ('a1', 'claude')")
        db.execute("INSERT INTO checkpoints (id, session_id, git_commit_hash) VALUES ('cp1', 's1', 'aaa')")
        db.execute(
            "INSERT INTO attributions (id, checkpoint_id, file_path, start_line, end_line, attribution_type, agent_id, session_id, turn_id) "
            "VALUES ('attr1', 'cp1', 'src/main.py', 1, 10, 'agent', 'a1', 's1', 't1')"
        )
        db.commit()

        db.execute("DELETE FROM agents WHERE id = 'a1'")
        db.commit()

        attr = db.execute("SELECT * FROM attributions WHERE id = 'attr1'").fetchone()
        assert attr is not None
        assert attr["agent_id"] is None


class TestMigration:
    def test_init_from_scratch(self):
        conn = get_memory_db()
        assert get_current_version(conn) == 0
        check_and_migrate(conn)
        assert get_current_version(conn) == SCHEMA_VERSION
        conn.close()

    def test_idempotent_init(self, db):
        v1 = get_current_version(db)
        check_and_migrate(db)
        v2 = get_current_version(db)
        assert v1 == v2

    def test_sync_metadata_singleton(self, db):
        db.execute("INSERT INTO sync_metadata (id, sync_status) VALUES (1, 'idle')")
        db.commit()

        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO sync_metadata (id, sync_status) VALUES (2, 'idle')")
