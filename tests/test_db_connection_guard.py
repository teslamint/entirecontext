"""get_db refuses linked-worktree roots so a missed call site cannot fork the corpus."""

from __future__ import annotations

import pytest

from entirecontext.db import LinkedWorktreeDatabaseError, db_path_for, get_db


def test_get_db_rejects_linked_worktree_root(linked_worktree):
    _main, linked = linked_worktree

    with pytest.raises(LinkedWorktreeDatabaseError):
        get_db(str(linked))

    assert not (linked / ".entirecontext").exists()


def test_get_db_accepts_bare_repo_worktree(tmp_path, git_repo):
    import subprocess

    bare = tmp_path / "bare.git"
    subprocess.run(["git", "clone", "--bare", str(git_repo), str(bare)], check=True, capture_output=True)
    checkout = tmp_path / "bare-wt"
    subprocess.run(
        ["git", "-C", str(bare), "worktree", "add", "-b", "bw", str(checkout)], check=True, capture_output=True
    )

    conn = get_db(str(checkout))
    conn.close()
    assert db_path_for(checkout).exists()
