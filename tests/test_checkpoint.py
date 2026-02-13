"""Tests for checkpoint core logic and CLI."""

from __future__ import annotations


import pytest

from entirecontext.core.checkpoint import create_checkpoint, diff_checkpoints, get_checkpoint, list_checkpoints
from entirecontext.core.session import create_session
from entirecontext.db.connection import get_memory_db
from entirecontext.db.migration import init_schema


@pytest.fixture
def db():
    conn = get_memory_db()
    init_schema(conn)
    conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test-project', '/tmp/test')")
    conn.commit()
    create_session(conn, "p1", session_id="s1")
    yield conn
    conn.close()


class TestCreateCheckpoint:
    def test_basic(self, db):
        result = create_checkpoint(db, "s1", "abc123def")
        assert result["session_id"] == "s1"
        assert result["git_commit_hash"] == "abc123def"
        assert result["id"] is not None

    def test_with_all_fields(self, db):
        result = create_checkpoint(
            db,
            "s1",
            "abc123def",
            git_branch="main",
            files_snapshot={"src/main.py": "hash1", "README.md": "hash2"},
            diff_summary="Added main module",
            metadata={"tool": "claude"},
            checkpoint_id="cp-custom",
        )
        assert result["id"] == "cp-custom"
        assert result["git_branch"] == "main"

    def test_with_parent(self, db):
        create_checkpoint(db, "s1", "aaa111", checkpoint_id="cp1")
        create_checkpoint(db, "s1", "bbb222", parent_checkpoint_id="cp1", checkpoint_id="cp2")
        fetched = get_checkpoint(db, "cp2")
        assert fetched["parent_checkpoint_id"] == "cp1"

    def test_files_snapshot_stored_as_json(self, db):
        snapshot = {"src/a.py": "hash_a", "src/b.py": "hash_b"}
        create_checkpoint(db, "s1", "abc123", files_snapshot=snapshot, checkpoint_id="cp-json")
        fetched = get_checkpoint(db, "cp-json")
        assert fetched["files_snapshot"] == snapshot

    def test_list_snapshot(self, db):
        snapshot = ["src/a.py", "src/b.py"]
        create_checkpoint(db, "s1", "abc123", files_snapshot=snapshot, checkpoint_id="cp-list")
        fetched = get_checkpoint(db, "cp-list")
        assert fetched["files_snapshot"] == snapshot


class TestGetCheckpoint:
    def test_exact_id(self, db):
        create_checkpoint(db, "s1", "abc123", checkpoint_id="cp-exact-123")
        result = get_checkpoint(db, "cp-exact-123")
        assert result is not None
        assert result["id"] == "cp-exact-123"

    def test_prefix_match(self, db):
        create_checkpoint(db, "s1", "abc123", checkpoint_id="cp-prefix-unique-id")
        result = get_checkpoint(db, "cp-prefix-unique")
        assert result is not None
        assert result["id"] == "cp-prefix-unique-id"

    def test_not_found(self, db):
        result = get_checkpoint(db, "nonexistent")
        assert result is None

    def test_metadata_deserialized(self, db):
        create_checkpoint(db, "s1", "abc123", metadata={"key": "val"}, checkpoint_id="cp-meta")
        result = get_checkpoint(db, "cp-meta")
        assert result["metadata"] == {"key": "val"}


class TestListCheckpoints:
    def test_empty(self, db):
        result = list_checkpoints(db)
        assert result == []

    def test_basic(self, db):
        create_checkpoint(db, "s1", "aaa", checkpoint_id="cp1")
        create_checkpoint(db, "s1", "bbb", checkpoint_id="cp2")
        result = list_checkpoints(db)
        assert len(result) == 2

    def test_filter_by_session(self, db):
        create_session(db, "p1", session_id="s2")
        create_checkpoint(db, "s1", "aaa", checkpoint_id="cp1")
        create_checkpoint(db, "s2", "bbb", checkpoint_id="cp2")
        result = list_checkpoints(db, session_id="s1")
        assert len(result) == 1
        assert result[0]["id"] == "cp1"

    def test_limit(self, db):
        for i in range(5):
            create_checkpoint(db, "s1", f"hash{i}", checkpoint_id=f"cp-lim-{i}")
        result = list_checkpoints(db, limit=3)
        assert len(result) == 3

    def test_order_by_created_desc(self, db):
        create_checkpoint(db, "s1", "aaa", checkpoint_id="cp-first")
        db.execute("UPDATE checkpoints SET created_at = '2025-01-01T00:00:00' WHERE id = 'cp-first'")
        db.commit()
        create_checkpoint(db, "s1", "bbb", checkpoint_id="cp-second")
        db.execute("UPDATE checkpoints SET created_at = '2025-01-02T00:00:00' WHERE id = 'cp-second'")
        db.commit()
        result = list_checkpoints(db)
        assert result[0]["id"] == "cp-second"


