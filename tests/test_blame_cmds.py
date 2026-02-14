"""Tests for blame/attribution commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestBlameCommand:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["blame", "somefile.py"])
            assert result.exit_code == 1
            assert "Not in a git" in result.output

    def test_no_attribution_data(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.attribution.get_file_attributions", return_value=[]),
        ):
            result = runner.invoke(app, ["blame", "somefile.py"])
            assert result.exit_code == 0
            assert "No attribution data" in result.output

    def test_summary_mode(self):
        mock_conn = MagicMock()
        stats = {
            "total_lines": 100,
            "human_lines": 60,
            "human_pct": 60.0,
            "agent_lines": 40,
            "agent_pct": 40.0,
            "agents": {"claude": 40},
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.attribution.get_file_attribution_summary", return_value=stats),
        ):
            result = runner.invoke(app, ["blame", "somefile.py", "--summary"])
            assert result.exit_code == 0
            assert "Attribution Summary" in result.output
            assert "Human" in result.output
            assert "Agent" in result.output
            assert "claude" in result.output

    def test_summary_no_data(self):
        mock_conn = MagicMock()
        stats = {
            "total_lines": 0,
            "human_lines": 0,
            "human_pct": 0,
            "agent_lines": 0,
            "agent_pct": 0,
            "agents": {},
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.attribution.get_file_attribution_summary", return_value=stats),
        ):
            result = runner.invoke(app, ["blame", "somefile.py", "-s"])
            assert result.exit_code == 0
            assert "No attribution data" in result.output

    def test_line_range(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.attribution.get_file_attributions", return_value=[]) as mock_attr,
        ):
            runner.invoke(app, ["blame", "somefile.py", "-L", "10,20"])
            mock_attr.assert_called_once_with(mock_conn, "somefile.py", start_line=10, end_line=20)

    def test_single_line(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.attribution.get_file_attributions", return_value=[]) as mock_attr,
        ):
            runner.invoke(app, ["blame", "somefile.py", "-L", "15"])
            mock_attr.assert_called_once_with(mock_conn, "somefile.py", start_line=15, end_line=15)

    def test_normal_table_output(self):
        mock_conn = MagicMock()
        attributions = [
            {
                "start_line": 1,
                "end_line": 10,
                "attribution_type": "human",
                "agent_name": None,
                "session_id": None,
                "confidence": None,
            },
            {
                "start_line": 11,
                "end_line": 25,
                "attribution_type": "agent",
                "agent_name": "claude",
                "session_id": "abc123456789xyz",
                "confidence": 0.95,
            },
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.attribution.get_file_attributions", return_value=attributions),
        ):
            result = runner.invoke(app, ["blame", "somefile.py"])
            assert result.exit_code == 0
            assert "Attribution" in result.output
