"""Tests for repo commands."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestRepoList:
    @patch("entirecontext.core.cross_repo.list_repos")
    def test_empty_list(self, mock_list_repos):
        mock_list_repos.return_value = []
        result = runner.invoke(app, ["repo", "list"])
        assert result.exit_code == 0
        assert "No registered repositories" in result.output

    @patch("entirecontext.core.cross_repo.list_repos")
    def test_normal_list(self, mock_list_repos, tmp_path):
        db_file = tmp_path / "local.db"
        db_file.touch()
        mock_list_repos.return_value = [
            {
                "repo_name": "my-project",
                "repo_path": "/home/user/my-project",
                "db_path": str(db_file),
                "session_count": 5,
                "turn_count": 42,
            },
            {
                "repo_name": "other-project",
                "repo_path": "/home/user/other-project",
                "db_path": "/nonexistent/path/local.db",
                "session_count": 0,
                "turn_count": 0,
            },
        ]
        result = runner.invoke(app, ["repo", "list"])
        assert result.exit_code == 0
        assert "my-project" in result.output
        assert "other-project" in result.output
        assert "42" in result.output
