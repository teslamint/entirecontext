"""Tests for runtime context helpers."""

from __future__ import annotations

from entirecontext.core.context import RepoContext


def test_repo_context_returns_none_outside_repo(tmp_path):
    assert RepoContext.from_cwd(tmp_path) is None
