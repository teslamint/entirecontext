"""Shared git state helpers for CLI and hooks."""

from __future__ import annotations

import subprocess


def get_current_commit(repo_path: str) -> str | None:
    """Get current HEAD commit hash via git rev-parse HEAD."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_current_branch(repo_path: str) -> str | None:
    """Get current branch name via git rev-parse --abbrev-ref HEAD."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            return branch if branch != "HEAD" else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_diff_stat(repo_path: str, from_commit: str | None = None) -> str | None:
    """Get diff stat between from_commit and HEAD, or just working tree if no from_commit."""
    try:
        if from_commit:
            cmd = ["git", "diff", "--stat", from_commit, "HEAD"]
        else:
            cmd = ["git", "diff", "--stat"]
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            stat = result.stdout.strip()
            return stat if stat else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_tracked_files_snapshot(repo_path: str) -> dict[str, str]:
    """Get snapshot of tracked files as {path: hash} via git ls-files -s."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-s"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            snapshot: dict[str, str] = {}
            for line in result.stdout.splitlines():
                # Format: <mode> <hash> <stage>\t<path>
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    file_info = parts[0].split()
                    if len(file_info) >= 2:
                        snapshot[parts[1]] = file_info[1]
            return snapshot
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return {}
