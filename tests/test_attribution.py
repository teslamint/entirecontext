"""Tests for attribution auto-generation pipeline."""

from __future__ import annotations

import subprocess

import pytest

from entirecontext.core.attribution import (
    create_attribution,
    generate_attributions_from_diff,
    get_file_attributions,
)
from entirecontext.core.checkpoint import create_checkpoint
from entirecontext.core.session import create_session


class TestCreateAttribution:
    @pytest.fixture
    def db(self):
        from entirecontext.db.connection import get_memory_db
        from entirecontext.db.migration import init_schema

        conn = get_memory_db()
        init_schema(conn)
        conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', '/tmp/test')")
        conn.execute("INSERT INTO agents (id, agent_type, name) VALUES ('a1', 'claude', 'Claude')")
        conn.commit()
        yield conn
        conn.close()

    def test_create_attribution(self, db):
        create_session(db, "p1", session_id="s1")
        create_checkpoint(db, "s1", "abc123", checkpoint_id="cp1")

        result = create_attribution(
            db,
            checkpoint_id="cp1",
            file_path="src/main.py",
            start_line=1,
            end_line=10,
            attribution_type="agent",
            agent_id="a1",
            session_id="s1",
        )
        assert result["file_path"] == "src/main.py"
        assert result["start_line"] == 1
        assert result["end_line"] == 10

        rows = get_file_attributions(db, "src/main.py")
        assert len(rows) == 1
        assert rows[0]["attribution_type"] == "agent"
        assert rows[0]["agent_name"] == "Claude"

    def test_create_attribution_human(self, db):
        create_session(db, "p1", session_id="s1")
        create_checkpoint(db, "s1", "abc123", checkpoint_id="cp1")

        result = create_attribution(
            db,
            checkpoint_id="cp1",
            file_path="src/main.py",
            start_line=1,
            end_line=5,
            attribution_type="human",
            session_id="s1",
        )
        assert result["attribution_type"] == "human"

        rows = get_file_attributions(db, "src/main.py")
        assert len(rows) == 1
        assert rows[0]["attribution_type"] == "human"
        assert rows[0]["agent_name"] is None


class TestGenerateAttributionsFromDiff:
    def test_generate_attributions_from_diff(self, ec_repo, ec_db):
        (ec_repo / "src").mkdir()
        (ec_repo / "src/main.py").write_text("line1\nline2\nline3\n")
        subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(ec_repo), "commit", "-m", "add main.py"], check=True, capture_output=True)

        (ec_repo / "src/main.py").write_text("line1\nnew_line\nline2\nline3\n")
        subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(ec_repo), "commit", "-m", "modify main.py"], check=True, capture_output=True)

        commit_hash = subprocess.run(
            ["git", "-C", str(ec_repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        project_row = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()
        create_session(ec_db, project_row["id"], session_id="s1")
        create_checkpoint(ec_db, "s1", commit_hash, checkpoint_id="cp1")

        count = generate_attributions_from_diff(
            ec_db,
            checkpoint_id="cp1",
            session_id="s1",
            agent_id=None,
            turn_id=None,
            repo_path=str(ec_repo),
            commit_hash=commit_hash,
        )
        assert count >= 1

        rows = get_file_attributions(ec_db, "src/main.py")
        assert len(rows) >= 1

    def test_generate_attributions_empty_diff(self, ec_repo, ec_db):
        subprocess.run(
            ["git", "-C", str(ec_repo), "commit", "--allow-empty", "-m", "empty"],
            check=True,
            capture_output=True,
        )

        commit_hash = subprocess.run(
            ["git", "-C", str(ec_repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        project_row = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()
        create_session(ec_db, project_row["id"], session_id="s1")
        create_checkpoint(ec_db, "s1", commit_hash, checkpoint_id="cp1")

        count = generate_attributions_from_diff(
            ec_db,
            checkpoint_id="cp1",
            session_id="s1",
            agent_id=None,
            turn_id=None,
            repo_path=str(ec_repo),
            commit_hash=commit_hash,
        )
        assert count == 0

    def test_generate_attributions_multiple_files(self, ec_repo, ec_db):
        (ec_repo / "a.py").write_text("old\n")
        (ec_repo / "b.py").write_text("old\n")
        subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(ec_repo), "commit", "-m", "add files"], check=True, capture_output=True)

        (ec_repo / "a.py").write_text("new_a\nold\n")
        (ec_repo / "b.py").write_text("new_b\nold\n")
        subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(ec_repo), "commit", "-m", "modify files"], check=True, capture_output=True)

        commit_hash = subprocess.run(
            ["git", "-C", str(ec_repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        project_row = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()
        create_session(ec_db, project_row["id"], session_id="s1")
        create_checkpoint(ec_db, "s1", commit_hash, checkpoint_id="cp1")

        count = generate_attributions_from_diff(
            ec_db,
            checkpoint_id="cp1",
            session_id="s1",
            agent_id=None,
            turn_id=None,
            repo_path=str(ec_repo),
            commit_hash=commit_hash,
        )
        assert count >= 2

        a_rows = get_file_attributions(ec_db, "a.py")
        b_rows = get_file_attributions(ec_db, "b.py")
        assert len(a_rows) >= 1
        assert len(b_rows) >= 1

    def test_attribution_links_to_session_and_agent(self, ec_repo, ec_db):
        (ec_repo / "src").mkdir(exist_ok=True)
        (ec_repo / "src/code.py").write_text("line1\n")
        subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(ec_repo), "commit", "-m", "add code"], check=True, capture_output=True)

        (ec_repo / "src/code.py").write_text("line1\nnew_line\n")
        subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(ec_repo), "commit", "-m", "modify code"], check=True, capture_output=True)

        commit_hash = subprocess.run(
            ["git", "-C", str(ec_repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        project_row = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()
        create_session(ec_db, project_row["id"], session_id="s1")
        ec_db.execute("INSERT INTO agents (id, agent_type, name) VALUES ('a1', 'claude', 'Claude')")
        ec_db.commit()
        create_checkpoint(ec_db, "s1", commit_hash, checkpoint_id="cp1")

        count = generate_attributions_from_diff(
            ec_db,
            checkpoint_id="cp1",
            session_id="s1",
            agent_id="a1",
            turn_id=None,
            repo_path=str(ec_repo),
            commit_hash=commit_hash,
        )
        assert count >= 1

        rows = get_file_attributions(ec_db, "src/code.py")
        assert len(rows) >= 1
        assert rows[0]["session_id"] == "s1"
        assert rows[0]["agent_id"] == "a1"
        assert rows[0]["attribution_type"] == "agent"
