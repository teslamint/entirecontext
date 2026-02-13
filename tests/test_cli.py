"""Tests for CLI commands using Typer's CliRunner."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestStatusCommand:
    @patch("entirecontext.core.project.get_status")
    def test_status_not_initialized(self, mock_status):
        mock_status.return_value = {"initialized": False}
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "not initialized" in result.output.lower() or "ec init" in result.output.lower()

    @patch("entirecontext.core.project.get_status")
    def test_status_initialized(self, mock_status):
        mock_status.return_value = {
            "initialized": True,
            "project": {"id": "abc12345-uuid", "name": "myproject", "repo_path": "/tmp/test"},
            "session_count": 5,
            "turn_count": 42,
            "checkpoint_count": 10,
            "active_session": None,
        }
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "myproject" in result.output


class TestConfigCommand:
    @patch("entirecontext.core.project.find_git_root")
    def test_config_show_all(self, mock_git_root):
        mock_git_root.return_value = None
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0

    @patch("entirecontext.core.project.find_git_root")
    def test_config_get_key(self, mock_git_root):
        mock_git_root.return_value = None
        result = runner.invoke(app, ["config", "search.default_mode"])
        assert result.exit_code == 0
        assert "regex" in result.output


class TestSearchCommand:
    @patch("entirecontext.core.project.find_git_root")
    def test_search_not_in_repo(self, mock_git_root):
        mock_git_root.return_value = None
        result = runner.invoke(app, ["search", "test"])
        assert result.exit_code == 1

    def test_search_semantic_phase3(self):
        with patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"):
            with patch("entirecontext.db.connection.get_db"):
                result = runner.invoke(app, ["search", "test", "--semantic"])
                assert "Phase 3" in result.output


class TestPhase2Stubs:
    def test_checkpoint_list(self):
        result = runner.invoke(app, ["checkpoint", "list"])
        assert "Phase 2" in result.output

    def test_sync(self):
        result = runner.invoke(app, ["sync"])
        assert "Phase 2" in result.output

    def test_pull(self):
        result = runner.invoke(app, ["pull"])
        assert "Phase 2" in result.output

    def test_rewind(self):
        result = runner.invoke(app, ["rewind", "some-id"])
        assert "Phase 2" in result.output


class TestRewindSafety:
    def test_rewind_restore_dirty_tree(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("Result", (), {"stdout": "M src/main.py", "returncode": 0})()
            result = runner.invoke(app, ["rewind", "some-id", "--restore"])
            assert result.exit_code == 1
            assert "uncommitted" in result.output.lower() or "stash" in result.output.lower()
