"""Shadow branch management for git-based sync."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

SHADOW_BRANCH = "entirecontext/checkpoints/v1"


def _run_git(args: list[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=check,
    )


def init_shadow_branch(repo_path: str) -> bool:
    """Create the orphan shadow branch if it doesn't exist."""
    result = _run_git(["branch", "--list", SHADOW_BRANCH], cwd=repo_path)
    if SHADOW_BRANCH in result.stdout:
        return True

    result = _run_git(
        ["rev-parse", "--verify", f"refs/heads/{SHADOW_BRANCH}"],
        cwd=repo_path,
        check=False,
    )
    if result.returncode == 0:
        return True

    current_branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path).stdout.strip()

    _run_git(["checkout", "--orphan", SHADOW_BRANCH], cwd=repo_path)
    _run_git(["rm", "-rf", "."], cwd=repo_path, check=False)

    manifest = {"version": 1, "checkpoints": {}, "sessions": {}}
    manifest_path = Path(repo_path) / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    (Path(repo_path) / "sessions").mkdir(exist_ok=True)
    (Path(repo_path) / "checkpoints").mkdir(exist_ok=True)

    _run_git(["add", "manifest.json"], cwd=repo_path)
    _run_git(["commit", "-m", "Initialize EntireContext shadow branch"], cwd=repo_path)
    _run_git(["checkout", current_branch], cwd=repo_path)

    return True


def shadow_branch_exists(repo_path: str) -> bool:
    """Check if shadow branch exists."""
    result = _run_git(
        ["rev-parse", "--verify", f"refs/heads/{SHADOW_BRANCH}"],
        cwd=repo_path,
        check=False,
    )
    return result.returncode == 0
