"""Tests for git_utils helpers."""

from __future__ import annotations

import subprocess


from entirecontext.core.git_utils import (
    get_current_branch,
    get_current_commit,
    get_diff_stat,
    get_tracked_files_snapshot,
)


class TestGetCurrentCommit:
    def test_returns_commit_hash(self, git_repo):
        commit = get_current_commit(str(git_repo))
        assert commit is not None
        assert len(commit) == 40

    def test_returns_none_outside_repo(self, tmp_path):
        result = get_current_commit(str(tmp_path))
        assert result is None

    def test_returns_none_on_timeout(self, git_repo, monkeypatch):
        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=5)

        monkeypatch.setattr(subprocess, "run", mock_run)
        assert get_current_commit(str(git_repo)) is None

    def test_returns_none_on_missing_git(self, git_repo, monkeypatch):
        def mock_run(*args, **kwargs):
            raise FileNotFoundError

        monkeypatch.setattr(subprocess, "run", mock_run)
        assert get_current_commit(str(git_repo)) is None


class TestGetCurrentBranch:
    def test_returns_branch_name(self, git_repo):
        branch = get_current_branch(str(git_repo))
        assert branch is not None
        assert isinstance(branch, str)
        assert len(branch) > 0

    def test_returns_none_outside_repo(self, tmp_path):
        result = get_current_branch(str(tmp_path))
        assert result is None

    def test_detached_head_returns_none(self, git_repo, monkeypatch):
        import subprocess as sp

        original_run = sp.run

        def mock_run(cmd, *args, **kwargs):
            if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:

                class FakeResult:
                    returncode = 0
                    stdout = "HEAD\n"

                return FakeResult()
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)
        assert get_current_branch(str(git_repo)) is None

    def test_returns_none_on_timeout(self, git_repo, monkeypatch):
        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=5)

        monkeypatch.setattr(subprocess, "run", mock_run)
        assert get_current_branch(str(git_repo)) is None


class TestGetDiffStat:
    def test_no_changes_returns_none(self, git_repo):
        result = get_diff_stat(str(git_repo))
        assert result is None

    def test_with_from_commit(self, git_repo):
        commit = get_current_commit(str(git_repo))
        (git_repo / "newfile.txt").write_text("hello")
        subprocess.run(["git", "-C", str(git_repo), "add", "newfile.txt"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(git_repo), "commit", "-m", "add file"],
            check=True,
            capture_output=True,
        )
        result = get_diff_stat(str(git_repo), from_commit=commit)
        assert result is not None
        assert "newfile.txt" in result

    def test_returns_none_on_timeout(self, git_repo, monkeypatch):
        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=10)

        monkeypatch.setattr(subprocess, "run", mock_run)
        assert get_diff_stat(str(git_repo)) is None

    def test_returns_none_outside_repo(self, tmp_path):
        assert get_diff_stat(str(tmp_path)) is None


class TestGetTrackedFilesSnapshot:
    def test_empty_repo_returns_empty_dict(self, git_repo):
        result = get_tracked_files_snapshot(str(git_repo))
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_tracked_files_appear_in_snapshot(self, git_repo):
        (git_repo / "src.py").write_text("x = 1")
        subprocess.run(["git", "-C", str(git_repo), "add", "src.py"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(git_repo), "commit", "-m", "add src"],
            check=True,
            capture_output=True,
        )
        result = get_tracked_files_snapshot(str(git_repo))
        assert "src.py" in result
        assert len(result["src.py"]) == 40

    def test_returns_empty_on_timeout(self, git_repo, monkeypatch):
        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=30)

        monkeypatch.setattr(subprocess, "run", mock_run)
        assert get_tracked_files_snapshot(str(git_repo)) == {}

    def test_returns_empty_outside_repo(self, tmp_path):
        result = get_tracked_files_snapshot(str(tmp_path))
        assert result == {}


class TestSharedDecisionSignals:
    """Both surfacing channels must observe the same repository state."""

    @staticmethod
    def _collectors():
        from entirecontext.core import decision_prompt_surfacing
        from entirecontext.hooks import decision_hooks

        return (decision_prompt_surfacing, decision_hooks)

    def test_diff_includes_staged_and_unstaged_changes(self, git_repo):
        (git_repo / "README.md").write_text("initial\n")
        subprocess.run(["git", "add", "README.md"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "track readme"], cwd=git_repo, check=True, capture_output=True)
        staged = git_repo / "staged.txt"
        staged.write_text("staged signal\n")
        subprocess.run(["git", "add", "staged.txt"], cwd=git_repo, check=True, capture_output=True)
        (git_repo / "README.md").write_text("unstaged signal\n")
        for module in self._collectors():
            diff = module._get_uncommitted_diff(str(git_repo))
            assert "staged signal" in diff
            assert "unstaged signal" in diff

    def test_diff_character_limit(self, git_repo):
        (git_repo / "README.md").write_text("한" * 9000 + "\n")
        subprocess.run(["git", "add", "README.md"], cwd=git_repo, check=True, capture_output=True)
        for module in self._collectors():
            diff = module._get_uncommitted_diff(str(git_repo))
            assert len(diff) == 8192
            assert "한" in diff

    def test_recent_commits_newest_first_with_limit(self, git_repo):
        original = get_current_commit(str(git_repo))
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "new signal"], cwd=git_repo, check=True, capture_output=True
        )
        newest = get_current_commit(str(git_repo))
        for module in self._collectors():
            assert module._get_recent_commit_shas(str(git_repo)) == [newest, original]
            assert module._get_recent_commit_shas(str(git_repo), limit=1) == [newest]

    def test_clean_and_nonrepository_fallbacks(self, git_repo, tmp_path):
        for module in self._collectors():
            assert module._get_uncommitted_diff(str(git_repo)) is None
            assert module._get_uncommitted_diff(str(tmp_path)) is None
            assert module._get_recent_commit_shas(str(tmp_path)) == []

    def test_timeout_fallbacks(self, git_repo, monkeypatch):
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

        monkeypatch.setattr(subprocess, "run", timeout)
        for module in self._collectors():
            assert module._get_uncommitted_diff(str(git_repo)) is None
            assert module._get_recent_commit_shas(str(git_repo)) == []

    def test_missing_git_fallbacks(self, git_repo, monkeypatch):
        def missing_git(*args, **kwargs):
            raise FileNotFoundError

        monkeypatch.setattr(subprocess, "run", missing_git)
        for module in self._collectors():
            assert module._get_uncommitted_diff(str(git_repo)) is None
            assert module._get_recent_commit_shas(str(git_repo)) == []
