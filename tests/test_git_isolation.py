"""Regression tests for host git-config isolation.

The suite builds real git repos and commits in them. Without isolation, whatever
the developer sets globally — commit.gpgsign, core.hooksPath, aliases — changes
what those commands do, so results depend on whose machine runs them. CI cannot
catch that: runners have no such configuration, so the failures appear only
locally.
"""

from __future__ import annotations

import os
import subprocess

from tests.conftest import git_commit_env


def _git(args: list[str], cwd, env=None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)
    return result.stdout.strip()


class TestHermeticGitConfig:
    def test_global_and_system_config_are_redirected(self):
        assert os.environ["GIT_CONFIG_GLOBAL"] == os.devnull
        assert os.environ["GIT_CONFIG_SYSTEM"] == os.devnull

    def test_git_sees_no_global_config(self, git_repo):
        assert _git(["config", "--global", "--list"], git_repo) == ""

    def test_git_sees_no_system_config(self, git_repo):
        assert _git(["config", "--system", "--list"], git_repo) == ""

    def test_repo_local_config_still_applies(self, git_repo):
        """Isolation must not break the per-repo identity fixtures set."""
        assert _git(["config", "--local", "--get", "user.email"], git_repo) == "test@test.com"


class TestGitCommitEnv:
    def test_carries_the_isolation_variables(self):
        """env= replaces rather than extends, so the helper must pass these through."""
        env = git_commit_env()
        assert env["GIT_CONFIG_GLOBAL"] == os.devnull
        assert env["GIT_CONFIG_SYSTEM"] == os.devnull

    def test_carries_path(self):
        assert git_commit_env()["PATH"] == os.environ["PATH"]

    def test_sets_commit_identity(self):
        env = git_commit_env()
        assert env["GIT_AUTHOR_EMAIL"] == "test@test.com"
        assert env["GIT_COMMITTER_EMAIL"] == "test@test.com"

    def test_isolation_reaches_subprocesses_given_an_explicit_env(self, git_repo):
        """A subprocess run with env=git_commit_env() must not see host config."""
        assert _git(["config", "--global", "--list"], git_repo, env=git_commit_env()) == ""
