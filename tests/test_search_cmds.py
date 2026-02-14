"""Tests for search commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestSearch:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["search", "test"])
            assert result.exit_code == 1

    def test_empty_results(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.search.regex_search", return_value=[]),
        ):
            result = runner.invoke(app, ["search", "nothing"])
            assert result.exit_code == 0
            assert "No results found" in result.output

    def test_regex_search_default(self):
        mock_conn = MagicMock()
        results = [
            {
                "id": "turn-001-uuid12",
                "session_id": "sess-001-uuid",
                "user_message": "hello world",
                "assistant_summary": "greeted user",
                "timestamp": "2025-01-01",
            }
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.search.regex_search", return_value=results) as mock_regex,
        ):
            result = runner.invoke(app, ["search", "hello"])
            assert result.exit_code == 0
            mock_regex.assert_called_once()
            assert "hello world" in result.output

    def test_fts_search(self):
        mock_conn = MagicMock()
        results = [
            {
                "id": "turn-002-uuid12",
                "session_id": "sess-002-uuid",
                "user_message": "fts result",
                "assistant_summary": "found it",
                "timestamp": "2025-01-01",
            }
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.search.fts_search", return_value=results) as mock_fts,
        ):
            result = runner.invoke(app, ["search", "query", "--fts"])
            assert result.exit_code == 0
            mock_fts.assert_called_once()

    def test_semantic_search(self):
        mock_conn = MagicMock()
        results = [
            {
                "id": "turn-003-uuid12",
                "session_id": "sess-003-uuid",
                "user_message": "semantic result",
                "assistant_summary": "found semantically",
                "timestamp": "2025-01-01",
            }
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.embedding.semantic_search", return_value=results) as mock_sem,
        ):
            result = runner.invoke(app, ["search", "meaning", "--semantic"])
            assert result.exit_code == 0
            mock_sem.assert_called_once()

    def test_semantic_import_error(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch(
                "entirecontext.core.embedding.semantic_search",
                side_effect=ImportError("no module"),
            ),
        ):
            result = runner.invoke(app, ["search", "test", "--semantic"])
            assert result.exit_code == 1
            assert "sentence-transformers" in result.output

    def test_global_search(self):
        results = [
            {
                "id": "turn-004-uuid12",
                "repo_name": "my-repo",
                "session_id": "sess-004-uuid",
                "user_message": "global result",
                "assistant_summary": "found globally",
                "timestamp": "2025-01-01",
            }
        ]
        with patch("entirecontext.core.cross_repo.cross_repo_search", return_value=results) as mock_cross:
            result = runner.invoke(app, ["search", "global query", "--global"])
            assert result.exit_code == 0
            mock_cross.assert_called_once()
            assert "my-repo" in result.output

    def test_session_target(self):
        mock_conn = MagicMock()
        results = [
            {
                "id": "sess-005-uuid",
                "session_title": "My Session",
                "session_summary": "A session about testing",
                "total_turns": 10,
            }
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.search.regex_search", return_value=results),
        ):
            result = runner.invoke(app, ["search", "testing", "-t", "session"])
            assert result.exit_code == 0
            assert "My Session" in result.output

    def test_event_target(self):
        mock_conn = MagicMock()
        results = [
            {
                "id": "evt-001-uuid12",
                "title": "Bug Fix",
                "description": "Fixed the login bug in auth module",
            }
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.search.regex_search", return_value=results),
        ):
            result = runner.invoke(app, ["search", "bug", "-t", "event"])
            assert result.exit_code == 0
            assert "Bug Fix" in result.output

    def test_content_target(self):
        mock_conn = MagicMock()
        results = [
            {
                "turn_id": "turn-006-uuid",
                "session_id": "sess-006-uuid",
                "content_path": "/data/content/001.jsonl",
                "repo_name": "",
            }
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.search.regex_search", return_value=results),
        ):
            result = runner.invoke(app, ["search", "data", "-t", "content"])
            assert result.exit_code == 0
            assert "001.jsonl" in result.output
