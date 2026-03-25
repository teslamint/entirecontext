"""Git transport helpers for shadow branch sync."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .shadow_branch import SHADOW_BRANCH

REMOTE_SHADOW_REF = f"origin/{SHADOW_BRANCH}"


class GitCommandError(RuntimeError):
    pass


def run_git(args: list[str], cwd: str, *, check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or str(exc)).strip()
        raise GitCommandError(message) from exc
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise GitCommandError(message)
    return result


def create_worktree(repo_path: str, ref: str, prefix: str, *, detach: bool = False) -> str:
    worktree_path = tempfile.mkdtemp(prefix=prefix)
    command = ["worktree", "add"]
    if detach:
        command.append("--detach")
    command.extend([worktree_path, ref])
    run_git(command, cwd=repo_path, check=True)
    return worktree_path


def remove_worktree(repo_path: str, worktree_path: str) -> None:
    run_git(["worktree", "remove", "--force", worktree_path], cwd=repo_path, check=False, timeout=10)


def remote_shadow_ref_exists(repo_path: str) -> bool:
    result = run_git(
        ["rev-parse", "--verify", f"refs/remotes/{REMOTE_SHADOW_REF}"],
        cwd=repo_path,
        check=False,
    )
    return result.returncode == 0


def fetch_shadow_branch(repo_path: str) -> subprocess.CompletedProcess:
    return run_git(["fetch", "origin", SHADOW_BRANCH], cwd=repo_path, check=False, timeout=60)


def commit_if_changed(worktree_path: str, message: str) -> bool:
    run_git(["add", "-A"], cwd=worktree_path, check=True, timeout=10)
    status = run_git(["status", "--porcelain"], cwd=worktree_path, check=False, timeout=5)
    if not status.stdout.strip():
        return False
    run_git(["commit", "-m", message], cwd=worktree_path, check=True)
    return True


def push_shadow_branch(worktree_path: str) -> subprocess.CompletedProcess:
    return run_git(["push", "origin", SHADOW_BRANCH], cwd=worktree_path, check=False, timeout=60)


def reset_hard(worktree_path: str, ref: str) -> None:
    run_git(["reset", "--hard", ref], cwd=worktree_path, check=True)


def is_non_fast_forward_push(push_result: subprocess.CompletedProcess) -> bool:
    output = f"{push_result.stdout}\n{push_result.stderr}".lower()
    return push_result.returncode != 0 and (
        "non-fast-forward" in output or "fetch first" in output or "failed to push some refs" in output
    )


def read_json_file(path: Path, artifact_name: str) -> dict:
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing {artifact_name}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed {artifact_name}: {path}") from exc
