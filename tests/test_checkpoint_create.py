"""Tests for checkpoint create CLI command and hook auto-checkpoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestCheckpointCreateCLI:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["checkpoint", "create"])
            assert result.exit_code == 1
            assert "Not in a git repository" in result.output

    def test_no_git_commit(self):
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.git_utils.get_current_commit", return_value=None),
        ):
            result = runner.invoke(app, ["checkpoint", "create"])
            assert result.exit_code == 1
            assert "Could not determine" in result.output

    def test_no_active_session(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.git_utils.get_current_commit", return_value="abc123" * 6 + "ab"),
            patch("entirecontext.core.git_utils.get_current_branch", return_value="main"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.get_current_session", return_value=None),
        ):
            result = runner.invoke(app, ["checkpoint", "create"])
            assert result.exit_code == 1
            assert "No active session" in result.output

    def test_explicit_session_not_found(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.git_utils.get_current_commit", return_value="abc123" * 6 + "ab"),
            patch("entirecontext.core.git_utils.get_current_branch", return_value="main"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.get_session", return_value=None),
        ):
            result = runner.invoke(app, ["checkpoint", "create", "--session", "nonexistent-id"])
            assert result.exit_code == 1
            assert "Session not found" in result.output

    def test_creates_with_message(self):
        mock_conn = MagicMock()
        session = {"id": "sess-abc123456789", "ended_at": None}
        cp = {
            "id": "cp-abc123456789xx",
            "git_commit_hash": "deadbeef1234" * 3 + "dead",
            "git_branch": "main",
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.git_utils.get_current_commit", return_value="deadbeef" * 5),
            patch("entirecontext.core.git_utils.get_current_branch", return_value="main"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.get_current_session", return_value=session),
            patch("entirecontext.core.checkpoint.list_checkpoints", return_value=[]),
            patch("entirecontext.core.checkpoint.create_checkpoint", return_value=cp),
        ):
            result = runner.invoke(app, ["checkpoint", "create", "-m", "my checkpoint"])
            assert result.exit_code == 0
            assert "Checkpoint created" in result.output
            assert "my checkpoint" in result.output

    def test_creates_with_explicit_session(self):
        mock_conn = MagicMock()
        session = {"id": "sess-explicit1234", "ended_at": None}
        cp = {"id": "cp-explicit123456", "git_commit_hash": "deadbeef" * 5, "git_branch": "feature"}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.git_utils.get_current_commit", return_value="deadbeef" * 5),
            patch("entirecontext.core.git_utils.get_current_branch", return_value="feature"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.get_session", return_value=session),
            patch("entirecontext.core.checkpoint.list_checkpoints", return_value=[]),
            patch("entirecontext.core.checkpoint.create_checkpoint", return_value=cp) as mock_create,
        ):
            result = runner.invoke(app, ["checkpoint", "create", "-s", "sess-explicit1234", "-m", "explicit"])
            assert result.exit_code == 0
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["session_id"] == "sess-explicit1234"

    def test_creates_with_snapshot(self):
        mock_conn = MagicMock()
        session = {"id": "sess-snap12345678", "ended_at": None}
        cp = {"id": "cp-snap123456789x", "git_commit_hash": "deadbeef" * 5, "git_branch": "main"}
        snapshot = {"src/main.py": "abc123" * 6 + "ab", "README.md": "def456" * 6 + "de"}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.git_utils.get_current_commit", return_value="deadbeef" * 5),
            patch("entirecontext.core.git_utils.get_current_branch", return_value="main"),
            patch("entirecontext.core.git_utils.get_tracked_files_snapshot", return_value=snapshot),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.get_current_session", return_value=session),
            patch("entirecontext.core.checkpoint.list_checkpoints", return_value=[]),
            patch("entirecontext.core.checkpoint.create_checkpoint", return_value=cp) as mock_create,
        ):
            result = runner.invoke(app, ["checkpoint", "create", "--snapshot"])
            assert result.exit_code == 0
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["files_snapshot"] == snapshot

    def test_auto_generates_diff_summary(self):
        mock_conn = MagicMock()
        session = {"id": "sess-diff12345678", "ended_at": None}
        prev_cp = {"git_commit_hash": "prevcommit" + "a" * 30}
        cp = {"id": "cp-diff1234567890", "git_commit_hash": "deadbeef" * 5, "git_branch": "main"}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.git_utils.get_current_commit", return_value="deadbeef" * 5),
            patch("entirecontext.core.git_utils.get_current_branch", return_value="main"),
            patch("entirecontext.core.git_utils.get_diff_stat", return_value="1 file changed") as mock_diff,
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.get_current_session", return_value=session),
            patch("entirecontext.core.checkpoint.list_checkpoints", return_value=[prev_cp]),
            patch("entirecontext.core.checkpoint.create_checkpoint", return_value=cp),
        ):
            result = runner.invoke(app, ["checkpoint", "create"])
            assert result.exit_code == 0
            mock_diff.assert_called_once_with("/tmp/test", from_commit=prev_cp["git_commit_hash"])


class TestAutoCheckpointHook:
    def test_disabled_by_default_skips(self, ec_repo, monkeypatch):
        from entirecontext.hooks.session_lifecycle import _maybe_create_auto_checkpoint

        with patch("entirecontext.core.checkpoint.create_checkpoint") as mock_create:
            _maybe_create_auto_checkpoint(str(ec_repo), "some-session-id")
            mock_create.assert_not_called()

    def test_enabled_creates_checkpoint(self, ec_repo, ec_db):
        from entirecontext.core.project import find_git_root
        from entirecontext.core.session import create_session
        from entirecontext.db import get_db
        from entirecontext.hooks.session_lifecycle import _maybe_create_auto_checkpoint

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id)
        session_id = session["id"]
        ec_db.close()

        with patch("entirecontext.core.config.load_config", return_value={"capture": {"checkpoint_on_session_end": True}}):
            _maybe_create_auto_checkpoint(str(ec_repo), session_id)

        conn = get_db(str(ec_repo))
        checkpoints = conn.execute("SELECT * FROM checkpoints WHERE session_id = ?", (session_id,)).fetchall()
        conn.close()
        assert len(checkpoints) == 1
        assert checkpoints[0]["metadata"] is not None
        import json
        meta = json.loads(checkpoints[0]["metadata"])
        assert meta["source"] == "auto_session_end"

    def test_exception_does_not_crash(self, ec_repo):
        from entirecontext.hooks.session_lifecycle import _maybe_create_auto_checkpoint

        with patch("entirecontext.core.config.load_config", side_effect=RuntimeError("boom")):
            _maybe_create_auto_checkpoint(str(ec_repo), "any-session-id")

    def test_no_git_commit_skips(self, ec_repo, ec_db):
        from entirecontext.core.session import create_session
        from entirecontext.hooks.session_lifecycle import _maybe_create_auto_checkpoint

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id)
        session_id = session["id"]
        ec_db.close()

        with (
            patch("entirecontext.core.config.load_config", return_value={"capture": {"checkpoint_on_session_end": True}}),
            patch("entirecontext.core.git_utils.get_current_commit", return_value=None),
        ):
            from entirecontext.db import get_db as _get_db
            with patch("entirecontext.core.checkpoint.create_checkpoint") as mock_create:
                _maybe_create_auto_checkpoint(str(ec_repo), session_id)
                mock_create.assert_not_called()


class TestSessionStartMetadata:
    def test_stores_start_git_commit(self, ec_repo, isolated_global_db):
        import json
        import subprocess

        from entirecontext.db import get_db
        from entirecontext.hooks.session_lifecycle import on_session_start

        on_session_start({"session_id": "test-session-meta", "cwd": str(ec_repo), "source": "startup"})

        conn = get_db(str(ec_repo))
        row = conn.execute("SELECT metadata FROM sessions WHERE id = ?", ("test-session-meta",)).fetchone()
        conn.close()

        assert row is not None
        assert row["metadata"] is not None
        meta = json.loads(row["metadata"])
        assert "start_git_commit" in meta
        assert len(meta["start_git_commit"]) == 40

    def test_no_crash_when_git_fails(self, ec_repo, isolated_global_db, monkeypatch):
        import subprocess as sp

        from entirecontext.db import get_db
        from entirecontext.hooks.session_lifecycle import on_session_start

        original_run = sp.run

        def mock_run(cmd, *args, **kwargs):
            if "rev-parse" in cmd and "HEAD" in cmd and "--show-toplevel" not in cmd:
                raise FileNotFoundError
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(sp, "run", mock_run)

        on_session_start({"session_id": "test-no-git", "cwd": str(ec_repo), "source": "startup"})

        conn = get_db(str(ec_repo))
        row = conn.execute("SELECT id FROM sessions WHERE id = ?", ("test-no-git",)).fetchone()
        conn.close()
        assert row is not None
