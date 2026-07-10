"""Unit tests for core/archaeology.py helper functions."""

import sqlite3
import subprocess
import pytest
from unittest.mock import patch, MagicMock
from entirecontext.core.archaeology import (
    _extract_files_from_patch,
    _build_signal_bundle,
    _is_processed,
    _mark_processed,
    _stream_commits,
    _get_github_token,
    archaeologize,
    ArchaeologyResult,
)
from entirecontext.core.decision_extraction import ExtractionOutcome


def _make_commits(git_repo, n, prefix="c"):
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
        "PATH": subprocess.check_output(["bash", "-c", "echo $PATH"]).decode().strip(),
    }
    for i in range(n):
        (git_repo / f"{prefix}{i}.txt").write_text(f"content {i}")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"{prefix} commit {i}"],
            cwd=git_repo,
            check=True,
            env=env,
        )


class TestExtractFilesFromPatch:
    def test_basic_diff(self):
        patch = "diff --git a/src/foo.py b/src/foo.py\n--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1 +1 @@\n-old\n+new"
        assert _extract_files_from_patch(patch) == ["src/foo.py"]

    def test_multiple_files(self):
        patch = "diff --git a/a.py b/a.py\n+++ b/a.py\ndiff --git a/b.py b/b.py\n+++ b/b.py\n"
        files = _extract_files_from_patch(patch)
        assert "a.py" in files
        assert "b.py" in files

    def test_rename(self):
        patch = "diff --git a/old.py b/new.py\nrename from old.py\nrename to new.py\n"
        files = _extract_files_from_patch(patch)
        assert "new.py" in files

    def test_empty_patch(self):
        assert _extract_files_from_patch("") == []

    def test_binary_file(self):
        patch = "diff --git a/img.png b/img.png\nBinary files differ\n"
        assert _extract_files_from_patch(patch) == ["img.png"]


class TestBuildSignalBundle:
    def test_basic(self):
        bundle = _build_signal_bundle("abc123", "commit message", "diff content", None)
        assert bundle.source_type == "archaeology"
        assert bundle.source_id == "abc123"
        assert bundle.session_id is None
        assert "diff content" in bundle.text_blocks

    def test_with_pr_body(self):
        bundle = _build_signal_bundle("abc123", "commit message", "diff", "PR description")
        assert "PR description" in bundle.text_blocks
        assert "diff" in bundle.text_blocks

    def test_message_included_in_text_blocks(self):
        bundle = _build_signal_bundle(
            "abc123", "fix: handle edge case\n\nThis explains why.", "diff content", None
        )
        assert "fix: handle edge case\n\nThis explains why." in bundle.text_blocks

    def test_message_precedes_pr_body_and_patch(self):
        bundle = _build_signal_bundle("abc123", "the message", "the patch", "the pr body")
        assert bundle.text_blocks == ["the message", "the pr body", "the patch"]

    def test_empty_message_omitted(self):
        bundle = _build_signal_bundle("abc123", "", "diff content", None)
        assert bundle.text_blocks == ["diff content"]


class TestDedup:
    @pytest.fixture
    def arch_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE archaeology_processed "
            "(commit_sha TEXT PRIMARY KEY, candidate_count INTEGER NOT NULL DEFAULT 0, "
            "processed_at TEXT DEFAULT (datetime('now')))"
        )
        return conn

    def test_not_processed(self, arch_db):
        assert _is_processed(arch_db, "abc123") is False

    def test_mark_and_check(self, arch_db):
        _mark_processed(arch_db, "abc123", 2)
        assert _is_processed(arch_db, "abc123") is True

    def test_mark_zero_candidates(self, arch_db):
        _mark_processed(arch_db, "abc123", 0)
        assert _is_processed(arch_db, "abc123") is True


class TestStreamCommits:
    def test_stream_from_fixture(self, git_repo):
        for i in range(3):
            (git_repo / f"file{i}.txt").write_text(f"content {i}")
            subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
            subprocess.run(
                ["git", "commit", "-m", f"commit {i}"],
                cwd=git_repo,
                check=True,
                env={
                    "GIT_AUTHOR_NAME": "Test",
                    "GIT_AUTHOR_EMAIL": "test@test.com",
                    "GIT_COMMITTER_NAME": "Test",
                    "GIT_COMMITTER_EMAIL": "test@test.com",
                    "PATH": subprocess.check_output(["bash", "-c", "echo $PATH"]).decode().strip(),
                },
            )
        commits = list(_stream_commits(str(git_repo), since=None, until=None, limit=10))
        assert len(commits) >= 3
        for sha, message, patch_text in commits:
            assert len(sha) == 40
            assert isinstance(message, str)
            assert isinstance(patch_text, str)

    def test_limit(self, git_repo):
        for i in range(5):
            (git_repo / f"f{i}.txt").write_text(f"c{i}")
            subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
            subprocess.run(
                ["git", "commit", "-m", f"c{i}"],
                cwd=git_repo,
                check=True,
                env={
                    "GIT_AUTHOR_NAME": "Test",
                    "GIT_AUTHOR_EMAIL": "test@test.com",
                    "GIT_COMMITTER_NAME": "Test",
                    "GIT_COMMITTER_EMAIL": "test@test.com",
                    "PATH": subprocess.check_output(["bash", "-c", "echo $PATH"]).decode().strip(),
                },
            )
        commits = list(_stream_commits(str(git_repo), since=None, until=None, limit=2))
        assert len(commits) == 2

    def test_empty_range(self, git_repo):
        commits = list(_stream_commits(str(git_repo), since="HEAD", until="HEAD", limit=10))
        assert len(commits) == 0

    def test_full_multiline_message_captured(self, git_repo):
        (git_repo / "body.txt").write_text("content")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                "subject line",
                "-m",
                "This is the body explaining why the change was made.",
            ],
            cwd=git_repo,
            check=True,
            env={
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
                "PATH": subprocess.check_output(["bash", "-c", "echo $PATH"]).decode().strip(),
            },
        )
        commits = list(_stream_commits(str(git_repo), since=None, until=None, limit=1))
        assert len(commits) == 1
        _, message, _ = commits[0]
        assert "subject line" in message
        assert "This is the body explaining why the change was made." in message


