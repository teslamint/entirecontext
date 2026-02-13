"""E2E tests for project initialization."""

from __future__ import annotations

from entirecontext.core.project import get_status, init_project
from entirecontext.db import get_db


class TestProjectInit:
    def test_creates_directory_structure(self, git_repo, isolated_global_db):
        init_project(str(git_repo))
        ec_dir = git_repo / ".entirecontext"
        assert ec_dir.is_dir()
        assert (ec_dir / "db").is_dir()
        assert (ec_dir / "content").is_dir()
        assert (ec_dir / "db" / "local.db").is_file()

    def test_creates_project_record(self, git_repo, isolated_global_db):
        project = init_project(str(git_repo))
        assert project["id"]
        assert project["name"] == "repo"
        assert project["repo_path"] == str(git_repo.resolve())

        conn = get_db(str(git_repo))
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone()
        conn.close()
        assert row is not None
        assert row["repo_path"] == str(git_repo.resolve())

    def test_schema_valid(self, git_repo, isolated_global_db):
        init_project(str(git_repo))
        conn = get_db(str(git_repo))
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        for expected in (
            "projects",
            "sessions",
            "turns",
            "turn_content",
            "checkpoints",
            "schema_version",
        ):
            assert expected in tables

    def test_updates_global_db(self, git_repo, isolated_global_db):
        init_project(str(git_repo))
        from entirecontext.db import get_global_db

        gconn = get_global_db()
        row = gconn.execute(
            "SELECT * FROM repo_index WHERE repo_path = ?",
            (str(git_repo.resolve()),),
        ).fetchone()
        gconn.close()
        assert row is not None
        assert row["repo_name"] == "repo"

    def test_idempotent(self, git_repo, isolated_global_db):
        p1 = init_project(str(git_repo))
        p2 = init_project(str(git_repo))
        assert p1["id"] == p2["id"]

    def test_status_after_init(self, ec_repo):
        status = get_status(str(ec_repo))
        assert status["initialized"] is True
        assert status["session_count"] == 0
        assert status["turn_count"] == 0
        assert status["checkpoint_count"] == 0
        assert status["active_session"] is None
