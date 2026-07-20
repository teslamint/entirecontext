"""Tests for blame/attribution commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.blame_decisions import BlameAnnotation

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


class TestBlameDecisionsFlag:
    def test_happy_single_annotation(self):
        mock_conn = MagicMock()
        annotation = BlameAnnotation(
            commit_sha="a" * 40,
            line_ranges=[(1, 5)],
            decision_id="dec-1",
            title="Use SQLite WAL mode",
            rationale_excerpt="Better concurrency.",
            rejected_count=0,
            staleness_status="fresh",
        )
        annotate_result = {
            "annotations": [annotation],
            "unlinked_ranges": [(6, 9)],
            "uncommitted_ranges": [],
            "annotated_sha_count": 1,
            "total_sha_count": 2,
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.attribution.get_file_attributions", return_value=[]),
            patch("entirecontext.core.blame_decisions.annotate_file", return_value=annotate_result),
        ):
            result = runner.invoke(app, ["blame", "somefile.py", "--decisions"])
            assert result.exit_code == 0
            assert "a" * 8 in result.output
            assert "Use SQLite WAL mode" in result.output
            assert "lines 1-5" in result.output
            assert "lines 6-9: no recorded decision" in result.output
            assert "absence of links" in result.output
            assert "decisions were made" in result.output

    def test_stale_annotation_shows_reverify(self):
        mock_conn = MagicMock()
        annotation = BlameAnnotation(
            commit_sha="b" * 40,
            line_ranges=[(1, 5)],
            decision_id="dec-2",
            title="Old decision",
            rationale_excerpt="Rationale.",
            rejected_count=0,
            staleness_status="superseded",
        )
        annotate_result = {
            "annotations": [annotation],
            "uncommitted_ranges": [],
            "annotated_sha_count": 1,
            "total_sha_count": 1,
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.attribution.get_file_attributions", return_value=[]),
            patch("entirecontext.core.blame_decisions.annotate_file", return_value=annotate_result),
        ):
            result = runner.invoke(app, ["blame", "somefile.py", "--decisions"])
            assert result.exit_code == 0
            assert "[STALE:superseded]" in result.output
            assert "ec decision get dec-2" in result.output

    def test_empty_state_message(self):
        mock_conn = MagicMock()
        annotate_result = {
            "annotations": [],
            "uncommitted_ranges": [],
            "annotated_sha_count": 0,
            "total_sha_count": 0,
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.attribution.get_file_attributions", return_value=[]),
            patch("entirecontext.core.blame_decisions.annotate_file", return_value=annotate_result),
        ):
            result = runner.invoke(app, ["blame", "somefile.py", "--decisions"])
            assert result.exit_code == 0
            assert "No recorded decisions for this file's commits" in result.output

    def test_uncommitted_ranges_rendered(self):
        mock_conn = MagicMock()
        annotate_result = {
            "annotations": [],
            "uncommitted_ranges": [(10, 15)],
            "annotated_sha_count": 0,
            "total_sha_count": 0,
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.attribution.get_file_attributions", return_value=[]),
            patch("entirecontext.core.blame_decisions.annotate_file", return_value=annotate_result),
        ):
            result = runner.invoke(app, ["blame", "somefile.py", "--decisions"])
            assert result.exit_code == 0
            assert "lines 10-15: uncommitted (no blame history yet)" in result.output

    def test_summary_and_decisions_mutually_exclusive(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.blame_decisions.annotate_file") as mock_annotate,
        ):
            result = runner.invoke(app, ["blame", "somefile.py", "--summary", "--decisions"])
            assert result.exit_code == 1
            assert "mutually exclusive" in result.output
            mock_annotate.assert_not_called()

    def test_annotate_file_value_error(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.attribution.get_file_attributions", return_value=[]),
            patch(
                "entirecontext.core.blame_decisions.annotate_file",
                side_effect=ValueError("no such path"),
            ),
        ):
            result = runner.invoke(app, ["blame", "somefile.py", "--decisions"])
            assert result.exit_code == 1
            assert "no such path" in result.output
