"""Tests for sync engine — perform_sync and perform_pull."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from entirecontext.sync.engine import REMOTE_SHADOW_REF, SHADOW_BRANCH, perform_pull, perform_sync


@pytest.fixture
def sync_db(ec_db):
    ec_db.execute("INSERT OR REPLACE INTO sync_metadata (id, sync_status) VALUES (1, 'idle')")
    ec_db.commit()
    return ec_db


def _cp(*, returncode=0, stdout="", stderr=""):
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def _copy_tree(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            target.write_text(item.read_text(encoding="utf-8"), encoding="utf-8")


def _write_snapshot(
    root: Path,
    *,
    session_id: str | None = None,
    session_meta: dict | None = None,
    transcript_entries: list[dict] | None = None,
    checkpoints: dict[str, dict] | None = None,
    manifest: dict | None = None,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "sessions").mkdir(exist_ok=True)
    (root / "checkpoints").mkdir(exist_ok=True)

    if session_id and session_meta is not None:
        session_dir = root / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "meta.json").write_text(json.dumps(session_meta, indent=2), encoding="utf-8")
        transcript_lines = []
        for entry in transcript_entries or []:
            transcript_lines.append(json.dumps(entry))
        (session_dir / "transcript.jsonl").write_text(
            "\n".join(transcript_lines) + ("\n" if transcript_lines else ""),
            encoding="utf-8",
        )

    for checkpoint_id, checkpoint_data in (checkpoints or {}).items():
        (root / "checkpoints" / f"{checkpoint_id}.json").write_text(json.dumps(checkpoint_data, indent=2), encoding="utf-8")

    if manifest is not None:
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _mk_subprocess_side_effect(
    *,
    remote_fixture: Path | None = None,
    stale_fixture: Path | None = None,
    status_outputs: list[str] | None = None,
    push_results: list[MagicMock] | None = None,
) -> tuple[callable, dict]:
    state = {
        "branch_worktree": None,
        "remote_ref_exists": remote_fixture is not None,
        "commands": [],
    }
    status_queue = list(status_outputs or [])
    push_queue = list(push_results or [])

    def side_effect(args, **kwargs):
        cwd = kwargs.get("cwd", "")
        state["commands"].append((args, cwd))

        if args[:3] == ["git", "worktree", "add"]:
            if "--detach" in args:
                worktree_path = Path(args[4])
                ref = args[5]
            else:
                worktree_path = Path(args[3])
                ref = args[4]

            if worktree_path.exists():
                shutil.rmtree(worktree_path)
            worktree_path.mkdir(parents=True, exist_ok=True)
            (worktree_path / "sessions").mkdir(exist_ok=True)
            (worktree_path / "checkpoints").mkdir(exist_ok=True)

            if ref == SHADOW_BRANCH:
                state["branch_worktree"] = worktree_path
            elif ref == "HEAD" and state["branch_worktree"] is not None:
                _copy_tree(state["branch_worktree"], worktree_path)
            elif ref == REMOTE_SHADOW_REF and remote_fixture is not None:
                _copy_tree(remote_fixture, worktree_path)
            elif ref == SHADOW_BRANCH and stale_fixture is not None:
                _copy_tree(stale_fixture, worktree_path)

            return _cp()

        if args[:3] == ["git", "status", "--porcelain"]:
            return _cp(stdout=status_queue.pop(0) if status_queue else "")

        if args[:2] == ["git", "push"]:
            return push_queue.pop(0) if push_queue else _cp()

        if args[:2] == ["git", "fetch"]:
            state["remote_ref_exists"] = remote_fixture is not None
            return _cp()

        if args[:3] == ["git", "rev-parse", "--verify"] and args[3] == f"refs/remotes/{REMOTE_SHADOW_REF}":
            return _cp(returncode=0 if state["remote_ref_exists"] else 1)

        if args[:3] == ["git", "reset", "--hard"]:
            worktree_path = Path(cwd)
            shutil.rmtree(worktree_path)
            worktree_path.mkdir(parents=True, exist_ok=True)
            (worktree_path / "sessions").mkdir(exist_ok=True)
            (worktree_path / "checkpoints").mkdir(exist_ok=True)
            return _cp()

        return _cp()

    return side_effect, state


class TestPerformSync:
    def test_success_path(self, sync_db, ec_repo):
        config = {"push_on_sync": False}
        side_effect, _state = _mk_subprocess_side_effect(status_outputs=["M manifest.json\n"])

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=side_effect),
            patch("entirecontext.sync.engine.export_sessions", return_value=2),
            patch("entirecontext.sync.engine.export_checkpoints", return_value=1),
            patch("entirecontext.sync.engine.update_manifest"),
        ):
            result = perform_sync(sync_db, str(ec_repo), config)

        assert result["error"] is None
        assert result["exported_sessions"] == 2
        assert result["exported_checkpoints"] == 1
        assert result["committed"] is True
        assert result["merge_applied"] is False
        assert result["retry_count"] == 0
        assert result["duration_ms"] >= 0

    def test_no_changes(self, sync_db, ec_repo):
        config = {"push_on_sync": False}
        side_effect, _state = _mk_subprocess_side_effect(status_outputs=[""])

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=side_effect),
            patch("entirecontext.sync.engine.export_sessions", return_value=0),
            patch("entirecontext.sync.engine.export_checkpoints", return_value=0),
            patch("entirecontext.sync.engine.update_manifest"),
        ):
            result = perform_sync(sync_db, str(ec_repo), config)

        assert result["error"] is None
        assert result["exported_sessions"] == 0
        assert result["exported_checkpoints"] == 0
        assert result["committed"] is False
        assert result["merge_applied"] is False
        assert result["retry_count"] == 0

    def test_error_handling(self, sync_db, ec_repo):
        def fail_on_worktree_add(args, **kwargs):
            if args[:3] == ["git", "worktree", "add"]:
                raise subprocess.CalledProcessError(1, args, stderr="worktree failed")
            return _cp()

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=fail_on_worktree_add),
        ):
            result = perform_sync(sync_db, str(ec_repo), {})

        assert result["error"] == "worktree failed"

    def test_updates_sync_metadata(self, sync_db, ec_repo):
        config = {"push_on_sync": False}
        side_effect, _state = _mk_subprocess_side_effect(status_outputs=["M manifest.json\n"])

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=side_effect),
            patch("entirecontext.sync.engine.export_sessions", return_value=1),
            patch("entirecontext.sync.engine.export_checkpoints", return_value=0),
            patch("entirecontext.sync.engine.update_manifest"),
        ):
            perform_sync(sync_db, str(ec_repo), config)

        row = sync_db.execute("SELECT last_export_at, last_sync_duration_ms FROM sync_metadata WHERE id = 1").fetchone()
        assert row["last_export_at"] is not None
        assert row["last_sync_duration_ms"] is not None

    def test_inits_shadow_branch_if_missing(self, sync_db, ec_repo):
        config = {"push_on_sync": False}
        side_effect, _state = _mk_subprocess_side_effect(status_outputs=[""])

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=False),
            patch("entirecontext.sync.engine.init_shadow_branch") as mock_init,
            patch("entirecontext.sync.engine.subprocess.run", side_effect=side_effect),
            patch("entirecontext.sync.engine.export_sessions", return_value=0),
            patch("entirecontext.sync.engine.export_checkpoints", return_value=0),
            patch("entirecontext.sync.engine.update_manifest"),
        ):
            perform_sync(sync_db, str(ec_repo), config)

        mock_init.assert_called_once_with(str(ec_repo))

    def test_push_non_fast_forward_merges_and_retries(self, sync_db, ec_repo, tmp_path):
        remote_fixture = tmp_path / "remote-shadow"
        _write_snapshot(
            remote_fixture,
            session_id="shared-session",
            session_meta={
                "id": "shared-session",
                "session_type": "claude",
                "started_at": "2026-03-06T11:00:00+00:00",
                "ended_at": "2026-03-06T12:00:00+00:00",
                "session_summary": "remote",
                "total_turns": 1,
            },
            transcript_entries=[{"id": "t0", "turn_number": 0}, {"id": "t1", "turn_number": 1}],
            checkpoints={
                "remote-cp": {
                    "id": "remote-cp",
                    "session_id": "shared-session",
                    "git_commit_hash": "remote123",
                }
            },
            manifest={
                "version": 1,
                "sessions": {
                    "shared-session": {
                        "session_type": "claude",
                        "started_at": "2026-03-06T11:00:00+00:00",
                        "total_turns": 1,
                    }
                },
                "checkpoints": {
                    "remote-cp": {
                        "session_id": "shared-session",
                        "commit_hash": "remote123",
                    }
                },
            },
        )

        side_effect, state = _mk_subprocess_side_effect(
            remote_fixture=remote_fixture,
            status_outputs=["M manifest.json\n", "M manifest.json\n"],
            push_results=[
                _cp(returncode=1, stderr="! [rejected] shadow -> shadow (non-fast-forward)"),
                _cp(returncode=0),
            ],
        )

        def export_sessions_stub(conn, repo_path, worktree_path, **kwargs):
            _write_snapshot(
                Path(worktree_path),
                session_id="shared-session",
                session_meta={
                    "id": "shared-session",
                    "session_type": "claude",
                    "started_at": "2026-03-06T12:00:00+00:00",
                    "ended_at": "2026-03-06T13:00:00+00:00",
                    "session_summary": None,
                    "total_turns": 2,
                },
                transcript_entries=[{"id": "t1", "turn_number": 1}, {"id": "t2", "turn_number": 2}],
            )
            return 1

        def export_checkpoints_stub(conn, worktree_path, **kwargs):
            _write_snapshot(
                Path(worktree_path),
                checkpoints={
                    "local-cp": {
                        "id": "local-cp",
                        "session_id": "shared-session",
                        "git_commit_hash": "local123",
                    }
                },
            )
            return 1

        def update_manifest_stub(conn, worktree_path):
            manifest = {
                "version": 1,
                "sessions": {
                    "shared-session": {
                        "session_type": "claude",
                        "started_at": "2026-03-06T12:00:00+00:00",
                        "total_turns": 2,
                    }
                },
                "checkpoints": {
                    "local-cp": {
                        "session_id": "shared-session",
                        "commit_hash": "local123",
                    }
                },
            }
            (Path(worktree_path) / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=side_effect),
            patch("entirecontext.sync.engine.export_sessions", side_effect=export_sessions_stub),
            patch("entirecontext.sync.engine.export_checkpoints", side_effect=export_checkpoints_stub),
            patch("entirecontext.sync.engine.update_manifest", side_effect=update_manifest_stub),
        ):
            result = perform_sync(sync_db, str(ec_repo), {"push_on_sync": True})

        branch_worktree = state["branch_worktree"]
        merged_meta = json.loads((branch_worktree / "sessions" / "shared-session" / "meta.json").read_text(encoding="utf-8"))
        merged_manifest = json.loads((branch_worktree / "manifest.json").read_text(encoding="utf-8"))
        transcript_lines = (branch_worktree / "sessions" / "shared-session" / "transcript.jsonl").read_text(
            encoding="utf-8"
        ).strip().splitlines()
        transcript_ids = [json.loads(line)["id"] for line in transcript_lines]

        assert result["error"] is None
        assert result["pushed"] is True
        assert result["merge_applied"] is True
        assert result["retry_count"] == 1
        assert merged_meta["total_turns"] == 2
        assert merged_meta["started_at"] == "2026-03-06T11:00:00+00:00"
        assert merged_meta["ended_at"] == "2026-03-06T13:00:00+00:00"
        assert set(merged_manifest["checkpoints"]) == {"local-cp", "remote-cp"}
        assert transcript_ids == ["t1", "t2", "t0"]

    def test_retry_push_failure_returns_error(self, sync_db, ec_repo, tmp_path):
        remote_fixture = tmp_path / "remote-shadow"
        _write_snapshot(
            remote_fixture,
            session_id="shared-session",
            session_meta={"id": "shared-session", "total_turns": 1},
            transcript_entries=[{"id": "t1"}],
            manifest={"version": 1, "sessions": {"shared-session": {"total_turns": 1}}, "checkpoints": {}},
        )

        side_effect, _state = _mk_subprocess_side_effect(
            remote_fixture=remote_fixture,
            status_outputs=["M manifest.json\n", "M manifest.json\n"],
            push_results=[
                _cp(returncode=1, stderr="non-fast-forward"),
                _cp(returncode=1, stderr="still rejected"),
            ],
        )

        def export_sessions_stub(conn, repo_path, worktree_path, **kwargs):
            _write_snapshot(
                Path(worktree_path),
                session_id="shared-session",
                session_meta={"id": "shared-session", "total_turns": 2},
                transcript_entries=[{"id": "t2"}],
                manifest={"version": 1, "sessions": {"shared-session": {"total_turns": 2}}, "checkpoints": {}},
            )
            return 1

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=side_effect),
            patch("entirecontext.sync.engine.export_sessions", side_effect=export_sessions_stub),
            patch("entirecontext.sync.engine.export_checkpoints", return_value=0),
            patch("entirecontext.sync.engine.update_manifest"),
        ):
            result = perform_sync(sync_db, str(ec_repo), {"push_on_sync": True})

        row = sync_db.execute("SELECT last_export_at FROM sync_metadata WHERE id = 1").fetchone()
        assert result["error"] == "git push retry failed: still rejected"
        assert result["retry_count"] == 1
        assert row["last_export_at"] is None

    def test_malformed_remote_manifest_returns_error(self, sync_db, ec_repo, tmp_path):
        remote_fixture = tmp_path / "remote-shadow"
        _write_snapshot(
            remote_fixture,
            session_id="shared-session",
            session_meta={"id": "shared-session", "total_turns": 1},
            transcript_entries=[{"id": "t1"}],
        )
        (remote_fixture / "manifest.json").write_text("{broken", encoding="utf-8")

        side_effect, _state = _mk_subprocess_side_effect(
            remote_fixture=remote_fixture,
            status_outputs=["M manifest.json\n"],
            push_results=[_cp(returncode=1, stderr="non-fast-forward")],
        )

        def export_sessions_stub(conn, repo_path, worktree_path, **kwargs):
            _write_snapshot(
                Path(worktree_path),
                session_id="shared-session",
                session_meta={"id": "shared-session", "total_turns": 2},
                transcript_entries=[{"id": "t2"}],
            )
            return 1

        def update_manifest_stub(conn, worktree_path):
            (Path(worktree_path) / "manifest.json").write_text(
                json.dumps({"version": 1, "sessions": {"shared-session": {"total_turns": 2}}, "checkpoints": {}}, indent=2),
                encoding="utf-8",
            )

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=side_effect),
            patch("entirecontext.sync.engine.export_sessions", side_effect=export_sessions_stub),
            patch("entirecontext.sync.engine.export_checkpoints", return_value=0),
            patch("entirecontext.sync.engine.update_manifest", side_effect=update_manifest_stub),
        ):
            result = perform_sync(sync_db, str(ec_repo), {"push_on_sync": True})

        assert "malformed manifest.json" in result["error"]

    def test_security_config_propagated_to_exporter(self, sync_db, ec_repo):
        config = {"push_on_sync": False, "security": {"filter_secrets": False}}
        side_effect, _state = _mk_subprocess_side_effect(status_outputs=["M manifest.json\n"])

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=side_effect),
            patch("entirecontext.sync.engine.export_sessions", return_value=1) as mock_export,
            patch("entirecontext.sync.engine.export_checkpoints", return_value=0),
            patch("entirecontext.sync.engine.update_manifest"),
        ):
            perform_sync(sync_db, str(ec_repo), config)

        assert mock_export.call_args.kwargs.get("filter_enabled") is False

    def test_security_config_defaults_to_enabled(self, sync_db, ec_repo):
        side_effect, _state = _mk_subprocess_side_effect(status_outputs=["M manifest.json\n"])

        with (
            patch("entirecontext.sync.engine.shadow_branch_exists", return_value=True),
            patch("entirecontext.sync.engine.subprocess.run", side_effect=side_effect),
            patch("entirecontext.sync.engine.export_sessions", return_value=1) as mock_export,
            patch("entirecontext.sync.engine.export_checkpoints", return_value=0),
            patch("entirecontext.sync.engine.update_manifest"),
        ):
            perform_sync(sync_db, str(ec_repo), {"push_on_sync": False})

        assert mock_export.call_args.kwargs.get("filter_enabled") is True


class TestPerformPull:
    def test_error_when_no_remote_shadow_branch(self, sync_db, ec_repo):
        side_effect, state = _mk_subprocess_side_effect(remote_fixture=None)
        state["remote_ref_exists"] = False

        with patch("entirecontext.sync.engine.subprocess.run", side_effect=side_effect):
            result = perform_pull(sync_db, str(ec_repo), {})

        assert result["error"] == "no_shadow_branch"

    def test_success_imports_sessions_and_checkpoints_from_remote_tracking_snapshot(self, sync_db, ec_repo, tmp_path):
        project_row = sync_db.execute("SELECT id FROM projects LIMIT 1").fetchone()
        project_id = project_row["id"]

        remote_fixture = tmp_path / "remote-shadow"
        stale_fixture = tmp_path / "stale-local-shadow"
        _write_snapshot(
            remote_fixture,
            session_id="imported-session-1",
            session_meta={
                "id": "imported-session-1",
                "project_id": project_id,
                "session_type": "claude",
            },
            checkpoints={
                "imported-cp-1": {
                    "id": "imported-cp-1",
                    "session_id": "imported-session-1",
                    "git_commit_hash": "abc123",
                    "git_branch": "main",
                }
            },
            manifest={"version": 1, "sessions": {"imported-session-1": {"total_turns": 1}}, "checkpoints": {}},
        )
        _write_snapshot(
            stale_fixture,
            session_id="stale-local-session",
            session_meta={
                "id": "stale-local-session",
                "project_id": project_id,
                "session_type": "claude",
            },
            manifest={"version": 1, "sessions": {"stale-local-session": {"total_turns": 1}}, "checkpoints": {}},
        )

        side_effect, state = _mk_subprocess_side_effect(remote_fixture=remote_fixture, stale_fixture=stale_fixture)

        with patch("entirecontext.sync.engine.subprocess.run", side_effect=side_effect):
            result = perform_pull(sync_db, str(ec_repo), {})

        session = sync_db.execute("SELECT * FROM sessions WHERE id = 'imported-session-1'").fetchone()
        stale_session = sync_db.execute("SELECT * FROM sessions WHERE id = 'stale-local-session'").fetchone()
        checkpoint = sync_db.execute("SELECT * FROM checkpoints WHERE id = 'imported-cp-1'").fetchone()

        add_refs = [args[-1] for args, _cwd in state["commands"] if args[:3] == ["git", "worktree", "add"]]

        assert result["error"] is None
        assert result["imported_sessions"] == 1
        assert result["imported_checkpoints"] == 1
        assert session is not None
        assert checkpoint is not None
        assert stale_session is None
        assert REMOTE_SHADOW_REF in add_refs
        assert SHADOW_BRANCH not in add_refs

    def test_updates_last_import_at(self, sync_db, ec_repo, tmp_path):
        remote_fixture = tmp_path / "remote-shadow"
        _write_snapshot(remote_fixture, manifest={"version": 1, "sessions": {}, "checkpoints": {}})
        side_effect, _state = _mk_subprocess_side_effect(remote_fixture=remote_fixture)

        with patch("entirecontext.sync.engine.subprocess.run", side_effect=side_effect):
            perform_pull(sync_db, str(ec_repo), {})

        row = sync_db.execute("SELECT last_import_at FROM sync_metadata WHERE id = 1").fetchone()
        assert row["last_import_at"] is not None

    def test_skips_existing_sessions(self, sync_db, ec_repo, tmp_path):
        from entirecontext.core.session import create_session

        project_row = sync_db.execute("SELECT id FROM projects LIMIT 1").fetchone()
        project_id = project_row["id"]
        create_session(sync_db, project_id, session_id="existing-session")

        remote_fixture = tmp_path / "remote-shadow"
        _write_snapshot(
            remote_fixture,
            session_id="existing-session",
            session_meta={"id": "existing-session", "project_id": project_id, "session_type": "claude"},
            manifest={"version": 1, "sessions": {"existing-session": {"total_turns": 1}}, "checkpoints": {}},
        )
        side_effect, _state = _mk_subprocess_side_effect(remote_fixture=remote_fixture)

        with patch("entirecontext.sync.engine.subprocess.run", side_effect=side_effect):
            result = perform_pull(sync_db, str(ec_repo), {})

        assert result["imported_sessions"] == 0

    def test_error_on_worktree_failure(self, sync_db, ec_repo, tmp_path):
        remote_fixture = tmp_path / "remote-shadow"
        _write_snapshot(remote_fixture, manifest={"version": 1, "sessions": {}, "checkpoints": {}})

        def fail_worktree(args, **kwargs):
            if args[:3] == ["git", "worktree", "add"]:
                raise subprocess.CalledProcessError(1, args, stderr="worktree error")
            if args[:3] == ["git", "rev-parse", "--verify"]:
                return _cp(returncode=0)
            return _cp()

        with patch("entirecontext.sync.engine.subprocess.run", side_effect=fail_worktree):
            result = perform_pull(sync_db, str(ec_repo), {})

        assert result["error"] == "worktree error"
