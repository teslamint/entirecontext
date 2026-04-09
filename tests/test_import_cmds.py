from __future__ import annotations

from unittest.mock import MagicMock

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.import_aline import ImportResult

runner = CliRunner()


class TestImportCmds:
    def test_import_no_source(self):
        result = runner.invoke(app, ["import"])
        assert result.exit_code == 1
        assert "Specify an import source" in result.output

    def test_import_not_in_repo(self, monkeypatch):
        monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda: None)
        result = runner.invoke(app, ["import", "--from-aline", "/tmp/fake.db"])
        assert result.exit_code == 1
        assert "Not in a git repository" in result.output

    def test_import_not_initialized(self, tmp_path, monkeypatch):
        monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda: str(tmp_path))
        monkeypatch.setattr("entirecontext.core.project.get_project", lambda repo_path: None)
        result = runner.invoke(app, ["import", "--from-aline", "/tmp/fake.db"])
        assert result.exit_code == 1
        assert "Not initialized" in result.output

    def test_import_dry_run(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        mock_result = ImportResult(sessions=3, turns=10, turn_content=5, checkpoints=2, events=1, event_links=1)
        monkeypatch.setattr("entirecontext.core.import_aline.import_from_aline", lambda **kwargs: mock_result)

        result = runner.invoke(app, ["import", "--from-aline", "/tmp/fake.db", "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run mode" in result.output
        assert "Would import" in result.output
        assert "3 sessions" in result.output
        assert "10 turns" in result.output

    def test_import_success(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        mock_result = ImportResult(sessions=2, turns=5, turn_content=3, checkpoints=1, events=1, event_links=1)
        monkeypatch.setattr("entirecontext.core.import_aline.import_from_aline", lambda **kwargs: mock_result)
        monkeypatch.setattr("entirecontext.core.indexing.rebuild_fts_indexes", lambda conn: None)

        result = runner.invoke(app, ["import", "--from-aline", "/tmp/fake.db"])
        assert result.exit_code == 0
        assert "Imported 2 sessions" in result.output
        assert "Imported 5 turns" in result.output
        assert "Import complete" in result.output

    def test_import_with_errors(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        mock_result = ImportResult(sessions=1, turns=2, errors=["error1", "error2"])
        monkeypatch.setattr("entirecontext.core.import_aline.import_from_aline", lambda **kwargs: mock_result)

        result = runner.invoke(app, ["import", "--from-aline", "/tmp/fake.db"])
        assert result.exit_code == 1
        assert "Errors (2)" in result.output
        assert "error1" in result.output
        assert "error2" in result.output

    def test_import_fts_rebuild_called(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        mock_result = ImportResult(sessions=1, turns=1)
        monkeypatch.setattr("entirecontext.core.import_aline.import_from_aline", lambda **kwargs: mock_result)
        rebuild_mock = MagicMock()
        monkeypatch.setattr("entirecontext.core.indexing.rebuild_fts_indexes", rebuild_mock)

        result = runner.invoke(app, ["import", "--from-aline", "/tmp/fake.db"])
        assert result.exit_code == 0
        rebuild_mock.assert_called_once()
        assert "FTS indexes rebuilt" in result.output

    def test_import_fts_rebuild_exception_ignored(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        mock_result = ImportResult(sessions=1, turns=1)
        monkeypatch.setattr("entirecontext.core.import_aline.import_from_aline", lambda **kwargs: mock_result)
        monkeypatch.setattr(
            "entirecontext.core.indexing.rebuild_fts_indexes",
            MagicMock(side_effect=Exception("FTS rebuild failed")),
        )

        result = runner.invoke(app, ["import", "--from-aline", "/tmp/fake.db"])
        assert result.exit_code == 0
        assert "Import complete" in result.output
        assert "FTS indexes rebuilt" not in result.output
