"""Tests for checkpoint commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestCheckpointList:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["checkpoint", "list"])
            assert result.exit_code == 1

    def test_empty_list(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.checkpoint.list_checkpoints", return_value=[]),
        ):
            result = runner.invoke(app, ["checkpoint", "list"])
            assert result.exit_code == 0
            assert "No checkpoints found" in result.output

    def test_normal_list(self):
        mock_conn = MagicMock()
        checkpoints = [
            {
                "id": "cp-abc123456789",
                "git_commit_hash": "deadbeef1234",
                "git_branch": "main",
                "created_at": "2025-01-01T00:00:00",
                "diff_summary": "Added 3 files",
            },
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.checkpoint.list_checkpoints", return_value=checkpoints),
        ):
            result = runner.invoke(app, ["checkpoint", "list"])
            assert result.exit_code == 0
            assert "Checkpoints" in result.output

    def test_global_list(self):
        checkpoints = [
            {
                "id": "cp-abc123456789",
                "repo_name": "myrepo",
                "git_commit_hash": "deadbeef1234",
                "git_branch": "main",
                "created_at": "2025-01-01T00:00:00",
                "diff_summary": "Added 3 files",
            },
        ]
        with patch(
            "entirecontext.core.cross_repo.cross_repo_checkpoints", return_value=(checkpoints, [])
        ):
            result = runner.invoke(app, ["checkpoint", "list", "--global"])
            assert result.exit_code == 0
            assert "Checkpoints" in result.output

    def test_global_list_empty(self):
        with patch("entirecontext.core.cross_repo.cross_repo_checkpoints", return_value=([], [])):
            result = runner.invoke(app, ["checkpoint", "list", "--global"])
            assert result.exit_code == 0
            assert "No checkpoints found" in result.output


class TestCheckpointShow:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["checkpoint", "show", "cp-123"])
            assert result.exit_code == 1

    def test_not_found(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.checkpoint.get_checkpoint", return_value=None),
        ):
            result = runner.invoke(app, ["checkpoint", "show", "cp-notexist"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()

    def test_normal_show(self):
        mock_conn = MagicMock()
        cp = {
            "id": "cp-abc123456789",
            "session_id": "sess-123456789",
            "git_commit_hash": "deadbeef1234",
            "git_branch": "main",
            "created_at": "2025-01-01T00:00:00",
            "diff_summary": "Added 3 files",
            "parent_checkpoint_id": None,
            "files_snapshot": None,
        }
        session = {
            "id": "sess-123456789abc",
            "session_type": "claude",
            "session_title": "Fix bug",
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.checkpoint.get_checkpoint", return_value=cp),
            patch("entirecontext.core.session.get_session", return_value=session),
        ):
            result = runner.invoke(app, ["checkpoint", "show", "cp-abc123456789"])
            assert result.exit_code == 0
            assert "Checkpoint" in result.output
            assert "Session" in result.output

    def test_show_with_files_snapshot(self):
        mock_conn = MagicMock()
        cp = {
            "id": "cp-abc123456789",
            "session_id": "sess-123456789",
            "git_commit_hash": "deadbeef1234",
            "git_branch": "main",
            "created_at": "2025-01-01T00:00:00",
            "diff_summary": None,
            "parent_checkpoint_id": "cp-parent12345",
            "files_snapshot": {"src/main.py": "hash1", "src/util.py": "hash2"},
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.checkpoint.get_checkpoint", return_value=cp),
            patch("entirecontext.core.session.get_session", return_value=None),
        ):
            result = runner.invoke(app, ["checkpoint", "show", "cp-abc123456789"])
            assert result.exit_code == 0
            assert "Files Snapshot" in result.output
            assert "Parent" in result.output


class TestCheckpointDiff:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["checkpoint", "diff", "cp1", "cp2"])
            assert result.exit_code == 1

    def test_error_result(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.checkpoint.diff_checkpoints", return_value={"error": "Checkpoint not found"}),
        ):
            result = runner.invoke(app, ["checkpoint", "diff", "cp1", "cp2"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()

    def test_normal_diff(self):
        mock_conn = MagicMock()
        diff_result = {
            "checkpoint_1": {"id": "cp-111111111111", "commit": "aaaa111111"},
            "checkpoint_2": {"id": "cp-222222222222", "commit": "bbbb222222"},
            "added": ["new_file.py"],
            "removed": ["old_file.py"],
            "modified": ["changed.py"],
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.checkpoint.diff_checkpoints", return_value=diff_result),
        ):
            result = runner.invoke(app, ["checkpoint", "diff", "cp1", "cp2"])
            assert result.exit_code == 0
            assert "Comparing" in result.output
            assert "Added" in result.output
            assert "Removed" in result.output
            assert "Modified" in result.output

    def test_no_differences(self):
        mock_conn = MagicMock()
        diff_result = {
            "checkpoint_1": {"id": "cp-111111111111", "commit": "aaaa111111"},
            "checkpoint_2": {"id": "cp-222222222222", "commit": "bbbb222222"},
            "added": [],
            "removed": [],
            "modified": [],
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.checkpoint.diff_checkpoints", return_value=diff_result),
        ):
            result = runner.invoke(app, ["checkpoint", "diff", "cp1", "cp2"])
            assert result.exit_code == 0
            assert "No differences" in result.output
