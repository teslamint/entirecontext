"""Tests for assessment-based auto tidy PR suggestion (rule-based)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.tidy_pr import (
    collect_tidy_suggestions,
    generate_tidy_pr,
    score_tidy_suggestions,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _seed_assessments(ec_repo, ec_db):
    """Seed assessments with various verdicts and tidy_suggestions."""
    ec_db.execute(
        """INSERT INTO checkpoints (id, session_id, git_commit_hash, created_at)
           SELECT 'chk-1', s.id, 'abc123', datetime('now')
           FROM sessions s LIMIT 1"""
    )
    ec_db.execute(
        """INSERT INTO checkpoints (id, session_id, git_commit_hash, created_at)
           SELECT 'chk-2', s.id, 'def456', datetime('now')
           FROM sessions s LIMIT 1"""
    )
    ec_db.execute(
        """INSERT INTO checkpoints (id, session_id, git_commit_hash, created_at)
           SELECT 'chk-3', s.id, 'ghi789', datetime('now')
           FROM sessions s LIMIT 1"""
    )
    ec_db.commit()

    # narrow assessments with tidy suggestions
    ec_db.execute(
        """INSERT INTO assessments (id, checkpoint_id, verdict, impact_summary, tidy_suggestion, created_at)
           VALUES ('a1', 'chk-1', 'narrow', 'Reduces coupling', 'Extract helper function auth_check()', datetime('now'))"""
    )
    ec_db.execute(
        """INSERT INTO assessments (id, checkpoint_id, verdict, impact_summary, tidy_suggestion, created_at)
           VALUES ('a2', 'chk-2', 'narrow', 'Simplifies tests', 'Move shared fixtures to conftest.py', datetime('now'))"""
    )
    # expand assessment (should be less prominent in tidy suggestions)
    ec_db.execute(
        """INSERT INTO assessments (id, checkpoint_id, verdict, impact_summary, tidy_suggestion, created_at)
           VALUES ('a3', 'chk-3', 'expand', 'Increases flexibility', NULL, datetime('now'))"""
    )
    # narrow without tidy_suggestion
    ec_db.execute(
        """INSERT INTO assessments (id, checkpoint_id, verdict, impact_summary, tidy_suggestion, created_at)
           VALUES ('a4', NULL, 'narrow', 'Minor coupling', NULL, datetime('now'))"""
    )
    ec_db.commit()

    return {"a1": "a1", "a2": "a2", "a3": "a3", "a4": "a4"}


def _seed_with_session(ec_repo, ec_db):
    """Ensure at least one session exists before seeding assessments."""
    from entirecontext.core.project import get_project
    from entirecontext.core.session import create_session

    project = get_project(str(ec_repo))
    create_session(ec_db, project["id"], session_id="tidy-sess-1")
    return _seed_assessments(ec_repo, ec_db)


# ---------------------------------------------------------------------------
# collect_tidy_suggestions
# ---------------------------------------------------------------------------


class TestCollectTidySuggestions:
    def test_returns_list(self, ec_repo, ec_db):
        _seed_with_session(ec_repo, ec_db)
        suggestions = collect_tidy_suggestions(ec_db)
        assert isinstance(suggestions, list)

    def test_only_includes_narrow_with_suggestion(self, ec_repo, ec_db):
        _seed_with_session(ec_repo, ec_db)
        suggestions = collect_tidy_suggestions(ec_db)
        # Only a1 and a2 have narrow verdict + tidy_suggestion
        assert len(suggestions) == 2

    def test_each_suggestion_has_required_fields(self, ec_repo, ec_db):
        _seed_with_session(ec_repo, ec_db)
        suggestions = collect_tidy_suggestions(ec_db)
        for s in suggestions:
            assert "assessment_id" in s
            assert "tidy_suggestion" in s
            assert "impact_summary" in s
            assert "verdict" in s

    def test_all_verdicts_are_narrow(self, ec_repo, ec_db):
        _seed_with_session(ec_repo, ec_db)
        suggestions = collect_tidy_suggestions(ec_db)
        for s in suggestions:
            assert s["verdict"] == "narrow"

    def test_since_filter(self, ec_repo, ec_db):
        _seed_with_session(ec_repo, ec_db)
        # Future date should return 0 since all seeded assessments are 'now'
        suggestions = collect_tidy_suggestions(ec_db, since="2099-01-01")
        assert suggestions == []

    def test_limit_respected(self, ec_repo, ec_db):
        _seed_with_session(ec_repo, ec_db)
        suggestions = collect_tidy_suggestions(ec_db, limit=1)
        assert len(suggestions) <= 1

    def test_empty_db_returns_empty(self, ec_repo, ec_db):
        suggestions = collect_tidy_suggestions(ec_db)
        assert suggestions == []


# ---------------------------------------------------------------------------
# score_tidy_suggestions
# ---------------------------------------------------------------------------


class TestScoreTidySuggestions:
    def test_returns_list(self, ec_repo, ec_db):
        _seed_with_session(ec_repo, ec_db)
        suggestions = collect_tidy_suggestions(ec_db)
        scored = score_tidy_suggestions(suggestions)
        assert isinstance(scored, list)

    def test_adds_score_field(self, ec_repo, ec_db):
        _seed_with_session(ec_repo, ec_db)
        suggestions = collect_tidy_suggestions(ec_db)
        scored = score_tidy_suggestions(suggestions)
        for s in scored:
            assert "score" in s
            assert isinstance(s["score"], (int, float))

    def test_sorted_by_score_descending(self, ec_repo, ec_db):
        _seed_with_session(ec_repo, ec_db)
        suggestions = collect_tidy_suggestions(ec_db)
        scored = score_tidy_suggestions(suggestions)
        scores = [s["score"] for s in scored]
        assert scores == sorted(scores, reverse=True)

    def test_empty_list_returns_empty(self):
        assert score_tidy_suggestions([]) == []

    def test_agreed_feedback_boosts_score(self):
        """Suggestions with 'agree' feedback should score higher than those without."""
        suggestions = [
            {"assessment_id": "x1", "tidy_suggestion": "Extract fn", "impact_summary": "...",
             "verdict": "narrow", "feedback": "agree"},
            {"assessment_id": "x2", "tidy_suggestion": "Move class", "impact_summary": "...",
             "verdict": "narrow", "feedback": None},
        ]
        scored = score_tidy_suggestions(suggestions)
        score_map = {s["assessment_id"]: s["score"] for s in scored}
        assert score_map["x1"] >= score_map["x2"]


# ---------------------------------------------------------------------------
# generate_tidy_pr
# ---------------------------------------------------------------------------


class TestGenerateTidyPr:
    def test_returns_string(self, ec_repo, ec_db):
        _seed_with_session(ec_repo, ec_db)
        pr_text = generate_tidy_pr(ec_db)
        assert isinstance(pr_text, str)

    def test_contains_title(self, ec_repo, ec_db):
        _seed_with_session(ec_repo, ec_db)
        pr_text = generate_tidy_pr(ec_db)
        assert "tidy" in pr_text.lower() or "refactor" in pr_text.lower() or "clean" in pr_text.lower()

    def test_contains_suggestion_text(self, ec_repo, ec_db):
        _seed_with_session(ec_repo, ec_db)
        pr_text = generate_tidy_pr(ec_db)
        assert "auth_check" in pr_text or "conftest" in pr_text

    def test_empty_db_returns_message(self, ec_repo, ec_db):
        pr_text = generate_tidy_pr(ec_db)
        assert "no" in pr_text.lower() or "0" in pr_text

    def test_limit_param(self, ec_repo, ec_db):
        _seed_with_session(ec_repo, ec_db)
        pr_text = generate_tidy_pr(ec_db, limit=1)
        # With limit=1, only one suggestion should appear
        assert isinstance(pr_text, str)

    def test_returns_yaml_frontmatter(self, ec_repo, ec_db):
        _seed_with_session(ec_repo, ec_db)
        pr_text = generate_tidy_pr(ec_db)
        assert pr_text.startswith("---")

    def test_since_filter(self, ec_repo, ec_db):
        _seed_with_session(ec_repo, ec_db)
        pr_text = generate_tidy_pr(ec_db, since="2099-01-01")
        assert "no" in pr_text.lower() or "0" in pr_text


# ---------------------------------------------------------------------------
# CLI: ec futures tidy-pr
# ---------------------------------------------------------------------------


class TestFuturesTidyPrCLI:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["futures", "tidy-pr"])
        assert result.exit_code == 1

    def test_basic_output(self):
        mock_conn = MagicMock()
        pr_text = "---\ntitle: Tidy PR\n---\n## Suggestions\n- Extract auth_check()\n"
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.tidy_pr.generate_tidy_pr", return_value=pr_text),
        ):
            result = runner.invoke(app, ["futures", "tidy-pr"])
        assert result.exit_code == 0
        assert "Tidy" in result.output or "auth_check" in result.output

    def test_output_file(self, tmp_path):
        mock_conn = MagicMock()
        pr_text = "---\ntitle: Tidy PR\n---\n"
        out_file = str(tmp_path / "tidy.md")
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.tidy_pr.generate_tidy_pr", return_value=pr_text),
        ):
            result = runner.invoke(app, ["futures", "tidy-pr", "--output", out_file])
        assert result.exit_code == 0
        import pathlib
        assert pathlib.Path(out_file).read_text() == pr_text

    def test_since_option_passed(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.tidy_pr.generate_tidy_pr", return_value="---\n---\n") as mock_gen,
        ):
            runner.invoke(app, ["futures", "tidy-pr", "--since", "2025-01-01"])
        assert mock_gen.call_args.kwargs.get("since") == "2025-01-01"

    def test_limit_option_passed(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.tidy_pr.generate_tidy_pr", return_value="---\n---\n") as mock_gen,
        ):
            runner.invoke(app, ["futures", "tidy-pr", "--limit", "5"])
        assert mock_gen.call_args.kwargs.get("limit") == 5
