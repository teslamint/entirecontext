"""E2E tests for cross-repo CLI commands."""

from __future__ import annotations


from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestSearchGlobal:
    def test_global_search_returns_both_repos(self, multi_ec_repos):
        result = runner.invoke(app, ["search", "auth", "--global"])
        assert result.exit_code == 0
        assert "frontend" in result.output
        assert "backend" in result.output

    def test_global_search_with_repo_filter(self, multi_ec_repos):
        result = runner.invoke(app, ["search", "auth", "-g", "-r", "frontend"])
        assert result.exit_code == 0
        assert "frontend" in result.output
        assert "backend" not in result.output

    def test_global_search_fts(self, multi_ec_repos):
        result = runner.invoke(app, ["search", "auth", "--global", "--fts"])
        assert result.exit_code == 0
        assert "frontend" in result.output
        assert "backend" in result.output

    def test_global_search_no_results(self, multi_ec_repos):
        result = runner.invoke(app, ["search", "zzz_nothing_zzz", "--global"])
        assert result.exit_code == 0
        assert "No results found" in result.output

    def test_repo_flag_without_global(self, multi_ec_repos):
        result = runner.invoke(app, ["search", "auth", "-r", "frontend"])
        assert result.exit_code == 0
        assert "frontend" in result.output

    def test_search_output_has_repo_column(self, multi_ec_repos):
        result = runner.invoke(app, ["search", "auth", "--global"])
        assert result.exit_code == 0
        assert "Repo" in result.output


class TestSessionListGlobal:
    def test_global_session_list(self, multi_ec_repos):
        result = runner.invoke(app, ["session", "list", "--global"])
        assert result.exit_code == 0
        assert "frontend" in result.output
        assert "backend" in result.output

    def test_global_session_list_with_repo(self, multi_ec_repos):
        result = runner.invoke(app, ["session", "list", "-g", "-r", "backend"])
        assert result.exit_code == 0
        assert "backend" in result.output
        assert "frontend" not in result.output

    def test_session_list_has_repo_column(self, multi_ec_repos):
        result = runner.invoke(app, ["session", "list", "--global"])
        assert result.exit_code == 0
        assert "Repo" in result.output


class TestRepoList:
    def test_repo_list(self, multi_ec_repos):
        result = runner.invoke(app, ["repo", "list"])
        assert result.exit_code == 0
        assert "frontend" in result.output
        assert "backend" in result.output

    def test_repo_list_shows_db_status(self, multi_ec_repos):
        result = runner.invoke(app, ["repo", "list"])
        assert result.exit_code == 0
        assert "✓" in result.output

    def test_repo_list_empty(self, isolated_global_db):
        result = runner.invoke(app, ["repo", "list"])
        assert result.exit_code == 0
        assert "No registered repositories" in result.output
