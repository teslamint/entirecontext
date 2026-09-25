"""``ec rewind --restore`` only touches the current worktree checkout."""

from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.checkpoint import create_checkpoint
from entirecontext.core.session import create_session
from entirecontext.db import get_db

runner = CliRunner()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, name: str, content: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-m", f"write {name}")
    return _git(repo, "rev-parse", "HEAD")


def _checkpoint(main: Path, workspace_root: Path, commit: str, session_id: str) -> str:
    conn = get_db(str(main))
    try:
        project_id = conn.execute("SELECT id FROM projects").fetchone()["id"]
        create_session(conn, project_id, session_id=session_id, workspace_root=str(workspace_root))
        return create_checkpoint(conn, session_id=session_id, git_commit_hash=commit, git_branch="wt")["id"]
    finally:
        conn.close()


def test_restore_in_linked_leaves_main_untouched(ec_worktree, monkeypatch):
    main, linked = ec_worktree
    first = _commit(linked, "app.txt", "v1\n")
    checkpoint_id = _checkpoint(main, linked, first, "wt-rewind")
    _commit(linked, "app.txt", "v2\n")
    (main / "dirty.txt").write_text("uncommitted main edit\n", encoding="utf-8")
    main_head = _git(main, "rev-parse", "HEAD")
    monkeypatch.chdir(linked)

    result = runner.invoke(app, ["rewind", checkpoint_id, "--restore"])

    assert result.exit_code == 0, result.output
    assert (linked / "app.txt").read_text(encoding="utf-8") == "v1\n"
    assert (main / "dirty.txt").read_text(encoding="utf-8") == "uncommitted main edit\n"
    assert not (main / "app.txt").exists()
    assert _git(main, "rev-parse", "HEAD") == main_head


def test_restore_of_other_workspace_checkpoint_requires_force(ec_worktree, monkeypatch):
    main, linked = ec_worktree
    first = _commit(linked, "app.txt", "v1\n")
    checkpoint_id = _checkpoint(main, main, first, "main-rewind")
    _commit(linked, "app.txt", "v2\n")
    monkeypatch.chdir(linked)

    refused = runner.invoke(app, ["rewind", checkpoint_id, "--restore"])

    assert refused.exit_code == 1
    assert "--force" in refused.output
    assert (linked / "app.txt").read_text(encoding="utf-8") == "v2\n"

    forced = runner.invoke(app, ["rewind", checkpoint_id, "--restore", "--force"])

    assert forced.exit_code == 0, forced.output
    assert (linked / "app.txt").read_text(encoding="utf-8") == "v1\n"
