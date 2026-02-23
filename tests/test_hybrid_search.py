"""Tests for hybrid search — FTS5 + recency via Reciprocal Rank Fusion (RRF)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.hybrid_search import hybrid_search, rrf_fuse

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_turns(ec_repo, ec_db, turns_data):
    """Insert turns with given data; returns list of turn IDs in insertion order."""
    from entirecontext.core.project import get_project
    from entirecontext.core.session import create_session
    from entirecontext.core.turn import create_turn

    project = get_project(str(ec_repo))
    session = create_session(ec_db, project["id"], session_id="hybrid-session")
    ids = []
    for i, data in enumerate(turns_data, start=1):
        t = create_turn(ec_db, session["id"], i, **data)
        ids.append(t["id"])
    return ids


# ---------------------------------------------------------------------------
# rrf_fuse unit tests
# ---------------------------------------------------------------------------


class TestRRFFuse:
    def test_empty_lists_returns_empty(self):
        assert rrf_fuse([]) == {}

    def test_empty_individual_list(self):
        scores = rrf_fuse([[], ["a", "b"]])
        assert scores["a"] == pytest.approx(1 / 61)
        assert scores["b"] == pytest.approx(1 / 62)

    def test_single_list_scores(self):
        scores = rrf_fuse([["a", "b", "c"]], k=60)
        assert scores["a"] == pytest.approx(1 / 61)
        assert scores["b"] == pytest.approx(1 / 62)
        assert scores["c"] == pytest.approx(1 / 63)

    def test_higher_rank_higher_score(self):
        scores = rrf_fuse([["a", "b", "c"]], k=60)
        assert scores["a"] > scores["b"] > scores["c"]

    def test_doc_in_both_lists_higher_than_single(self):
        # "a" is rank 1 in both lists; "b" and "c" appear in only one list each
        scores = rrf_fuse([["a", "b"], ["a", "c"]], k=60)
        assert scores["a"] > scores["b"]
        assert scores["a"] > scores["c"]

    def test_doc_in_one_list_only_still_scored(self):
        scores = rrf_fuse([["a", "b"], ["c", "d"]], k=60)
        # All docs appear in exactly one list; rank-1 docs score highest
        assert scores["a"] == pytest.approx(1 / 61)
        assert scores["c"] == pytest.approx(1 / 61)
        assert scores["b"] == pytest.approx(1 / 62)
        assert scores["d"] == pytest.approx(1 / 62)

    def test_custom_k(self):
        scores = rrf_fuse([["a"]], k=10)
        assert scores["a"] == pytest.approx(1 / 11)

    def test_custom_weights(self):
        # With weight=2 on list1, rank-1 doc in list1 scores twice as much
        scores_equal = rrf_fuse([["a"], ["b"]], weights=[1.0, 1.0], k=60)
        scores_weighted = rrf_fuse([["a"], ["b"]], weights=[2.0, 1.0], k=60)
        assert scores_weighted["a"] == pytest.approx(2.0 / 61)
        assert scores_weighted["b"] == pytest.approx(1.0 / 61)
        assert scores_weighted["a"] > scores_equal["a"]

    def test_default_weights_equal(self):
        scores_explicit = rrf_fuse([["a", "b"], ["b", "a"]], weights=[1.0, 1.0], k=60)
        scores_default = rrf_fuse([["a", "b"], ["b", "a"]], k=60)
        assert scores_default["a"] == pytest.approx(scores_explicit["a"])
        assert scores_default["b"] == pytest.approx(scores_explicit["b"])


# ---------------------------------------------------------------------------
# hybrid_search integration tests
# ---------------------------------------------------------------------------


class TestHybridSearch:
    def test_returns_list(self, ec_repo, ec_db):
        _seed_turns(
            ec_repo,
            ec_db,
            [
                {
                    "user_message": "implement auth login",
                    "assistant_summary": "built auth",
                    "timestamp": "2025-01-01T10:00:00",
                },
            ],
        )
        results = hybrid_search(ec_db, "auth")
        assert isinstance(results, list)

    def test_empty_db_returns_empty_list(self, ec_repo, ec_db):
        results = hybrid_search(ec_db, "auth")
        assert results == []

    def test_fts5_match_in_results(self, ec_repo, ec_db):
        ids = _seed_turns(
            ec_repo,
            ec_db,
            [
                {
                    "user_message": "implement auth login",
                    "assistant_summary": "built auth",
                    "timestamp": "2025-01-01T10:00:00",
                },
                {
                    "user_message": "unrelated xyz999 task",
                    "assistant_summary": "did other stuff",
                    "timestamp": "2025-01-02T10:00:00",
                },
            ],
        )
        results = hybrid_search(ec_db, "auth")
        result_ids = [r["id"] for r in results]
        assert ids[0] in result_ids

    def test_no_fts5_match_excluded(self, ec_repo, ec_db):
        ids = _seed_turns(
            ec_repo,
            ec_db,
            [
                {
                    "user_message": "completely unrelated content xyz123abc",
                    "assistant_summary": "nothing here",
                    "timestamp": "2025-01-01T10:00:00",
                },
            ],
        )
        results = hybrid_search(ec_db, "authentication")
        result_ids = [r["id"] for r in results]
        assert ids[0] not in result_ids

    def test_results_have_hybrid_score(self, ec_repo, ec_db):
        _seed_turns(
            ec_repo,
            ec_db,
            [
                {
                    "user_message": "auth feature work",
                    "assistant_summary": "built auth",
                    "timestamp": "2025-01-01T10:00:00",
                },
            ],
        )
        results = hybrid_search(ec_db, "auth")
        for r in results:
            assert "hybrid_score" in r
            assert r["hybrid_score"] > 0

    def test_results_sorted_by_score_descending(self, ec_repo, ec_db):
        _seed_turns(
            ec_repo,
            ec_db,
            [
                {
                    "user_message": "auth module build",
                    "assistant_summary": "full auth with login logout register",
                    "timestamp": "2025-01-01T10:00:00",
                },
                {
                    "user_message": "auth hotfix",
                    "assistant_summary": "patched auth bug",
                    "timestamp": "2025-01-03T10:00:00",
                },
                {
                    "user_message": "minor auth tweak",
                    "assistant_summary": "auth update",
                    "timestamp": "2025-01-02T10:00:00",
                },
            ],
        )
        results = hybrid_search(ec_db, "auth")
        scores = [r["hybrid_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_limit_respected(self, ec_repo, ec_db):
        _seed_turns(
            ec_repo,
            ec_db,
            [
                {
                    "user_message": f"auth task number {i}",
                    "assistant_summary": f"auth work {i}",
                    "timestamp": f"2025-01-{i:02d}T10:00:00",
                }
                for i in range(1, 8)
            ],
        )
        results = hybrid_search(ec_db, "auth", limit=3)
        assert len(results) <= 3

    def test_session_target(self, ec_repo, ec_db):
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session

        project = get_project(str(ec_repo))
        s = create_session(ec_db, project["id"], session_id="hyb-sess")
        ec_db.execute(
            "UPDATE sessions SET session_title=?, session_summary=? WHERE id=?",
            ("auth workflow session", "all about auth login and register", s["id"]),
        )
        ec_db.commit()
        results = hybrid_search(ec_db, "auth", target="session")
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_session_results_have_hybrid_score(self, ec_repo, ec_db):
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session

        project = get_project(str(ec_repo))
        s = create_session(ec_db, project["id"], session_id="hyb-sess2")
        ec_db.execute(
            "UPDATE sessions SET session_title=?, session_summary=? WHERE id=?",
            ("auth session", "auth related", s["id"]),
        )
        ec_db.commit()
        results = hybrid_search(ec_db, "auth", target="session")
        for r in results:
            assert "hybrid_score" in r

    def test_unsupported_target_returns_empty(self, ec_repo, ec_db):
        results = hybrid_search(ec_db, "auth", target="content")
        assert results == []

    def test_custom_k_param_accepted(self, ec_repo, ec_db):
        _seed_turns(
            ec_repo,
            ec_db,
            [
                {"user_message": "auth feature", "assistant_summary": "auth done", "timestamp": "2025-01-01T10:00:00"},
            ],
        )
        results_default = hybrid_search(ec_db, "auth")
        results_custom_k = hybrid_search(ec_db, "auth", k=10)
        # Both should return the same turn; just scores differ
        assert len(results_default) == len(results_custom_k)
        if results_default and results_custom_k:
            assert results_default[0]["id"] == results_custom_k[0]["id"]
            # With smaller k, scores are higher (1/(10+1) > 1/(60+1))
            assert results_custom_k[0]["hybrid_score"] > results_default[0]["hybrid_score"]


# ---------------------------------------------------------------------------
# CLI tests: ec search --hybrid
# ---------------------------------------------------------------------------


class TestSearchHybridCLI:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["search", "auth", "--hybrid"])
            assert result.exit_code == 1

    def test_hybrid_flag_calls_hybrid_search(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.hybrid_search.hybrid_search", return_value=[]) as mock_hs,
        ):
            runner.invoke(app, ["search", "auth", "--hybrid"])
            mock_hs.assert_called_once()

    def test_hybrid_no_results_message(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.hybrid_search.hybrid_search", return_value=[]),
        ):
            result = runner.invoke(app, ["search", "auth", "--hybrid"])
            assert result.exit_code == 0
            assert "no" in result.output.lower() or "0" in result.output

    def test_hybrid_with_results_exit_code(self):
        mock_conn = MagicMock()
        fake_results = [
            {
                "id": "turn-aaa",
                "session_id": "sess-bbb",
                "user_message": "implement auth module",
                "assistant_summary": "done auth",
                "timestamp": "2025-01-01T10:00:00",
                "files_touched": None,
                "git_commit_hash": None,
                "hybrid_score": 0.032,
            }
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.hybrid_search.hybrid_search", return_value=fake_results),
        ):
            result = runner.invoke(app, ["search", "auth", "--hybrid"])
            assert result.exit_code == 0

    def test_hybrid_conn_passed_to_hybrid_search(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.hybrid_search.hybrid_search", return_value=[]) as mock_hs,
        ):
            runner.invoke(app, ["search", "auth", "--hybrid"])
            mock_hs.assert_called_once()
            call_args = mock_hs.call_args
            assert call_args.args[0] is mock_conn

    def test_hybrid_limit_passed(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.hybrid_search.hybrid_search", return_value=[]) as mock_hs,
        ):
            runner.invoke(app, ["search", "auth", "--hybrid", "--limit", "5"])
            call_kwargs = mock_hs.call_args.kwargs
            assert call_kwargs.get("limit") == 5
