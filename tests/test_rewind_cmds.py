"""Tests for rewind commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestRewind:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["rewind", "cp-123"])
            assert result.exit_code == 1

    def test_checkpoint_not_found(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.checkpoint.get_checkpoint", return_value=None),
        ):
            result = runner.invoke(app, ["rewind", "cp-nonexistent"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()

    def test_normal_display(self):
        mock_conn = MagicMock()
        checkpoint = {
            "id": "cp-123456789012",
            "session_id": "sess-001",
            "git_commit_hash": "abc123def456",
            "git_branch": "main",
            "created_at": "2025-01-01T00:00:00",
            "diff_summary": "Changed 3 files",
            "files_snapshot": {"src/main.py": "content1", "README.md": "content2"},
        }
        session = {
            "id": "sess-001-full",
            "session_type": "claude",
            "session_title": "Test Session",
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.checkpoint.get_checkpoint", return_value=checkpoint),
            patch("entirecontext.core.session.get_session", return_value=session),
        ):
            result = runner.invoke(app, ["rewind", "cp-123456789012"])
            assert result.exit_code == 0
            assert "cp-123456789012"[:12] in result.output
            assert "abc123def456" in result.output
            assert "Changed 3 files" in result.output
            assert "Test Session" in result.output
            assert "src/main.py" in result.output

    def test_global_with_restore_fails(self):
        result = runner.invoke(app, ["rewind", "cp-123", "--global", "--restore"])
        assert result.exit_code == 1
        assert "not supported" in result.output.lower()

    def test_global_normal(self):
        checkpoint = {
            "id": "cp-global-12345",
            "repo_name": "my-repo",
            "git_commit_hash": "abc123",
            "git_branch": "main",
            "created_at": "2025-01-01T00:00:00",
            "diff_summary": None,
            "files_snapshot": None,
        }
        with patch(
            "entirecontext.core.cross_repo.cross_repo_rewind",
            return_value=(checkpoint, []),
        ):
            result = runner.invoke(app, ["rewind", "cp-global-12345", "--global"])
            assert result.exit_code == 0
            assert "my-repo" in result.output

    def test_global_not_found(self):
        with patch(
            "entirecontext.core.cross_repo.cross_repo_rewind",
            return_value=(None, []),
        ):
            result = runner.invoke(app, ["rewind", "cp-missing", "--global"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()