class TestGetGithubToken:
    def test_env_var_priority(self, monkeypatch):
        monkeypatch.setenv("EC_GITHUB_TOKEN", "env-token-123")
        assert _get_github_token() == "env-token-123"

    def test_gh_cli_fallback(self, monkeypatch):
        monkeypatch.delenv("EC_GITHUB_TOKEN", raising=False)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="gh-token-456\n")
            assert _get_github_token() == "gh-token-456"

    def test_no_token_returns_none(self, monkeypatch):
        monkeypatch.delenv("EC_GITHUB_TOKEN", raising=False)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            assert _get_github_token() is None


class TestArchaeologize:
    def test_dry_run_does_not_process(self, ec_db, ec_repo):
        _make_commits(ec_repo, 3)
        progress = []
        with patch("entirecontext.core.archaeology.run_extraction") as mock_extract:
            result = archaeologize(
                ec_db,
                str(ec_repo),
                dry_run=True,
                progress_callback=progress.append,
            )
        mock_extract.assert_not_called()
        assert isinstance(result, ArchaeologyResult)
        assert result.commits_processed == 0
        assert result.commits_scanned >= 3
        assert progress
        assert "Estimated token cost" in progress[0]

    def test_processes_and_marks(self, ec_db, ec_repo):
        _make_commits(ec_repo, 2)
        with patch(
            "entirecontext.core.archaeology.run_extraction",
            return_value=ExtractionOutcome(candidates_inserted=1),
        ) as mock_extract:
            result = archaeologize(ec_db, str(ec_repo))
        assert result.commits_processed >= 2
        assert result.candidates_generated == result.commits_processed
        assert mock_extract.call_count == result.commits_processed

    def test_commit_message_reaches_bundle(self, ec_db, ec_repo):
        _make_commits(ec_repo, 1, prefix="msgtest")
        with patch(
            "entirecontext.core.archaeology.run_extraction",
            return_value=ExtractionOutcome(candidates_inserted=0),
        ) as mock_extract:
            archaeologize(ec_db, str(ec_repo))
        assert mock_extract.call_count >= 1
        bundles = mock_extract.call_args.kwargs["bundles"]
        assert any("msgtest commit 0" in b.text_blocks[0] for b in bundles)

    def test_dry_run_limit_note_when_scanned_meets_limit(self, ec_db, ec_repo):
        _make_commits(ec_repo, 3)
        progress = []
        archaeologize(
            ec_db,
            str(ec_repo),
            limit=2,
            dry_run=True,
            progress_callback=progress.append,
        )
        assert progress
        assert "increase --limit" in progress[0]

    def test_dry_run_no_limit_note_when_under_limit(self, ec_db, ec_repo):
        _make_commits(ec_repo, 2)
        progress = []
        archaeologize(
            ec_db,
            str(ec_repo),
            limit=100,
            dry_run=True,
            progress_callback=progress.append,
        )
        assert progress
        assert "increase --limit" not in progress[0]

    def test_rerun_skips_already_processed(self, ec_db, ec_repo):
        _make_commits(ec_repo, 2)
        with patch(
            "entirecontext.core.archaeology.run_extraction",
            return_value=ExtractionOutcome(candidates_inserted=1),
        ):
            first = archaeologize(ec_db, str(ec_repo))
        with patch(
            "entirecontext.core.archaeology.run_extraction",
            return_value=ExtractionOutcome(candidates_inserted=1),
        ) as mock_extract:
            second = archaeologize(ec_db, str(ec_repo))
        assert second.commits_processed == 0
        assert second.commits_skipped == first.commits_processed
        mock_extract.assert_not_called()

    def test_interrupt_processes_each_commit_exactly_once(self, ec_db, ec_repo):
        _make_commits(ec_repo, 3)
        calls = {"n": 0}

        def side_effect(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise KeyboardInterrupt()
            return ExtractionOutcome(candidates_inserted=1)

        with patch(
            "entirecontext.core.archaeology.run_extraction",
            side_effect=side_effect,
        ):
            result = archaeologize(ec_db, str(ec_repo), batch_size=1)

        assert result.commits_processed == 1
        assert any("Interrupted" in w for w in result.warnings)

        # Re-run should process each remaining commit exactly once — no
        # double-processing of the commit that was mid-flight at interrupt.
        with patch(
            "entirecontext.core.archaeology.run_extraction",
            return_value=ExtractionOutcome(candidates_inserted=1),
        ) as mock_extract:
            second = archaeologize(ec_db, str(ec_repo), batch_size=1)

        assert mock_extract.call_count == second.commits_processed
        # Exactly one commit was processed before the interrupt; the rest
        # (scanned minus that one) must be processed on the second run.
        assert second.commits_processed == second.commits_scanned - 1
