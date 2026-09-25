"""Tests for canonical project root vs. workspace root resolution."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from entirecontext.core import repo_roots
from entirecontext.core.repo_roots import (
    clear_repo_roots_cache,
    resolve_repo_roots,
    resolve_repo_roots_fs,
    roots_for_workspace,
)


def _git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name, encoding="utf-8")
    _git("-C", str(repo), "add", name)
    _git("-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", name)


def test_normal_repo_roots(git_repo):
    roots = resolve_repo_roots(git_repo)

    assert roots is not None
    assert roots.project_root == str(git_repo)
    assert roots.workspace_root == str(git_repo)
    assert roots.is_linked_worktree is False
    assert Path(roots.git_common_dir) == git_repo / ".git"
    assert Path(roots.worktree_git_dir) == git_repo / ".git"


def test_subdirectory_matches_toplevel(git_repo):
    sub = git_repo / "a" / "b"
    sub.mkdir(parents=True)

    assert resolve_repo_roots(sub) == resolve_repo_roots(git_repo)


def test_linked_worktree_maps_to_main(linked_worktree):
    main, linked = linked_worktree
    sub = linked / "sub"
    sub.mkdir()

    roots = resolve_repo_roots(sub)

    assert roots is not None
    assert roots.project_root == str(main)
    assert roots.workspace_root == str(linked)
    assert roots.is_linked_worktree is True
    assert roots.branch == "wt"
    assert Path(roots.worktree_git_dir).parent == main / ".git" / "worktrees"
    assert Path(roots.git_common_dir) == main / ".git"


def test_filesystem_mapping_matches_git(linked_worktree):
    main, linked = linked_worktree

    assert roots_for_workspace(str(linked)) == resolve_repo_roots(linked)
    assert roots_for_workspace(str(main)) == resolve_repo_roots(main)


def test_detached_head_has_no_branch(git_repo):
    head = subprocess.run(
        ["git", "-C", str(git_repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    _git("-C", str(git_repo), "checkout", "--detach", head)

    roots = resolve_repo_roots(git_repo)

    assert roots is not None
    assert roots.branch is None


def test_bare_repo_worktree_falls_back_to_checkout(tmp_path, git_repo):
    bare = tmp_path / "bare.git"
    _git("clone", "--bare", str(git_repo), str(bare))
    checkout = tmp_path / "bare-wt"
    _git("-C", str(bare), "worktree", "add", "-b", "bw", str(checkout))

    roots = resolve_repo_roots(checkout)

    assert roots is not None
    assert roots.project_root == str(checkout)
    assert roots.workspace_root == str(checkout)
    assert roots.is_linked_worktree is False


def test_submodule_falls_back_to_submodule_toplevel(tmp_path, git_repo):
    parent = tmp_path / "parent"
    _git("init", str(parent))
    _commit(parent, "README")
    _git("-C", str(parent), "-c", "protocol.file.allow=always", "submodule", "add", str(git_repo), "child")
    child = parent / "child"

    roots = resolve_repo_roots(child)

    assert roots is not None
    assert roots.workspace_root == str(child.resolve())
    assert roots.project_root == roots.workspace_root
    assert roots.is_linked_worktree is False


def test_separate_git_dir_falls_back(tmp_path):
    work = tmp_path / "work"
    gitdir = tmp_path / "store" / "repo.git"
    gitdir.parent.mkdir()
    _git("init", "--separate-git-dir", str(gitdir), str(work))

    roots = resolve_repo_roots(work)

    assert roots is not None
    assert roots.project_root == str(work)
    assert roots.is_linked_worktree is False


def test_non_git_directory_returns_none(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()

    assert resolve_repo_roots(plain) is None


def test_rev_parse_does_not_use_path_format(linked_worktree, monkeypatch):
    """Git < 2.31 echoes an unknown ``--path-format`` to stdout and exits 0."""
    main, linked = linked_worktree
    clear_repo_roots_cache()
    real_run = subprocess.run
    calls: list[list[str]] = []

    def old_git_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        result = real_run([arg for arg in cmd if arg != "--path-format=absolute"], *args, **kwargs)
        if "--path-format=absolute" in cmd:
            result = subprocess.CompletedProcess(cmd, 0, "--path-format=absolute\n" + result.stdout, result.stderr)
        return result

    monkeypatch.setattr(repo_roots.subprocess, "run", old_git_run)

    main_roots = resolve_repo_roots(main)
    linked_roots = resolve_repo_roots(linked)

    assert all("--path-format=absolute" not in cmd for cmd in calls)
    assert len(calls) == 2
    assert main_roots is not None
    assert main_roots.workspace_root == str(main)
    assert main_roots.project_root == str(main)
    assert Path(main_roots.git_common_dir) == main / ".git"
    assert linked_roots is not None
    assert linked_roots.workspace_root == str(linked)
    assert linked_roots.project_root == str(main)


def test_echoed_option_output_is_rejected(git_repo, monkeypatch):
    clear_repo_roots_cache()

    def echoing_run(cmd, *args, **kwargs):
        stdout = f"--bogus\n{git_repo}\n.git\n{git_repo / '.git'}\n"
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr(repo_roots.subprocess, "run", echoing_run)

    assert resolve_repo_roots(git_repo) is None


def test_relative_common_dir_resolves_against_subdirectory(git_repo):
    clear_repo_roots_cache()
    sub = git_repo / "nested" / "dir"
    sub.mkdir(parents=True)

    roots = resolve_repo_roots(sub)

    assert roots is not None
    assert roots.workspace_root == str(git_repo)
    assert Path(roots.git_common_dir) == git_repo / ".git"


def test_cache_avoids_second_subprocess(git_repo, monkeypatch):
    clear_repo_roots_cache()
    real_run = subprocess.run
    count = {"n": 0}

    def counting_run(*args, **kwargs):
        count["n"] += 1
        return real_run(*args, **kwargs)

    monkeypatch.setattr(repo_roots.subprocess, "run", counting_run)

    first = resolve_repo_roots(git_repo)
    second = resolve_repo_roots(git_repo)

    assert first == second
    assert count["n"] == 1


def test_fs_resolver_finds_main_db_from_linked(ec_worktree, monkeypatch):
    main, linked = ec_worktree
    nested = linked / "pkg" / "mod"
    nested.mkdir(parents=True)
    monkeypatch.setattr(repo_roots.subprocess, "run", pytest.fail)

    roots = resolve_repo_roots_fs(nested)

    assert roots is not None
    assert roots.project_root == str(main)
    assert roots.workspace_root == str(linked)


def test_fs_resolver_ignores_legacy_worktree_db(legacy_worktree_db):
    main, linked, _db = legacy_worktree_db

    assert resolve_repo_roots_fs(linked) is None


def test_fs_resolver_prefers_main_db_over_legacy(legacy_worktree_db, isolated_global_db):
    from entirecontext.core.project import init_project

    main, linked, _db = legacy_worktree_db
    init_project(str(main))

    roots = resolve_repo_roots_fs(linked)

    assert roots is not None
    assert roots.project_root == str(main)


def test_fs_resolver_rejects_gitdir_without_back_pointer(tmp_path, git_repo):
    wt = tmp_path / "wt"
    _git("-C", str(git_repo), "worktree", "add", "-q", str(wt), "-b", "spoof")
    other = tmp_path / "other"
    other.mkdir()
    (other / ".git").write_text(f"gitdir: {git_repo / '.git' / 'worktrees' / 'wt'}\n", encoding="utf-8")

    assert roots_for_workspace(wt).is_linked_worktree is True
    spoofed = roots_for_workspace(other)
    assert spoofed.project_root == str(other)
    assert spoofed.is_linked_worktree is False


def test_fs_resolver_rejects_non_worktree_gitdir(tmp_path, git_repo):
    other = tmp_path / "other"
    other.mkdir()
    (other / ".git").write_text(f"gitdir: {git_repo / '.git'}\n", encoding="utf-8")

    roots = roots_for_workspace(other)
    assert roots.project_root == str(other)
    assert roots.git_common_dir is None
