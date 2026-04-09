from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.futures import add_assessment_relationship, create_assessment
from entirecontext.db import get_db

runner = CliRunner()


class TestFuturesRelate:
    def test_relate_success(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        a1 = create_assessment(conn, verdict="expand", impact_summary="adds flexibility")
        a2 = create_assessment(conn, verdict="narrow", impact_summary="removes options")
        conn.close()

        result = runner.invoke(
            app, ["futures", "relate", a1["id"][:12], "causes", a2["id"][:12], "--note", "test note"]
        )
        assert result.exit_code == 0
        assert "Relationship added" in result.output
        assert "test note" in result.output

    def test_relate_invalid_type(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        a1 = create_assessment(conn, verdict="expand", impact_summary="a")
        a2 = create_assessment(conn, verdict="narrow", impact_summary="b")
        conn.close()

        result = runner.invoke(app, ["futures", "relate", a1["id"][:12], "invalid_type", a2["id"][:12]])
        assert result.exit_code == 1


class TestFuturesRelationships:
    def test_relationships_with_data(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        a1 = create_assessment(conn, verdict="expand", impact_summary="adds flexibility")
        a2 = create_assessment(conn, verdict="narrow", impact_summary="removes options")
        add_assessment_relationship(conn, a1["id"], a2["id"], "causes", note="root cause")
        conn.close()

        result = runner.invoke(app, ["futures", "relationships", a1["id"][:12]])
        assert result.exit_code == 0
        assert "causes" in result.output
        assert a2["id"][:12] in result.output

    def test_relationships_empty(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        a1 = create_assessment(conn, verdict="neutral", impact_summary="nothing")
        conn.close()

        result = runner.invoke(app, ["futures", "relationships", a1["id"][:12]])
        assert result.exit_code == 0
        assert "No relationships found" in result.output


class TestFuturesUnrelate:
    def test_unrelate_success(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        a1 = create_assessment(conn, verdict="expand", impact_summary="a")
        a2 = create_assessment(conn, verdict="narrow", impact_summary="b")
        add_assessment_relationship(conn, a1["id"], a2["id"], "fixes")
        conn.close()

        result = runner.invoke(app, ["futures", "unrelate", a1["id"][:12], "fixes", a2["id"][:12]])
        assert result.exit_code == 0
        assert "Relationship removed" in result.output

    def test_unrelate_not_found(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        a1 = create_assessment(conn, verdict="expand", impact_summary="a")
        a2 = create_assessment(conn, verdict="narrow", impact_summary="b")
        conn.close()

        result = runner.invoke(app, ["futures", "unrelate", a1["id"][:12], "causes", a2["id"][:12]])
        assert result.exit_code == 0
        assert "not found" in result.output


class TestFuturesTrend:
    def test_trend_empty(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        with patch("entirecontext.core.cross_repo.cross_repo_assessment_trends") as mock_trends:
            mock_trends.return_value = (
                {"total_count": 0, "overall": {}, "with_feedback": 0, "by_repo": {}},
                [],
            )
            result = runner.invoke(app, ["futures", "trend"])
        assert result.exit_code == 0
        assert "No assessments found" in result.output

    def test_trend_single_repo(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        with patch("entirecontext.core.cross_repo.cross_repo_assessment_trends") as mock_trends:
            mock_trends.return_value = (
                {
                    "total_count": 5,
                    "overall": {"expand": 3, "narrow": 1, "neutral": 1},
                    "with_feedback": 2,
                    "by_repo": {
                        "my-repo": {"total": 5, "expand": 3, "narrow": 1, "neutral": 1, "with_feedback": 2},
                    },
                },
                [],
            )
            result = runner.invoke(app, ["futures", "trend"])
        assert result.exit_code == 0
        assert "Cross-Repo Assessment Trends" in result.output
        assert "Overall Distribution" in result.output
        assert "Per-Repo Breakdown" not in result.output

    def test_trend_multi_repo_with_warnings(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        with patch("entirecontext.core.cross_repo.cross_repo_assessment_trends") as mock_trends:
            mock_trends.return_value = (
                {
                    "total_count": 10,
                    "overall": {"expand": 5, "narrow": 3, "neutral": 2},
                    "with_feedback": 4,
                    "by_repo": {
                        "repo-a": {"total": 6, "expand": 3, "narrow": 2, "neutral": 1, "with_feedback": 2},
                        "repo-b": {"total": 4, "expand": 2, "narrow": 1, "neutral": 1, "with_feedback": 2},
                    },
                },
                ["Repo X had errors"],
            )
            result = runner.invoke(app, ["futures", "trend"])
        assert result.exit_code == 0
        assert "Per-Repo Breakdown" in result.output
        assert "repo-a" in result.output
        assert "repo-b" in result.output
        assert "Repo X had errors" in result.output
