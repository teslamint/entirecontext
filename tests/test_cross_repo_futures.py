"""Tests for cross-repo assessment aggregation and trend analysis."""

from __future__ import annotations

import pytest

from entirecontext.core.cross_repo import (
    cross_repo_assessments,
    cross_repo_assessment_trends,
)


def _get_repo_conn(repo_path):
    from entirecontext.db import get_db, check_and_migrate

    conn = get_db(str(repo_path))
    check_and_migrate(conn)
    return conn


def _seed_assessment(conn, verdict="expand", impact="test impact", feedback=None, feedback_reason=None):
    from entirecontext.core.futures import create_assessment, add_feedback

    a = create_assessment(conn, verdict=verdict, impact_summary=impact)
    if feedback:
        add_feedback(conn, a["id"], feedback, feedback_reason=feedback_reason)
    return a


class TestCrossRepoAssessments:
    def test_lists_from_multiple_repos(self, multi_ec_repos):
        for name, repo_path in multi_ec_repos.items():
            conn = _get_repo_conn(repo_path)
            _seed_assessment(conn, verdict="expand", impact=f"impact from {name}")
            conn.close()

        results = cross_repo_assessments()
        assert len(results) == 2
        repo_names = {r["repo_name"] for r in results}
        assert "frontend" in repo_names
        assert "backend" in repo_names

    def test_results_have_repo_metadata(self, multi_ec_repos):
        conn = _get_repo_conn(multi_ec_repos["frontend"])
        _seed_assessment(conn, verdict="narrow")
        conn.close()

        results = cross_repo_assessments()
        assert len(results) >= 1
        for r in results:
            assert "repo_name" in r
            assert "repo_path" in r

    def test_verdict_filter(self, multi_ec_repos):
        for name, repo_path in multi_ec_repos.items():
            conn = _get_repo_conn(repo_path)
            _seed_assessment(conn, verdict="expand", impact=f"expand from {name}")
            _seed_assessment(conn, verdict="narrow", impact=f"narrow from {name}")
            conn.close()

        expand_results = cross_repo_assessments(verdict="expand")
        assert len(expand_results) == 2
        assert all(r["verdict"] == "expand" for r in expand_results)

        narrow_results = cross_repo_assessments(verdict="narrow")
        assert len(narrow_results) == 2
        assert all(r["verdict"] == "narrow" for r in narrow_results)

    def test_invalid_verdict_raises(self, multi_ec_repos):
        with pytest.raises(ValueError, match="Invalid verdict"):
            cross_repo_assessments(verdict="invalid")

    def test_repo_filter(self, multi_ec_repos):
        for name, repo_path in multi_ec_repos.items():
            conn = _get_repo_conn(repo_path)
            _seed_assessment(conn, verdict="neutral", impact=f"from {name}")
            conn.close()

        results = cross_repo_assessments(repos=["frontend"])
        assert len(results) == 1
        assert results[0]["repo_name"] == "frontend"

    def test_since_filter(self, multi_ec_repos):
        conn = _get_repo_conn(multi_ec_repos["frontend"])
        _seed_assessment(conn, verdict="expand")
        conn.close()

        future_results = cross_repo_assessments(since="2099-01-01T00:00:00")
        assert future_results == []

        past_results = cross_repo_assessments(since="2000-01-01T00:00:00")
        assert len(past_results) >= 1

    def test_limit_applied(self, multi_ec_repos):
        for name, repo_path in multi_ec_repos.items():
            conn = _get_repo_conn(repo_path)
            for i in range(5):
                _seed_assessment(conn, verdict="neutral", impact=f"impact {i} from {name}")
            conn.close()

        results = cross_repo_assessments(limit=3)
        assert len(results) <= 3

    def test_empty_repos_returns_empty(self, isolated_global_db):
        results = cross_repo_assessments()
        assert results == []

    def test_include_warnings_false_returns_list(self, multi_ec_repos):
        result = cross_repo_assessments(include_warnings=False)
        assert isinstance(result, list)

    def test_include_warnings_true_returns_tuple(self, multi_ec_repos):
        result = cross_repo_assessments(include_warnings=True)
        assert isinstance(result, tuple)
        assert len(result) == 2
        results, warnings = result
        assert isinstance(results, list)
        assert isinstance(warnings, list)

    def test_sorted_by_created_at_desc(self, multi_ec_repos):
        for name, repo_path in multi_ec_repos.items():
            conn = _get_repo_conn(repo_path)
            _seed_assessment(conn, verdict="expand", impact=f"from {name}")
            conn.close()

        results = cross_repo_assessments()
        timestamps = [r["created_at"] for r in results]
        assert timestamps == sorted(timestamps, reverse=True)


