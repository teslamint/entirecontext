"""Tests for index management commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestIndexCommand:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["index"])
            assert result.exit_code == 1

    def test_fts_rebuild_only(self):
        mock_conn = MagicMock()
        counts = {"fts_turns": 42, "fts_sessions": 5}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.indexing.rebuild_fts_indexes", return_value=counts),
        ):
            result = runner.invoke(app, ["index"])
            assert result.exit_code == 0
            assert "FTS indexes rebuilt" in result.output
            assert "fts_turns" in result.output
            assert "42" in result.output

    def test_semantic_embeddings(self):
        mock_conn = MagicMock()
        counts = {"fts_turns": 10}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.indexing.rebuild_fts_indexes", return_value=counts),
            patch("entirecontext.core.indexing.generate_embeddings", return_value=25) as mock_gen,
        ):
            result = runner.invoke(app, ["index", "--semantic"])
            assert result.exit_code == 0
            assert "Generated 25 embeddings" in result.output
            mock_gen.assert_called_once_with(mock_conn, "/tmp/test", model_name="all-MiniLM-L6-v2", force=False)

    def test_semantic_import_error(self):
        mock_conn = MagicMock()
        counts = {"fts_turns": 10}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.indexing.rebuild_fts_indexes", return_value=counts),
            patch(
                "entirecontext.core.indexing.generate_embeddings",
                side_effect=ImportError("sentence-transformers is required"),
            ),
        ):
            result = runner.invoke(app, ["index", "--semantic"])
            assert result.exit_code == 1
            assert "sentence-transformers" in result.output

    def test_force_flag(self):
        mock_conn = MagicMock()
        counts = {"fts_turns": 10}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.indexing.rebuild_fts_indexes", return_value=counts),
            patch("entirecontext.core.indexing.generate_embeddings", return_value=50) as mock_gen,
        ):
            result = runner.invoke(app, ["index", "--semantic", "--force"])
            assert result.exit_code == 0
            mock_gen.assert_called_once_with(mock_conn, "/tmp/test", model_name="all-MiniLM-L6-v2", force=True)

    def test_custom_model(self):
        mock_conn = MagicMock()
        counts = {"fts_turns": 10}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.indexing.rebuild_fts_indexes", return_value=counts),
            patch("entirecontext.core.indexing.generate_embeddings", return_value=10) as mock_gen,
        ):
            result = runner.invoke(app, ["index", "--semantic", "--model", "custom-model"])
            assert result.exit_code == 0
            mock_gen.assert_called_once_with(mock_conn, "/tmp/test", model_name="custom-model", force=False)
