"""Tests for CLI commands using Typer's CliRunner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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

    @staticmethod
    def _status(**overrides):
        project = {"id": "abc12345-uuid", "name": "myproject", "repo_path": "/tmp/test"}
        status = {
            "initialized": True,
            "project": project,
            "logical_project": {**project, "git_common_dir": "/tmp/test/.git"},
            "workspace": {
                "root": "/tmp/wt",
                "branch": "feature",
                "worktree_git_dir": "/tmp/test/.git/worktrees/wt",
                "is_linked": True,
            },
            "session_count": 5,
            "workspace_session_count": 2,
            "turn_count": 42,
            "checkpoint_count": 10,
            "active_session": None,
            "legacy_worktree_db": None,
        }
        status.update(overrides)
        return status

    @patch("entirecontext.core.project.get_status")
    def test_status_initialized(self, mock_status):
        mock_status.return_value = self._status()
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "myproject" in result.output
        assert "Logical project" in result.output
        assert "Active workspace" in result.output
        assert "/tmp/wt (linked worktree)" in result.output
        assert "feature" in result.output
        assert "Workspace sessions" in result.output

    @patch("entirecontext.core.project.get_status")
    def test_status_warns_about_legacy_worktree_db(self, mock_status):
        mock_status.return_value = self._status(
            legacy_worktree_db={"path": "/tmp/wt/.entirecontext/db/local.db", "session_count": 3, "decision_count": 1}
        )
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        output = " ".join(result.output.split())
        assert "Legacy per-worktree database found at /tmp/wt/.entirecontext/db/local.db" in output
        assert "3 sessions, 1 decisions" in output
        assert "verify-docs --promote-from" in output


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

    def test_search_semantic_calls_semantic_search(self):
        mock_conn = MagicMock()
        with patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"):
            with patch("entirecontext.db.get_db", return_value=mock_conn):
                with patch(
                    "entirecontext.core.embedding.semantic_search",
                    return_value=[
                        {
                            "id": "t1",
                            "source_type": "turn",
                            "session_id": "s1",
                            "user_message": "test query",
                            "assistant_summary": "result",
                            "timestamp": "2025-01-01",
                            "score": 0.95,
                        }
                    ],
                ) as mock_sem:
                    result = runner.invoke(app, ["search", "test query", "--semantic"])
                    assert result.exit_code == 0
                    mock_sem.assert_called_once()

    def test_search_semantic_import_error_message(self):
        mock_conn = MagicMock()
        with patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"):
            with patch("entirecontext.db.get_db", return_value=mock_conn):
                with patch(
                    "entirecontext.core.embedding.semantic_search",
                    side_effect=ImportError("sentence-transformers is required"),
                ):
                    result = runner.invoke(app, ["search", "test", "--semantic"])
                    assert result.exit_code == 1
                    assert "sentence-transformers" in result.output


class TestCheckpointCommands:
    def test_checkpoint_list_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["checkpoint", "list"])
            assert result.exit_code != 0

    def test_sync_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["sync"])
            assert result.exit_code != 0

    def test_pull_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["pull"])
            assert result.exit_code != 0

    def test_rewind_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["rewind", "some-id"])
            assert result.exit_code != 0


class TestContextCommands:
    def test_context_select_and_apply(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session
        from entirecontext.core.telemetry import record_retrieval_event
        from entirecontext.core.turn import create_turn

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="ctx-cli-session")
        turn = create_turn(ec_db, session["id"], 1, user_message="search auth", assistant_summary="results")
        event = record_retrieval_event(
            ec_db,
            source="cli",
            search_type="regex",
            target="turn",
            query="auth",
            result_count=1,
            latency_ms=5,
            session_id=session["id"],
            turn_id=turn["id"],
        )

        monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda *a, **kw: str(ec_repo))
        select_result = runner.invoke(app, ["context", "select", event["id"], "turn", "turn-source", "--rank", "1"])
        assert select_result.exit_code == 0
        assert "Selection ID:" in select_result.output
        selection_id = select_result.output.strip().split(": ", 1)[1]

        apply_result = runner.invoke(app, ["context", "apply", "reference", "--selection-id", selection_id])
        assert apply_result.exit_code == 0
        assert "Application ID:" in apply_result.output


class TestRewindSafety:
    def test_rewind_restore_dirty_tree(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.core.checkpoint import create_checkpoint
        from entirecontext.core.session import create_session

        project_row = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()
        create_session(ec_db, project_row["id"], session_id="rw-s1")
        create_checkpoint(ec_db, "rw-s1", "abc123", checkpoint_id="rw-cp1")

        monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda *a, **kw: str(ec_repo))

        dirty_file = ec_repo / "dirty.txt"
        dirty_file.write_text("uncommitted")

        result = runner.invoke(app, ["rewind", "rw-cp1", "--restore"])
        assert result.exit_code == 1
        assert "uncommitted" in result.output.lower() or "stash" in result.output.lower()