class TestCrossRepoAssessmentTrends:
    def test_returns_overall_counts(self, multi_ec_repos):
        for name, repo_path in multi_ec_repos.items():
            conn = _get_repo_conn(repo_path)
            _seed_assessment(conn, verdict="expand", impact=f"expand from {name}")
            _seed_assessment(conn, verdict="narrow", impact=f"narrow from {name}")
            conn.close()

        trends = cross_repo_assessment_trends()
        assert "total_count" in trends
        assert "overall" in trends
        assert "by_repo" in trends
        assert "with_feedback" in trends
        assert trends["total_count"] == 4
        assert trends["overall"]["expand"] == 2
        assert trends["overall"]["narrow"] == 2
        assert trends["overall"]["neutral"] == 0

    def test_by_repo_breakdown(self, multi_ec_repos):
        for name, repo_path in multi_ec_repos.items():
            conn = _get_repo_conn(repo_path)
            _seed_assessment(conn, verdict="expand", impact=f"e from {name}")
            _seed_assessment(conn, verdict="narrow", impact=f"n from {name}")
            conn.close()

        trends = cross_repo_assessment_trends()
        assert "frontend" in trends["by_repo"]
        assert "backend" in trends["by_repo"]
        for repo_name in ("frontend", "backend"):
            repo_stats = trends["by_repo"][repo_name]
            assert repo_stats["total"] == 2
            assert repo_stats["expand"] == 1
            assert repo_stats["narrow"] == 1
            assert repo_stats["neutral"] == 0
            assert "repo_path" in repo_stats

    def test_feedback_counted(self, multi_ec_repos):
        conn = _get_repo_conn(multi_ec_repos["frontend"])
        _seed_assessment(conn, verdict="expand", feedback="agree")
        _seed_assessment(conn, verdict="narrow")
        conn.close()

        trends = cross_repo_assessment_trends()
        assert trends["with_feedback"] == 1
        assert trends["by_repo"]["frontend"]["with_feedback"] == 1

    def test_empty_repos_returns_zeros(self, isolated_global_db):
        trends = cross_repo_assessment_trends()
        assert trends["total_count"] == 0
        assert trends["overall"] == {"expand": 0, "narrow": 0, "neutral": 0}
        assert trends["by_repo"] == {}
        assert trends["with_feedback"] == 0

    def test_since_filter(self, multi_ec_repos):
        conn = _get_repo_conn(multi_ec_repos["frontend"])
        _seed_assessment(conn, verdict="expand")
        conn.close()

        future_trends = cross_repo_assessment_trends(since="2099-01-01T00:00:00")
        assert future_trends["total_count"] == 0

        past_trends = cross_repo_assessment_trends(since="2000-01-01T00:00:00")
        assert past_trends["total_count"] >= 1

    def test_repo_filter(self, multi_ec_repos):
        for name, repo_path in multi_ec_repos.items():
            conn = _get_repo_conn(repo_path)
            _seed_assessment(conn, verdict="expand", impact=f"from {name}")
            conn.close()

        trends = cross_repo_assessment_trends(repos=["frontend"])
        assert "frontend" in trends["by_repo"]
        assert "backend" not in trends["by_repo"]
        assert trends["total_count"] == 1

    def test_include_warnings_false(self, multi_ec_repos):
        result = cross_repo_assessment_trends(include_warnings=False)
        assert isinstance(result, dict)
        assert not isinstance(result, tuple)

    def test_include_warnings_true(self, multi_ec_repos):
        result = cross_repo_assessment_trends(include_warnings=True)
        assert isinstance(result, tuple)
        trends, warnings = result
        assert isinstance(trends, dict)
        assert isinstance(warnings, list)

    def test_no_assessments_in_repos(self, multi_ec_repos):
        trends = cross_repo_assessment_trends()
        assert trends["total_count"] == 0
        assert trends["overall"] == {"expand": 0, "narrow": 0, "neutral": 0}
        assert "frontend" in trends["by_repo"]
        assert "backend" in trends["by_repo"]
        assert trends["by_repo"]["frontend"]["total"] == 0
        assert trends["by_repo"]["backend"]["total"] == 0

    def test_broken_repo_warning(self, multi_ec_repos, tmp_path):
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

        trends, warnings = cross_repo_assessment_trends(include_warnings=True)
        assert len(warnings) >= 1
        assert any("broken" in w for w in warnings)
        assert "frontend" in trends["by_repo"]
