"""Tests for streaming Popen in _stream_commits and lazy archaeologize."""
import subprocess

from entirecontext.core.archaeology import _stream_commits


class TestStreamingPopen:
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


class TestLazyArchaeologize:
    def test_dry_run_counts_without_materialization(self, ec_repo, ec_db):
        """dry_run counts commits without storing all in memory."""
        repo = str(ec_repo)
        (ec_repo / "x.py").write_text("a = 1")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "test lazy"], cwd=repo, check=True)

        from entirecontext.core.archaeology import archaeologize
        result = archaeologize(ec_db, repo, dry_run=True, limit=10)
        assert result.commits_scanned >= 1
