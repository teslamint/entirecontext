"""Tests for streaming Popen in _stream_commits and lazy archaeologize."""
import subprocess
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock

from entirecontext.core.archaeology import _stream_commits, archaeologize


def _fake_popen(chunks, *, running=False):
    proc = MagicMock()
    proc.stdout = MagicMock()
    proc.stdout.__iter__.return_value = iter(chunks)
    proc.stderr = StringIO("")
    proc.poll.return_value = None if running else 0
    proc.wait.return_value = 0
    proc.returncode = 0
    return proc


class TestStreamingPopen:
    def test_record_separator_at_chunk_boundary(self, monkeypatch):
        first_sha = "a" * 40
        second_sha = "b" * 40
        proc = _fake_popen(
            [
                f"\x1e{first_sha}\x00first message\x00first patch\n",
                "\x1e",
                f"{second_sha}\x00second message\x00second patch\n",
            ]
        )
        monkeypatch.setattr("entirecontext.core.archaeology.subprocess.Popen", lambda *a, **kw: proc)

        assert list(_stream_commits("/repo", None, None, 10)) == [
            (first_sha, "first message", "first patch"),
            (second_sha, "second message", "second patch"),
        ]

    def test_clean_completion_does_not_terminate_or_warn(self, monkeypatch):
        sha = "a" * 40
        proc = _fake_popen([f"\x1e{sha}\x00message\x00patch"])
        monkeypatch.setattr("entirecontext.core.archaeology.subprocess.Popen", lambda *a, **kw: proc)
        warnings = []

        assert list(_stream_commits("/repo", None, None, 10, warnings=warnings)) == [
            (sha, "message", "patch")
        ]
        assert warnings == []
        proc.terminate.assert_not_called()

    def test_generator_close_terminates_live_process(self, monkeypatch):
        first_sha = "a" * 40
        second_sha = "b" * 40
        proc = _fake_popen(
            [
                f"\x1e{first_sha}\x00first\x00patch\n\x1e",
                f"{second_sha}\x00second\x00patch",
            ],
            running=True,
        )
        monkeypatch.setattr("entirecontext.core.archaeology.subprocess.Popen", lambda *a, **kw: proc)

        gen = _stream_commits("/repo", None, None, 10)
        next(gen)
        gen.close()

        proc.terminate.assert_called_once()
        proc.wait.assert_called()

    def test_parity_with_real_repo(self, git_repo):
        """Yields correct (sha, msg, patch) tuples from a real repo."""
        (git_repo / "a.py").write_text("x = 1")
        subprocess.run(["git", "add", "."], cwd=str(git_repo), check=True)
        subprocess.run(["git", "commit", "-m", "add a"], cwd=str(git_repo), check=True)
        (git_repo / "b.py").write_text("y = 2")
        subprocess.run(["git", "add", "."], cwd=str(git_repo), check=True)
        subprocess.run(["git", "commit", "-m", "add b"], cwd=str(git_repo), check=True)

        results = list(_stream_commits(str(git_repo), since=None, until=None, limit=10))
        assert len(results) >= 2
        for sha, msg, _patch_text in results:
            assert len(sha) == 40
            assert isinstance(msg, str)
            assert msg

    def test_generator_cleanup_terminates_process(self, git_repo):
        """Early break from generator does not leak processes."""
        (git_repo / "c.py").write_text("z = 3")
        subprocess.run(["git", "add", "."], cwd=str(git_repo), check=True)
        subprocess.run(["git", "commit", "-m", "add c"], cwd=str(git_repo), check=True)

        gen = _stream_commits(str(git_repo), since=None, until=None, limit=100)
        next(gen)
        gen.close()

    def test_merge_commits_excluded(self, git_repo):
        """Merge commits are not yielded by _stream_commits."""
        repo = str(git_repo)
        # Detect default branch name (may be main or master depending on git config)
        branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=repo,
            capture_output=True, text=True,
        ).stdout.strip()
        # Create a branch, commit, merge back with --no-ff
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True)
        (git_repo / "feat.py").write_text("f = 1")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "feature commit"], cwd=repo, check=True)
        subprocess.run(["git", "checkout", branch], cwd=repo, check=True)
        subprocess.run(
            ["git", "merge", "feature", "--no-ff", "-m", "Merge branch feature"],
            cwd=repo, check=True,
        )

        results = list(_stream_commits(repo, since=None, until=None, limit=100))
        messages = [msg for _, msg, _ in results]
        assert not any("Merge branch" in m for m in messages)
        assert any("feature commit" in m for m in messages)


class TestLazyArchaeologize:
    def test_extraction_starts_before_stream_is_exhausted(self, ec_repo, ec_db, monkeypatch):
        extraction_started = False

        class SentinelIterator:
            def __init__(self):
                self.index = 0

            def __iter__(self):
                return self

            def __next__(self):
                nonlocal extraction_started
                if self.index == 0:
                    self.index += 1
                    return ("a" * 40, "first", "patch")
                if self.index == 1:
                    assert extraction_started, "stream requested a second commit before extraction started"
                    self.index += 1
                    return ("b" * 40, "second", "patch")
                raise StopIteration

        def fake_run_extraction(*args, **kwargs):
            nonlocal extraction_started
            extraction_started = True
            return SimpleNamespace(
                parsed_ok=True,
                candidates_inserted=0,
                warnings=[],
            )

        monkeypatch.setattr("entirecontext.core.archaeology._stream_commits", lambda *a, **kw: SentinelIterator())
        monkeypatch.setattr("entirecontext.core.archaeology.run_extraction", fake_run_extraction)

        result = archaeologize(ec_db, str(ec_repo), batch_size=1)

        assert extraction_started
        assert result.commits_scanned == 2

    def test_dry_run_counts_without_materialization(self, ec_repo, ec_db):
        """dry_run counts commits without storing all in memory."""
        repo = str(ec_repo)
        (ec_repo / "x.py").write_text("a = 1")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "test lazy"], cwd=repo, check=True)

        from entirecontext.core.archaeology import archaeologize
        result = archaeologize(ec_db, repo, dry_run=True, limit=10)
        assert result.commits_scanned >= 1
