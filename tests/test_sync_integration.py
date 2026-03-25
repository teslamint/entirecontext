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
