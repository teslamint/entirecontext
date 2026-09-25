"""Canonical project root vs. active workspace root resolution.

A Git checkout has two roots that EntireContext cares about:

* ``project_root`` — where the logical project lives (``.entirecontext/``:
  DB, config, content, pid files). All linked worktrees of one repository
  share the main worktree as their project root, derived from
  ``git rev-parse --git-common-dir``.
* ``workspace_root`` — the current checkout's ``--show-toplevel``. Every Git
  subprocess and every checkout-relative file path uses it.

Layouts whose common dir is not ``<main>/.git`` (bare repositories with
worktrees, ``--separate-git-dir``, submodules) fall back to
``project_root == workspace_root``, which is the pre-v21 behaviour.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..db.connection import db_path_for

_BARE_RE = re.compile(r"^\s*bare\s*=\s*true\s*$", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True, slots=True)
class RepoRoots:
    project_root: str
    workspace_root: str
    git_common_dir: str | None
    worktree_git_dir: str | None
    branch: str | None
    is_linked_worktree: bool


_CACHE: dict[str, tuple[str, str, str] | None] = {}


def clear_repo_roots_cache() -> None:
    _CACHE.clear()


def _is_bare(common_dir: Path) -> bool:
    try:
        text = (common_dir / "config").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return bool(_BARE_RE.search(text))


def _canonical_from_common(common_dir: Path, worktree_git_dir: Path, workspace_root: str) -> str:
    """Map a Git common dir to the canonical project root.

    Only a linked worktree of a regular (non-bare) repository whose common dir
    is ``<main>/.git`` maps to ``<main>``; everything else keeps the workspace.
    """
    try:
        if common_dir.resolve() == worktree_git_dir.resolve():
            return workspace_root
        if common_dir.name != ".git":
            return workspace_root
        parent = common_dir.parent
        dot_git = parent / ".git"
        if not dot_git.is_dir() or not os.path.samefile(dot_git, common_dir):
            return workspace_root
        if _is_bare(common_dir):
            return workspace_root
    except OSError:
        return workspace_root
    parent_str = str(parent.resolve())
    try:
        if os.path.samefile(parent_str, workspace_root):
            return workspace_root
    except OSError:
        pass
    return parent_str


def _branch_from_head(worktree_git_dir: str | None) -> str | None:
    if not worktree_git_dir:
        return None
    try:
        head = (Path(worktree_git_dir) / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    prefix = "ref: refs/heads/"
    if head.startswith(prefix):
        return head[len(prefix) :] or None
    return None


def _build(workspace_root: str, common_dir: str, worktree_git_dir: str) -> RepoRoots:
    project_root = _canonical_from_common(Path(common_dir), Path(worktree_git_dir), workspace_root)
    return RepoRoots(
        project_root=project_root,
        workspace_root=workspace_root,
        git_common_dir=common_dir,
        worktree_git_dir=worktree_git_dir,
        branch=_branch_from_head(worktree_git_dir),
        is_linked_worktree=project_root != workspace_root,
    )


def _run_rev_parse(cwd: str) -> tuple[str, str, str] | None:
    """Return ``(toplevel, common_dir, absolute_git_dir)`` from one ``git rev-parse``.

    ``--path-format`` (Git 2.31+) is deliberately not used: older ``git
    rev-parse`` echoes unknown dashed options to stdout and still exits 0, so
    the output could not be trusted. A relative ``--git-common-dir`` is
    resolved against ``cwd`` instead, and output that is not exactly three
    absolute-looking lines is rejected.
    """
    cmd = ["git", "rev-parse", "--show-toplevel", "--git-common-dir", "--absolute-git-dir"]
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, FileNotFoundError, NotADirectoryError):
        return None
    if result.returncode != 0:
        return None
    lines = result.stdout.splitlines()
    if len(lines) != 3:
        return None
    top, common, gitdir = lines
    if not (Path(top).is_absolute() and Path(gitdir).is_absolute()) or common.startswith("-") or not common:
        return None
    return top, common, gitdir


def resolve_repo_roots(path: str | Path = ".") -> RepoRoots | None:
    """Resolve project and workspace roots with a single ``git rev-parse`` call."""
    try:
        key = str(Path(path).resolve())
    except (OSError, RuntimeError):
        key = str(path)
    if key in _CACHE:
        cached = _CACHE[key]
        return _build(*cached) if cached else None

    parsed = _run_rev_parse(str(path))
    if parsed is None:
        return None
    top, common, gitdir = parsed
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = Path(key) / common_path
    common = str(common_path.resolve())

    entry = (top, common, gitdir)
    _CACHE[key] = entry
    return _build(*entry)


def _read_gitdir_file(dot_git: Path) -> Path | None:
    try:
        text = dot_git.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    raw = Path(text[len("gitdir:") :].strip())
    if not raw.is_absolute():
        raw = dot_git.parent / raw
    return raw.resolve()


def _git_dirs_for_checkout(workspace: Path) -> tuple[Path, Path] | None:
    """Return ``(common_dir, worktree_git_dir)`` for a checkout root, without Git."""
    dot_git = workspace / ".git"
    if dot_git.is_dir():
        resolved = dot_git.resolve()
        return resolved, resolved
    if not dot_git.is_file():
        return None
    gitdir = _read_gitdir_file(dot_git)
    if gitdir is None:
        return None
    common = gitdir
    commondir_file = gitdir / "commondir"
    try:
        rel = commondir_file.read_text(encoding="utf-8").strip()
    except OSError:
        rel = ""
    if rel:
        candidate = Path(rel)
        if not candidate.is_absolute():
            candidate = gitdir / candidate
        common = candidate.resolve()
    return common, gitdir


def roots_for_workspace(workspace_root: str | Path) -> RepoRoots:
    """Derive roots for a known checkout toplevel using only the filesystem.

    Paths that are not Git checkouts map to themselves, so callers that were
    handed an arbitrary root keep their pre-v21 behaviour.
    """
    workspace = str(workspace_root)
    dirs = _git_dirs_for_checkout(Path(workspace))
    if dirs is None:
        return RepoRoots(workspace, workspace, None, None, None, False)
    common, gitdir = dirs
    return _build(workspace, str(common), str(gitdir))


def canonical_project_root(repo_path: str | Path) -> str:
    """Return the canonical project root for a checkout root (filesystem only)."""
    return roots_for_workspace(repo_path).project_root


def is_linked_worktree_root(repo_path: str | Path) -> bool:
    """True when ``repo_path`` is a linked worktree whose project lives elsewhere."""
    if not (Path(repo_path) / ".git").is_file():
        return False
    roots = roots_for_workspace(str(Path(repo_path).resolve()))
    return roots.is_linked_worktree


def resolve_repo_roots_fs(start: str | Path) -> RepoRoots | None:
    """Git-free root discovery for latency-sensitive hooks (PostToolUse).

    Walks parents of ``start`` looking for a ``.git`` entry, maps it to the
    canonical project root, and returns the roots only when the canonical
    ``.entirecontext/db/local.db`` exists; otherwise keeps walking so nested
    repositories behave as before. A legacy per-worktree database is never
    returned.
    """
    try:
        current = Path(start).resolve()
    except (OSError, RuntimeError):
        return None
    for parent in (current, *current.parents):
        if (parent / ".git").exists():
            roots = roots_for_workspace(str(parent))
        elif db_path_for(parent).exists():
            return RepoRoots(str(parent), str(parent), None, None, None, False)
        else:
            continue
        if db_path_for(roots.project_root).exists():
            return roots
    return None
