"""Tests for sync commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestSync:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["sync"])
            assert result.exit_code == 1

    def test_not_initialized(self):
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value=None),
        ):
            result = runner.invoke(app, ["sync"])
            assert result.exit_code == 1
            assert "init" in result.output.lower()

    def test_success(self):
        mock_conn = MagicMock()
        sync_result = {
            "error": None,
            "exported_sessions": 3,
            "exported_checkpoints": 5,
            "committed": True,
            "pushed": True,
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.sync.engine.perform_sync", return_value=sync_result),
        ):
            result = runner.invoke(app, ["sync"])
            assert result.exit_code == 0
            assert "3 sessions" in result.output
            assert "5 checkpoints" in result.output
            assert "Sync complete" in result.output

    def test_sync_error(self):
        mock_conn = MagicMock()
        sync_result = {
            "error": "git push failed",
            "exported_sessions": 0,
            "exported_checkpoints": 0,
            "committed": False,
            "pushed": False,
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.sync.engine.perform_sync", return_value=sync_result),
        ):
            result = runner.invoke(app, ["sync"])
            assert result.exit_code == 1
            assert "git push failed" in result.output

    def test_sync_no_changes(self):
        mock_conn = MagicMock()
        sync_result = {
            "error": None,
            "exported_sessions": 0,
            "exported_checkpoints": 0,
            "committed": False,
            "pushed": False,
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.sync.engine.perform_sync", return_value=sync_result),
        ):
            result = runner.invoke(app, ["sync"])
            assert result.exit_code == 0
            assert "No changes to commit" in result.output

    def test_sync_no_filter_option_disables_filtering_in_runtime_config(self):
        mock_conn = MagicMock()
        sync_result = {
            "error": None,
            "exported_sessions": 1,
            "exported_checkpoints": 1,
            "committed": False,
            "pushed": False,
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.sync.engine.perform_sync", return_value=sync_result) as mock_sync,
        ):
            result = runner.invoke(app, ["sync", "--no-filter"])
            assert result.exit_code == 0

            runtime_config = mock_sync.call_args.kwargs["config"]
            assert runtime_config.get("security", {}).get("filter_secrets") is False, (
                "--no-filter must propagate to runtime sync config"
            )

    def test_sync_default_keeps_filtering_enabled(self):
        mock_conn = MagicMock()
        sync_result = {
            "error": None,
            "exported_sessions": 1,
            "exported_checkpoints": 1,
            "committed": False,
            "pushed": False,
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.sync.engine.perform_sync", return_value=sync_result) as mock_sync,
        ):
            result = runner.invoke(app, ["sync"])
            assert result.exit_code == 0

            runtime_config = mock_sync.call_args.kwargs["config"]
            assert runtime_config.get("security", {}).get("filter_secrets") is True, (
                "default sync must keep secret filtering enabled in runtime config"
            )


class TestPull:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["pull"])
            assert result.exit_code == 1

    def test_not_initialized(self):
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value=None),
        ):
            result = runner.invoke(app, ["pull"])
            assert result.exit_code == 1
            assert "init" in result.output.lower()

    def test_no_shadow_branch(self):
        mock_conn = MagicMock()
        pull_result = {
            "error": "no_shadow_branch",
            "imported_sessions": 0,
            "imported_checkpoints": 0,
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.sync.engine.perform_pull", return_value=pull_result),
        ):
            result = runner.invoke(app, ["pull"])
            assert result.exit_code == 1
            assert "No shadow branch" in result.output or "sync" in result.output.lower()

    def test_other_error(self):
        mock_conn = MagicMock()
        pull_result = {
            "error": "merge conflict",
            "imported_sessions": 0,
            "imported_checkpoints": 0,
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.sync.engine.perform_pull", return_value=pull_result),
        ):
            result = runner.invoke(app, ["pull"])
            assert result.exit_code == 1
            assert "merge conflict" in result.output

    def test_success(self):
        mock_conn = MagicMock()
        pull_result = {
            "error": None,
            "imported_sessions": 2,
            "imported_checkpoints": 4,
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.sync.engine.perform_pull", return_value=pull_result),
        ):
            result = runner.invoke(app, ["pull"])
            assert result.exit_code == 0
            assert "2 sessions" in result.output
            assert "4 checkpoints" in result.output
            assert "Pull complete" in result.output
