"""Tests for runtime context helpers."""

from __future__ import annotations

from entirecontext.core.context import GlobalContext, RepoContext
from entirecontext.core.session import create_session
from entirecontext.db import get_db


def test_repo_context_loads_project_and_current_session(ec_repo):
    conn = get_db(str(ec_repo))
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
    create_session(conn, project_id, session_id="ctx-session")
    conn.close()

    context = RepoContext.from_repo_path(ec_repo, require_project=True)

    assert context is not None
    assert context.repo_path == str(ec_repo.resolve())
    assert context.project["id"] == project_id
    assert context.current_session_id == "ctx-session"
    assert isinstance(context.config, dict)
    context.close()


def test_repo_context_returns_none_outside_repo(tmp_path):
    assert RepoContext.from_cwd(tmp_path) is None


def test_global_context_lists_registered_repos(multi_ec_repos):
    context = GlobalContext.create()

    repos = context.list_registered_repos()

    assert {repo["repo_name"] for repo in repos} >= {"frontend", "backend"}
    context.close()
