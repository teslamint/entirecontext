"""Tests for Signal B: working-file inference from recent commits."""

from __future__ import annotations

import subprocess
from pathlib import Path


from entirecontext.core.decision_prompt_surfacing import (
    _get_recent_commit_file_paths,
    rank_decisions_for_prompt,
)
from entirecontext.core.decisions import create_decision
from entirecontext.core.config import DEFAULT_CONFIG


def _commit_file(repo: Path, name: str, content: str = "x") -> None:
    """Create, add, and commit a file in *repo*."""
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    subprocess.run(["git", "-C", str(repo), "add", name], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", f"add {name}"],
        check=True,
        capture_output=True,
    )


class TestGetRecentCommitFilePaths:
    def test_returns_files(self, git_repo) -> None:
        _commit_file(git_repo, "hello.py")
        paths = _get_recent_commit_file_paths(str(git_repo))
        assert "hello.py" in paths

    def test_deduplicates(self, git_repo) -> None:
        _commit_file(git_repo, "dup.py", "v1")
        (git_repo / "dup.py").write_text("v2")
        subprocess.run(["git", "-C", str(git_repo), "add", "dup.py"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(git_repo), "commit", "-m", "update dup.py"],
            check=True,
            capture_output=True,
        )
        paths = _get_recent_commit_file_paths(str(git_repo))
        assert paths.count("dup.py") == 1

    def test_empty_repo(self, git_repo) -> None:
        # git_repo already has one --allow-empty commit; no files touched
        paths = _get_recent_commit_file_paths(str(git_repo))
        assert paths == []

    def test_respects_limit(self, git_repo) -> None:
        for i in range(10):
            _commit_file(git_repo, f"file_{i}.py", str(i))
        paths = _get_recent_commit_file_paths(str(git_repo), limit=3)
        # limit=3 means only the 3 most recent commits are inspected
        assert len(paths) <= 3
        # The 3 most recent files should be 9, 8, 7
        for i in (9, 8, 7):
            assert f"file_{i}.py" in paths

    def test_handles_timeout(self, monkeypatch) -> None:
        def _raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=["git"], timeout=5)

        monkeypatch.setattr(
            "entirecontext.core.decision_prompt_surfacing.subprocess.run",
            _raise_timeout,
        )
        paths = _get_recent_commit_file_paths("/nonexistent")
        assert paths == []


class TestRankIncludesSignalB:
    def test_rank_includes_signal_b(self, ec_repo, ec_db) -> None:
        """Integration: decision linked to a committed file is surfaced via Signal B.

        Signal A (uncommitted changes) is empty — all changes are committed.
        The prompt text shares no tokens with the decision title/rationale
        to avoid diff-FTS matching. We discriminate by checking the score
        carries the file_exact weight (>= 3.0) rather than just presence,
        since padding fills in decisions at score 0.0.
        """
        # Create a decision with a deliberately opaque title/rationale
        decision = create_decision(ec_db, title="zxqwkj-policy", rationale="vbnmlk-rationale")
        decision_id = decision["id"]

        # Create and commit a real file
        target_file = "alpha/bravo.py"
        _commit_file(ec_repo, target_file, "content = True\n")

        # Link the decision to that file path
        ec_db.execute(
            "INSERT INTO decision_files (decision_id, file_path) VALUES (?, ?)",
            (decision_id, target_file),
        )
        ec_db.commit()

        # Verify no uncommitted changes (Signal A returns nothing)
        result = subprocess.run(
            ["git", "diff", "HEAD", "--name-only"],
            cwd=str(ec_repo),
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "", "Expected no uncommitted changes"

        # Use a prompt that shares no tokens with decision title/rationale
        config = dict(DEFAULT_CONFIG)
        surfaced, warnings = rank_decisions_for_prompt(
            ec_db,
            repo_path=str(ec_repo),
            prompt_text="completely unrelated prompt 98765",
            config=config,
        )

        matched = [d for d in surfaced if d["id"] == decision_id]
        assert matched, f"Decision {decision_id[:12]} not found in surfaced results"
        # file_exact weight is 3.0, staleness_factor for 'fresh' is 1.0
        # Score should carry at least the file_exact signal
        assert matched[0]["score"] >= 3.0, f"Expected score >= 3.0 from file_exact match, got {matched[0]['score']}"
