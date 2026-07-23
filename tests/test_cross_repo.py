"""Unit tests for cross-repo search orchestrator."""

from __future__ import annotations

import struct

import pytest

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
    def _seed_bounded_turns(self, multi_ec_repos):
        from entirecontext.db import get_db

        for repo in multi_ec_repos.values():
            conn = get_db(str(repo))
            turns = conn.execute("SELECT id FROM turns ORDER BY turn_number").fetchall()
            conn.execute(
                "UPDATE turns SET user_message = ?, timestamp = ? WHERE id = ?",
                ("auth in range", "2026-01-01 00:00:00", turns[0]["id"]),
            )
            conn.execute(
                "UPDATE turns SET user_message = ?, timestamp = ? WHERE id = ?",
                ("auth out of range", "2026-03-01 00:00:00", turns[1]["id"]),
            )
            conn.commit()
            conn.close()

    @pytest.mark.parametrize("search_type", ["regex", "fts", "hybrid"])
    def test_until_filters_each_repo(self, multi_ec_repos, search_type):
        self._seed_bounded_turns(multi_ec_repos)

        results = cross_repo_search(
            "auth",
            search_type=search_type,
            until="2026-02-01 00:00:00",
        )

        assert len(results) == 2
        assert {result["repo_name"] for result in results} == {"frontend", "backend"}
        assert {result["repo_path"] for result in results} == {
            str(multi_ec_repos["frontend"]),
            str(multi_ec_repos["backend"]),
        }
        assert all(result["timestamp"] == "2026-01-01 00:00:00" for result in results)

    def test_exclusive_until_reaches_semantic_search(self, multi_ec_repos, monkeypatch):
        from entirecontext.core import embedding
        from entirecontext.db import get_db

        vector = struct.pack("2f", 1.0, 0.0)
        for repo in multi_ec_repos.values():
            conn = get_db(str(repo))
            turns = conn.execute("SELECT id FROM turns ORDER BY turn_number").fetchall()
            for index, turn in enumerate(turns):
                timestamp = "2026-02-01 00:00:00" if index == 0 else "2026-01-01 00:00:00"
                conn.execute("UPDATE turns SET timestamp = ? WHERE id = ?", (timestamp, turn["id"]))
                conn.execute(
                    "INSERT INTO embeddings "
                    "(id, source_type, source_id, model_name, vector, dimensions, text_hash) "
                    "VALUES (?, 'turn', ?, 'all-MiniLM-L6-v2', ?, 2, ?)",
                    (f"embedding-{index}", turn["id"], vector, f"hash-{index}"),
                )
            conn.commit()
            conn.close()
        monkeypatch.setattr(embedding, "embed_text", lambda *_args, **_kwargs: vector)

        results = cross_repo_search(
            "auth",
            search_type="semantic",
            until="2026-02-01 00:00:00",
            until_exclusive=True,
        )

        assert len(results) == 2
        assert {result["repo_name"] for result in results} == {"frontend", "backend"}
        assert all(result["timestamp"] == "2026-01-01 00:00:00" for result in results)

    def test_temporal_filter_preserves_repo_fault_isolation(self, multi_ec_repos, tmp_path):
        from entirecontext.db import get_global_db
        from entirecontext.db.global_schema import init_global_schema

        self._seed_bounded_turns(multi_ec_repos)
        bad_db = tmp_path / "bad.db"
        bad_db.write_text("not a sqlite db")
        gconn = get_global_db()
        init_global_schema(gconn)
        gconn.execute(
            "INSERT OR REPLACE INTO repo_index (repo_path, repo_name, db_path) VALUES (?, ?, ?)",
            ("/bad/repo", "broken", str(bad_db)),
        )
        gconn.commit()
        gconn.close()

        results, warnings = cross_repo_search(
            "auth",
            until="2026-02-01 00:00:00",
            include_warnings=True,
        )

        assert len(results) == 2
        assert {result["repo_name"] for result in results} == {"frontend", "backend"}
        assert warnings == [{"repo_name": "broken", "phase": "query", "error": "file is not a database"}]

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

    def test_hybrid_merges_results(self, multi_ec_repos):
        results = cross_repo_search("auth", search_type="hybrid")
        assert len(results) >= 2
        repo_names = {r["repo_name"] for r in results}
        assert "frontend" in repo_names
        assert "backend" in repo_names
        assert all("hybrid_score" in r for r in results)

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
