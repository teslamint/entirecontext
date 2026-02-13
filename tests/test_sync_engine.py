"""Tests for sync engine — perform_sync and perform_pull."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from entirecontext.sync.engine import perform_sync, perform_pull


@pytest.fixture
def sync_db(ec_db):
    ec_db.execute("INSERT OR REPLACE INTO sync_metadata (id, sync_status) VALUES (1, 'idle')")
    ec_db.commit()
    return ec_db


def _make_run_side_effect(worktree_path, has_changes=True):
    def side_effect(args, **kwargs):
        kwargs.get("cwd", "")
        result = MagicMock(returncode=0, stdout="", stderr="")

        if args[:3] == ["git", "worktree", "add"]:
            Path(worktree_path).mkdir(parents=True, exist_ok=True)
            (Path(worktree_path) / "sessions").mkdir(exist_ok=True)
            (Path(worktree_path) / "checkpoints").mkdir(exist_ok=True)

        if args[:3] == ["git", "status", "--porcelain"]:
            result.stdout = "M manifest.json\n" if has_changes else ""

        return result

    return side_effect


class TestPerformSync:
    def test_success_path(self, sync_db, ec_repo, tmp_path):
        worktree = str(tmp_path / "worktree")
        config = {"push_on_sync": False}

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=_make_run_side_effect(worktree)),
            patch("entirecontext.sync.engine.tempfile.mkdtemp", return_value=worktree),
            patch("entirecontext.sync.engine.export_sessions", return_value=2),
            patch("entirecontext.sync.engine.export_checkpoints", return_value=1),
            patch("entirecontext.sync.engine.update_manifest"),
        ):
            result = perform_sync(sync_db, str(ec_repo), config)

        assert result["error"] is None
        assert result["exported_sessions"] == 2
        assert result["exported_checkpoints"] == 1
        assert result["committed"] is True
        assert result["duration_ms"] >= 0

    def test_no_changes(self, sync_db, ec_repo, tmp_path):
        worktree = str(tmp_path / "worktree")
        config = {"push_on_sync": False}

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch(
                "entirecontext.sync.engine.subprocess.run",
                side_effect=_make_run_side_effect(worktree, has_changes=False),
            ),
            patch("entirecontext.sync.engine.tempfile.mkdtemp", return_value=worktree),
            patch("entirecontext.sync.engine.export_sessions", return_value=0),
            patch("entirecontext.sync.engine.export_checkpoints", return_value=0),
            patch("entirecontext.sync.engine.update_manifest"),
        ):
            result = perform_sync(sync_db, str(ec_repo), config)

        assert result["error"] is None
        assert result["exported_sessions"] == 0
        assert result["exported_checkpoints"] == 0
        assert result["committed"] is False

    def test_error_handling(self, sync_db, ec_repo, tmp_path):
        worktree = str(tmp_path / "worktree")

        def fail_on_worktree_add(args, **kwargs):
            if args[:3] == ["git", "worktree", "add"]:
                raise subprocess.CalledProcessError(1, args, stderr="worktree failed")
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=fail_on_worktree_add),
            patch("entirecontext.sync.engine.tempfile.mkdtemp", return_value=worktree),
        ):
            result = perform_sync(sync_db, str(ec_repo), {})

        assert result["error"] is not None

    def test_updates_sync_metadata(self, sync_db, ec_repo, tmp_path):
        worktree = str(tmp_path / "worktree")
        config = {"push_on_sync": False}

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=_make_run_side_effect(worktree)),
            patch("entirecontext.sync.engine.tempfile.mkdtemp", return_value=worktree),
            patch("entirecontext.sync.engine.export_sessions", return_value=1),
            patch("entirecontext.sync.engine.export_checkpoints", return_value=0),
            patch("entirecontext.sync.engine.update_manifest"),
        ):
            perform_sync(sync_db, str(ec_repo), config)

        row = sync_db.execute("SELECT last_export_at, last_sync_duration_ms FROM sync_metadata WHERE id = 1").fetchone()
        assert row["last_export_at"] is not None
        assert row["last_sync_duration_ms"] is not None

    def test_inits_shadow_branch_if_missing(self, sync_db, ec_repo, tmp_path):
        worktree = str(tmp_path / "worktree")
        config = {"push_on_sync": False}

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=False),
            patch("entirecontext.sync.engine.init_shadow_branch") as mock_init,
            patch(
                "entirecontext.sync.engine.subprocess.run",
                side_effect=_make_run_side_effect(worktree, has_changes=False),
            ),
            patch("entirecontext.sync.engine.tempfile.mkdtemp", return_value=worktree),
            patch("entirecontext.sync.engine.export_sessions", return_value=0),
            patch("entirecontext.sync.engine.export_checkpoints", return_value=0),
            patch("entirecontext.sync.engine.update_manifest"),
        ):
            perform_sync(sync_db, str(ec_repo), config)

        mock_init.assert_called_once_with(str(ec_repo))

    def test_push_on_sync(self, sync_db, ec_repo, tmp_path):
        worktree = str(tmp_path / "worktree")
        config = {"push_on_sync": True}
        calls_log = []

        def tracking_side_effect(args, **kwargs):
            calls_log.append(args)
            kwargs.get("cwd", "")
            result = MagicMock(returncode=0, stdout="", stderr="")

            if args[:3] == ["git", "worktree", "add"]:
                Path(worktree).mkdir(parents=True, exist_ok=True)
                (Path(worktree) / "sessions").mkdir(exist_ok=True)
                (Path(worktree) / "checkpoints").mkdir(exist_ok=True)

            if args[:3] == ["git", "status", "--porcelain"]:
                result.stdout = "M manifest.json\n"

            return result

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=tracking_side_effect),
            patch("entirecontext.sync.engine.tempfile.mkdtemp", return_value=worktree),
            patch("entirecontext.sync.engine.export_sessions", return_value=1),
            patch("entirecontext.sync.engine.export_checkpoints", return_value=0),
            patch("entirecontext.sync.engine.update_manifest"),
        ):
            result = perform_sync(sync_db, str(ec_repo), config)

        push_calls = [c for c in calls_log if c[:2] == ["git", "push"]]
        assert len(push_calls) == 1
        assert result["pushed"] is True


class TestPerformPull:
    def test_error_when_no_shadow_branch(self, sync_db, ec_repo):
        with patch("entirecontext.sync.engine.shadow_branch_exists", return_value=False):
            result = perform_pull(sync_db, str(ec_repo), {})
        assert result["error"] == "no_shadow_branch"

    def test_success_imports_sessions_and_checkpoints(self, sync_db, ec_repo, tmp_path):
        worktree = str(tmp_path / "worktree")

        project_row = sync_db.execute("SELECT id FROM projects LIMIT 1").fetchone()
        project_id = project_row["id"]

        session_meta = {
            "id": "imported-session-1",
            "project_id": project_id,
            "session_type": "claude",
        }
        checkpoint_data = {
            "id": "imported-cp-1",
            "session_id": "imported-session-1",
            "git_commit_hash": "abc123",
            "git_branch": "main",
        }

        def setup_worktree(args, **kwargs):
            result = MagicMock(returncode=0, stdout="", stderr="")
            if args[:3] == ["git", "worktree", "add"]:
                Path(worktree).mkdir(parents=True, exist_ok=True)
                sessions_dir = Path(worktree) / "sessions" / "imported-session-1"
                sessions_dir.mkdir(parents=True, exist_ok=True)
                (sessions_dir / "meta.json").write_text(json.dumps(session_meta))

                cp_dir = Path(worktree) / "checkpoints"
                cp_dir.mkdir(parents=True, exist_ok=True)
                (cp_dir / "imported-cp-1.json").write_text(json.dumps(checkpoint_data))
            return result

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=setup_worktree),
            patch("entirecontext.sync.engine.tempfile.mkdtemp", return_value=worktree),
        ):
            result = perform_pull(sync_db, str(ec_repo), {})

        assert result["error"] is None
        assert result["imported_sessions"] == 1
        assert result["imported_checkpoints"] == 1

        session = sync_db.execute("SELECT * FROM sessions WHERE id = 'imported-session-1'").fetchone()
        assert session is not None

        cp = sync_db.execute("SELECT * FROM checkpoints WHERE id = 'imported-cp-1'").fetchone()
        assert cp is not None
        assert cp["git_commit_hash"] == "abc123"

    def test_updates_last_import_at(self, sync_db, ec_repo, tmp_path):
        worktree = str(tmp_path / "worktree")

        def setup_worktree(args, **kwargs):
            result = MagicMock(returncode=0, stdout="", stderr="")
            if args[:3] == ["git", "worktree", "add"]:
                Path(worktree).mkdir(parents=True, exist_ok=True)
            return result

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=setup_worktree),
            patch("entirecontext.sync.engine.tempfile.mkdtemp", return_value=worktree),
        ):
            perform_pull(sync_db, str(ec_repo), {})

        row = sync_db.execute("SELECT last_import_at FROM sync_metadata WHERE id = 1").fetchone()
        assert row["last_import_at"] is not None

    def test_skips_existing_sessions(self, sync_db, ec_repo, tmp_path):
        from entirecontext.core.session import create_session

        project_row = sync_db.execute("SELECT id FROM projects LIMIT 1").fetchone()
        project_id = project_row["id"]
        create_session(sync_db, project_id, session_id="existing-session")

        worktree = str(tmp_path / "worktree")
        session_meta = {
            "id": "existing-session",
            "project_id": project_id,
            "session_type": "claude",
        }

        def setup_worktree(args, **kwargs):
            result = MagicMock(returncode=0, stdout="", stderr="")
            if args[:3] == ["git", "worktree", "add"]:
                Path(worktree).mkdir(parents=True, exist_ok=True)
                sessions_dir = Path(worktree) / "sessions" / "existing-session"
                sessions_dir.mkdir(parents=True, exist_ok=True)
                (sessions_dir / "meta.json").write_text(json.dumps(session_meta))
            return result

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=setup_worktree),
            patch("entirecontext.sync.engine.tempfile.mkdtemp", return_value=worktree),
        ):
            result = perform_pull(sync_db, str(ec_repo), {})

        assert result["imported_sessions"] == 0

    def test_error_on_worktree_failure(self, sync_db, ec_repo, tmp_path):
        worktree = str(tmp_path / "worktree")

        def fail_worktree(args, **kwargs):
            if args[:3] == ["git", "worktree", "add"]:
                raise subprocess.CalledProcessError(1, args, stderr="worktree error")
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=fail_worktree),
            patch("entirecontext.sync.engine.tempfile.mkdtemp", return_value=worktree),
        ):
            result = perform_pull(sync_db, str(ec_repo), {})

        assert result["error"] is not None