class TestDiffCheckpoints:
    def test_basic_diff(self, db):
        snap1 = {"a.py": "h1", "b.py": "h2", "c.py": "h3"}
        snap2 = {"b.py": "h2_new", "c.py": "h3", "d.py": "h4"}
        create_checkpoint(db, "s1", "aaa", files_snapshot=snap1, checkpoint_id="d1")
        create_checkpoint(db, "s1", "bbb", files_snapshot=snap2, checkpoint_id="d2")

        result = diff_checkpoints(db, "d1", "d2")
        assert "a.py" in result["removed"]
        assert "d.py" in result["added"]
        assert "b.py" in result["modified"]
        assert "c.py" in result["unchanged"]

    def test_not_found(self, db):
        create_checkpoint(db, "s1", "aaa", checkpoint_id="d1")
        result = diff_checkpoints(db, "d1", "nonexistent")
        assert "error" in result

    def test_empty_snapshots(self, db):
        create_checkpoint(db, "s1", "aaa", checkpoint_id="e1")
        create_checkpoint(db, "s1", "bbb", checkpoint_id="e2")
        result = diff_checkpoints(db, "e1", "e2")
        assert result["added"] == []
        assert result["removed"] == []
        assert result["modified"] == []

    def test_list_snapshots(self, db):
        create_checkpoint(db, "s1", "aaa", files_snapshot=["a.py", "b.py"], checkpoint_id="l1")
        create_checkpoint(db, "s1", "bbb", files_snapshot=["b.py", "c.py"], checkpoint_id="l2")
        result = diff_checkpoints(db, "l1", "l2")
        assert "a.py" in result["removed"]
        assert "c.py" in result["added"]
        assert "b.py" in result["unchanged"]


class TestCheckpointCLI:
    def test_checkpoint_list_no_repo(self, monkeypatch):
        from typer.testing import CliRunner

        from entirecontext.cli import app

        monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda *a, **kw: None)
        runner = CliRunner()
        result = runner.invoke(app, ["checkpoint", "list"])
        assert result.exit_code != 0

    def test_checkpoint_list_empty(self, ec_repo, ec_db, monkeypatch):
        from typer.testing import CliRunner

        from entirecontext.cli import app

        monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda *a, **kw: str(ec_repo))
        runner = CliRunner()
        result = runner.invoke(app, ["checkpoint", "list"])
        assert result.exit_code == 0
        assert "No checkpoints found" in result.output

    def test_checkpoint_list_with_data(self, ec_repo, ec_db, monkeypatch):
        from typer.testing import CliRunner

        from entirecontext.cli import app

        project_row = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()
        create_session(ec_db, project_row["id"], session_id="test-s1")
        create_checkpoint(ec_db, "test-s1", "abc123", git_branch="main", checkpoint_id="cp-test-1")

        monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda *a, **kw: str(ec_repo))
        runner = CliRunner()
        result = runner.invoke(app, ["checkpoint", "list"])
        assert result.exit_code == 0
        assert "cp-test-1" in result.output

    def test_checkpoint_show(self, ec_repo, ec_db, monkeypatch):
        from typer.testing import CliRunner

        from entirecontext.cli import app

        project_row = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()
        create_session(ec_db, project_row["id"], session_id="test-s1")
        create_checkpoint(
            ec_db,
            "test-s1",
            "abc123def",
            git_branch="main",
            diff_summary="Added auth",
            files_snapshot={"src/auth.py": "h1"},
            checkpoint_id="cp-show-1",
        )

        monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda *a, **kw: str(ec_repo))
        runner = CliRunner()
        result = runner.invoke(app, ["checkpoint", "show", "cp-show-1"])
        assert result.exit_code == 0
        assert "abc123def" in result.output
        assert "main" in result.output
        assert "Added auth" in result.output
        assert "src/auth.py" in result.output

    def test_checkpoint_show_not_found(self, ec_repo, ec_db, monkeypatch):
        from typer.testing import CliRunner

        from entirecontext.cli import app

        monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda *a, **kw: str(ec_repo))
        runner = CliRunner()
        result = runner.invoke(app, ["checkpoint", "show", "nonexistent"])
        assert result.exit_code != 0

    def test_checkpoint_diff(self, ec_repo, ec_db, monkeypatch):
        from typer.testing import CliRunner

        from entirecontext.cli import app

        project_row = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()
        create_session(ec_db, project_row["id"], session_id="test-s1")
        create_checkpoint(
            ec_db, "test-s1", "aaa", files_snapshot={"a.py": "h1", "b.py": "h2"}, checkpoint_id="cp-diff-1"
        )
        create_checkpoint(
            ec_db, "test-s1", "bbb", files_snapshot={"b.py": "h2_new", "c.py": "h3"}, checkpoint_id="cp-diff-2"
        )

        monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda *a, **kw: str(ec_repo))
        runner = CliRunner()
        result = runner.invoke(app, ["checkpoint", "diff", "cp-diff-1", "cp-diff-2"])
        assert result.exit_code == 0
        assert "a.py" in result.output
        assert "c.py" in result.output


class TestRewindCLI:
    def test_rewind_show(self, ec_repo, ec_db, monkeypatch):
        from typer.testing import CliRunner

        from entirecontext.cli import app

        project_row = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()
        create_session(ec_db, project_row["id"], session_id="test-s1")
        create_checkpoint(
            ec_db,
            "test-s1",
            "abc123",
            git_branch="main",
            diff_summary="Some changes",
            checkpoint_id="cp-rw-1",
        )

        monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda *a, **kw: str(ec_repo))
        runner = CliRunner()
        result = runner.invoke(app, ["rewind", "cp-rw-1"])
        assert result.exit_code == 0
        assert "abc123" in result.output
        assert "Some changes" in result.output

    def test_rewind_not_found(self, ec_repo, ec_db, monkeypatch):
        from typer.testing import CliRunner

        from entirecontext.cli import app

        monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda *a, **kw: str(ec_repo))
        runner = CliRunner()
        result = runner.invoke(app, ["rewind", "nonexistent"])
        assert result.exit_code != 0
