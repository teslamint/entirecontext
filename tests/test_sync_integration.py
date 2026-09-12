"""Real git integration tests for sync orchestration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from entirecontext.core.project import init_project
from entirecontext.core.session import create_session
from entirecontext.core.turn import create_turn
from entirecontext.db import get_db
from entirecontext.sync.engine import SHADOW_BRANCH, perform_sync


def _run_git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo_path: Path, remote_path: Path) -> Path:
    repo_path.mkdir()
    _run_git(["init", str(repo_path)])
    _run_git(["-C", str(repo_path), "config", "user.email", "test@test.com"])
    _run_git(["-C", str(repo_path), "config", "user.name", "Test"])
    _run_git(["-C", str(repo_path), "config", "commit.gpgsign", "false"])
    _run_git(["-C", str(repo_path), "remote", "add", "origin", str(remote_path)])
    _run_git(["-C", str(repo_path), "commit", "--allow-empty", "-m", "init"])
    return repo_path


def _seed_session(repo_path: Path, session_id: str) -> None:
    project = init_project(str(repo_path))
    conn = get_db(str(repo_path))
    session = create_session(conn, project["id"], session_id=session_id)
    create_turn(
        conn,
        session["id"],
        turn_number=1,
        user_message=f"user message for {session_id}",
        assistant_summary=f"assistant summary for {session_id}",
    )
    conn.execute("UPDATE sessions SET total_turns = 1 WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()


def _read_remote_json(remote_path: Path, relative_path: str) -> dict:
    result = _run_git(
        [
            f"--git-dir={remote_path}",
            "show",
            f"refs/heads/{SHADOW_BRANCH}:{relative_path}",
        ]
    )
    return json.loads(result.stdout)


def test_first_sync_pushes_shadow_branch_to_remote(tmp_path, isolated_global_db):
    remote_path = tmp_path / "remote.git"
    _run_git(["init", "--bare", str(remote_path)])

    repo_path = _init_repo(tmp_path / "repo", remote_path)
    _seed_session(repo_path, "session-first")

    conn = get_db(str(repo_path))
    result = perform_sync(conn, str(repo_path), {"push_on_sync": True})
    conn.close()

    manifest = _read_remote_json(remote_path, "manifest.json")

    assert result["error"] is None
    assert result["pushed"] is True
    assert result["merge_applied"] is False
    assert "session-first" in manifest["sessions"]


def test_sync_retries_non_fast_forward_and_merges_remote_state(tmp_path, isolated_global_db):
    remote_path = tmp_path / "remote.git"
    _run_git(["init", "--bare", str(remote_path)])

    repo_a = _init_repo(tmp_path / "repo-a", remote_path)
    _seed_session(repo_a, "session-a")
    conn_a = get_db(str(repo_a))
    first_result = perform_sync(conn_a, str(repo_a), {"push_on_sync": True})
    conn_a.close()

    repo_b = _init_repo(tmp_path / "repo-b", remote_path)
    _seed_session(repo_b, "session-b")
    conn_b = get_db(str(repo_b))
    second_result = perform_sync(conn_b, str(repo_b), {"push_on_sync": True})
    conn_b.close()

    manifest = _read_remote_json(remote_path, "manifest.json")

    assert first_result["error"] is None
    assert second_result["error"] is None
    assert second_result["pushed"] is True
    assert second_result["merge_applied"] is True
    assert second_result["retry_count"] == 1
    assert {"session-a", "session-b"} <= set(manifest["sessions"])


def test_sync_recovers_records_written_during_push(tmp_path, isolated_global_db, monkeypatch):
    from entirecontext.core.checkpoint import create_checkpoint
    from entirecontext.sync import coordinator

    remote_path = tmp_path / "remote.git"
    _run_git(["init", "--bare", str(remote_path)])
    repo_path = _init_repo(tmp_path / "repo", remote_path)
    _seed_session(repo_path, "baseline")
    conn = get_db(str(repo_path))
    writer = get_db(str(repo_path))
    original_push = coordinator.push_shadow_branch
    inserted = False

    def push_with_concurrent_records(worktree_path):
        nonlocal inserted
        if not inserted:
            inserted = True
            project_id = writer.execute("SELECT project_id FROM sessions WHERE id = 'baseline'").fetchone()[0]
            create_session(writer, project_id, session_id="during-push")
            create_turn(writer, "during-push", 1, user_message="new session during push")
            create_turn(writer, "baseline", 2, user_message="existing session during push")
            create_checkpoint(writer, "during-push", "abc123", checkpoint_id="during-push-checkpoint")
            writer.commit()
        return original_push(worktree_path)

    monkeypatch.setattr(coordinator, "push_shadow_branch", push_with_concurrent_records)
    try:
        first = perform_sync(conn, str(repo_path), {"push_on_sync": True})
        assert first["error"] is None
        assert first["pushed"] is True
        assert "during-push" not in _read_remote_json(remote_path, "manifest.json")["sessions"]
        watermark = conn.execute("SELECT last_export_at FROM sync_metadata WHERE id = 1").fetchone()[0]
        assert watermark is not None

        second = perform_sync(conn, str(repo_path), {"push_on_sync": True})
        assert second["error"] is None
        assert second["pushed"] is True
        paths = _run_git(
            [f"--git-dir={remote_path}", "ls-tree", "-r", "--name-only", f"refs/heads/{SHADOW_BRANCH}"]
        ).stdout.splitlines()
        assert "sessions/during-push/meta.json" in paths
        assert "checkpoints/during-push-checkpoint.json" in paths
        for session_id, expected_messages in (
            ("during-push", ["new session during push"]),
            ("baseline", ["user message for baseline", "existing session during push"]),
        ):
            transcript = _run_git(
                [
                    f"--git-dir={remote_path}",
                    "show",
                    f"refs/heads/{SHADOW_BRANCH}:sessions/{session_id}/transcript.jsonl",
                ]
            ).stdout
            assert [json.loads(line)["user_message"] for line in transcript.splitlines()] == expected_messages
    finally:
        writer.close()
        conn.close()


def test_sync_exports_same_second_checkpoint_after_existing_watermark(tmp_path, isolated_global_db):
    from datetime import datetime

    from entirecontext.core.checkpoint import create_checkpoint

    remote_path = tmp_path / "remote.git"
    _run_git(["init", "--bare", str(remote_path)])
    repo_path = _init_repo(tmp_path / "repo", remote_path)
    _seed_session(repo_path, "baseline")
    conn = get_db(str(repo_path))
    writer = get_db(str(repo_path))
    try:
        first = perform_sync(conn, str(repo_path), {"push_on_sync": True})
        assert first["error"] is None
        watermark = conn.execute("SELECT last_export_at FROM sync_metadata WHERE id = 1").fetchone()[0]
        same_second = datetime.fromisoformat(watermark).strftime("%Y-%m-%d %H:%M:%S")
        create_checkpoint(writer, "baseline", "abc123", checkpoint_id="same-second")
        writer.execute("UPDATE checkpoints SET created_at = ? WHERE id = ?", (same_second, "same-second"))
        writer.commit()

        second = perform_sync(conn, str(repo_path), {"push_on_sync": True})
        assert second["error"] is None
        assert second["exported_checkpoints"] == 1
        checkpoint = _read_remote_json(remote_path, "checkpoints/same-second.json")
        assert checkpoint["created_at"] == same_second
        assert checkpoint["session_id"] == "baseline"
    finally:
        writer.close()
        conn.close()


def test_sync_exports_metadata_only_updates(tmp_path, isolated_global_db):
    remote_path = tmp_path / "remote.git"
    _run_git(["init", "--bare", str(remote_path)])
    repo_path = _init_repo(tmp_path / "repo", remote_path)
    _seed_session(repo_path, "baseline")
    conn = get_db(str(repo_path))
    writer = get_db(str(repo_path))
    try:
        first = perform_sync(conn, str(repo_path), {"push_on_sync": True})
        assert first["error"] is None
        assert conn.execute("SELECT last_export_at FROM sync_metadata WHERE id = 1").fetchone()[0]
        writer.execute(
            "UPDATE sessions SET session_title = ?, session_summary = ?, ended_at = ? WHERE id = ?",
            ("Updated title", "Completed summary", "2020-01-01T00:00:00+00:00", "baseline"),
        )
        writer.commit()

        second = perform_sync(conn, str(repo_path), {"push_on_sync": True})
        assert second["error"] is None
        meta = _read_remote_json(remote_path, "sessions/baseline/meta.json")
        assert meta["session_title"] == "Updated title"
        assert meta["session_summary"] == "Completed summary"
        assert meta["ended_at"] == "2020-01-01T00:00:00+00:00"
    finally:
        writer.close()
        conn.close()


def test_sync_exports_backdated_records(tmp_path, isolated_global_db):
    remote_path = tmp_path / "remote.git"
    _run_git(["init", "--bare", str(remote_path)])
    repo_path = _init_repo(tmp_path / "repo", remote_path)
    _seed_session(repo_path, "baseline")
    conn = get_db(str(repo_path))
    writer = get_db(str(repo_path))
    try:
        first = perform_sync(conn, str(repo_path), {"push_on_sync": True})
        assert first["error"] is None
        assert conn.execute("SELECT last_export_at FROM sync_metadata WHERE id = 1").fetchone()[0]
        turn = create_turn(writer, "baseline", 2, user_message="delayed capture")
        old_timestamp = "2020-01-01T00:00:00+00:00"
        writer.execute("UPDATE turns SET timestamp = ? WHERE id = ?", (old_timestamp, turn["id"]))
        writer.execute("UPDATE sessions SET last_activity_at = ? WHERE id = ?", (old_timestamp, "baseline"))
        writer.commit()

        second = perform_sync(conn, str(repo_path), {"push_on_sync": True})
        assert second["error"] is None
        transcript = _run_git(
            [f"--git-dir={remote_path}", "show", f"refs/heads/{SHADOW_BRANCH}:sessions/baseline/transcript.jsonl"]
        ).stdout
        turns = [json.loads(line) for line in transcript.splitlines()]
        assert len(turns) == 2
        assert turns[1]["id"] == turn["id"]
        assert turns[1]["timestamp"] == old_timestamp
        assert turns[1]["user_message"] == "delayed capture"
    finally:
        writer.close()
        conn.close()
