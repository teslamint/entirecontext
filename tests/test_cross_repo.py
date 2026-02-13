"""Unit tests for cross-repo search orchestrator."""

from __future__ import annotations


from entirecontext.core.cross_repo import (
    cross_repo_search,
    cross_repo_sessions,
    list_repos,
)


class TestListRepos:
    def test_returns_registered_repos(self, multi_ec_repos):
        repos = list_repos()
        names = {r["repo_name"] for r in repos}
        assert "frontend" in names
        assert "backend" in names

    def test_filter_by_name(self, multi_ec_repos):
        repos = list_repos(names=["frontend"])
        assert len(repos) == 1
        assert repos[0]["repo_name"] == "frontend"

    def test_skip_missing_db(self, multi_ec_repos, tmp_path):
        from entirecontext.db import get_global_db
        from entirecontext.db.global_schema import init_global_schema

        gconn = get_global_db()
        init_global_schema(gconn)
        gconn.execute(
            "INSERT OR REPLACE INTO repo_index (repo_path, repo_name, db_path) VALUES (?, ?, ?)",
            ("/nonexistent/repo", "ghost", "/nonexistent/repo/.entirecontext/db/local.db"),
        )
        gconn.commit()
        gconn.close()

        repos = list_repos()
        names = {r["repo_name"] for r in repos}
        assert "ghost" not in names
        assert "frontend" in names

    def test_empty_when_no_repos(self, isolated_global_db):
        repos = list_repos()
        assert repos == []


class TestCrossRepoSearch:
    def test_regex_merges_results(self, multi_ec_repos):
        results = cross_repo_search("auth", search_type="regex")
        assert len(results) >= 2
        repo_names = {r["repo_name"] for r in results}
        assert "frontend" in repo_names
        assert "backend" in repo_names

    def test_fts_merges_results(self, multi_ec_repos):
        results = cross_repo_search("auth", search_type="fts")
        assert len(results) >= 2
        repo_names = {r["repo_name"] for r in results}
        assert "frontend" in repo_names
        assert "backend" in repo_names

    def test_results_contain_repo_name(self, multi_ec_repos):
        results = cross_repo_search("auth")
        for r in results:
            assert "repo_name" in r
            assert "repo_path" in r

    def test_filter_by_repo_name(self, multi_ec_repos):
        results = cross_repo_search("auth", repos=["frontend"])
        assert all(r["repo_name"] == "frontend" for r in results)
        assert len(results) >= 1

    def test_limit_applied(self, multi_ec_repos):
        results = cross_repo_search("auth", limit=1)
        assert len(results) <= 1

    def test_no_match_returns_empty(self, multi_ec_repos):
        results = cross_repo_search("zzz_nonexistent_pattern_zzz")
        assert results == []

    def test_inaccessible_repo_skipped(self, multi_ec_repos, tmp_path):
        from entirecontext.db import get_global_db
        from entirecontext.db.global_schema import init_global_schema

        gconn = get_global_db()
        init_global_schema(gconn)
        bad_db = tmp_path / "bad.db"
        bad_db.write_text("not a sqlite db")
        gconn.execute(
            "INSERT OR REPLACE INTO repo_index (repo_path, repo_name, db_path) VALUES (?, ?, ?)",
            ("/bad/repo", "broken", str(bad_db)),
        )
        gconn.commit()
        gconn.close()

        results = cross_repo_search("auth")
        assert len(results) >= 2
        assert all(r["repo_name"] != "broken" for r in results)

    def test_session_target(self, multi_ec_repos):
        results = cross_repo_search(".", search_type="regex", target="session")
        assert len(results) == 0 or all("repo_name" in r for r in results)


class TestCrossRepoSessions:
    def test_merges_sessions(self, multi_ec_repos):
        sessions = cross_repo_sessions()
        assert len(sessions) >= 2
        repo_names = {s["repo_name"] for s in sessions}
        assert "frontend" in repo_names
        assert "backend" in repo_names

    def test_filter_by_repo(self, multi_ec_repos):
        sessions = cross_repo_sessions(repos=["backend"])
        assert all(s["repo_name"] == "backend" for s in sessions)
        assert len(sessions) >= 1

    def test_limit_applied(self, multi_ec_repos):
        sessions = cross_repo_sessions(limit=1)
        assert len(sessions) <= 1
