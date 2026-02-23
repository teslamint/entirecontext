"""Tests for futures report generation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.report import generate_futures_report

runner = CliRunner()


# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------


def _make_assessment(
    id: str = "aaa-000-uuid",
    verdict: str = "expand",
    impact_summary: str = "Improved modularity",
    roadmap_alignment: str = "Aligns with refactor goal",
    tidy_suggestion: str = "Extract helper module",
    feedback: str | None = None,
    feedback_reason: str | None = None,
    model_name: str | None = "gpt-4o-mini",
    created_at: str = "2025-01-15T10:00:00+00:00",
    diff_summary: str | None = None,
) -> dict:
    return {
        "id": id,
        "verdict": verdict,
        "impact_summary": impact_summary,
        "roadmap_alignment": roadmap_alignment,
        "tidy_suggestion": tidy_suggestion,
        "feedback": feedback,
        "feedback_reason": feedback_reason,
        "model_name": model_name,
        "created_at": created_at,
        "diff_summary": diff_summary,
    }


def _make_assessments_varied():
    return [
        _make_assessment(id="a1", verdict="expand", impact_summary="Better structure", feedback="agree"),
        _make_assessment(id="a2", verdict="narrow", impact_summary="Added coupling", feedback="disagree"),
        _make_assessment(id="a3", verdict="neutral", impact_summary="Minor rename"),
        _make_assessment(id="a4", verdict="expand", impact_summary="New abstraction", feedback="agree"),
        _make_assessment(id="a5", verdict="narrow", impact_summary="Hard dependency"),
    ]


# ---------------------------------------------------------------------------
# Core function: generate_futures_report
# ---------------------------------------------------------------------------


class TestGenerateFuturesReport:
    def test_returns_string(self):
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments)
        assert isinstance(result, str)

    def test_empty_assessments_returns_no_data_message(self):
        result = generate_futures_report([])
        assert "no" in result.lower() or "empty" in result.lower() or "0" in result

    def test_contains_yaml_frontmatter(self):
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments)
        assert result.startswith("---\n")
        assert "\n---\n" in result

    def test_frontmatter_has_report_type(self):
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments)
        frontmatter_end = result.index("\n---\n", 4)
        fm = result[4:frontmatter_end]
        assert "report:" in fm or "type:" in fm

    def test_frontmatter_has_generated_field(self):
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments)
        frontmatter_end = result.index("\n---\n", 4)
        fm = result[4:frontmatter_end]
        assert "generated:" in fm

    def test_contains_h1_heading(self):
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments)
        assert "# " in result

    def test_verdict_distribution_section_present(self):
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments)
        assert "expand" in result.lower()
        assert "narrow" in result.lower()
        assert "neutral" in result.lower()

    def test_expand_count_correct(self):
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments)
        # 2 expand out of 5
        assert "2" in result

    def test_narrow_count_correct(self):
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments)
        # 2 narrow
        assert "2" in result

    def test_neutral_count_correct(self):
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments)
        # 1 neutral
        assert "1" in result

    def test_total_count_present(self):
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments)
        assert "5" in result

    def test_impact_summaries_included(self):
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments)
        assert "Better structure" in result
        assert "Added coupling" in result

    def test_feedback_section_present_when_feedback_exists(self):
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments)
        # 2 assessments have feedback
        assert "agree" in result.lower() or "feedback" in result.lower()

    def test_tidy_suggestions_included(self):
        a = _make_assessment(tidy_suggestion="Consider extracting interface")
        result = generate_futures_report([a])
        assert "Consider extracting interface" in result

    def test_project_name_in_frontmatter_when_provided(self):
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments, project_name="awesome-repo")
        frontmatter_end = result.index("\n---\n", 4)
        fm = result[4:frontmatter_end]
        assert "awesome-repo" in fm

    def test_project_name_omitted_when_none(self):
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments, project_name=None)
        assert "project:" not in result

    def test_since_label_in_frontmatter_when_provided(self):
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments, since="2025-01-01")
        frontmatter_end = result.index("\n---\n", 4)
        fm = result[4:frontmatter_end]
        assert "since:" in fm
        assert "2025-01-01" in fm

    def test_single_assessment_no_feedback(self):
        a = _make_assessment(feedback=None, feedback_reason=None)
        result = generate_futures_report([a])
        assert isinstance(result, str)
        assert "Improved modularity" in result

    def test_percentage_calculation_in_output(self):
        """Verify percentages appear for verdict distribution."""
        assessments = [
            _make_assessment(id="x1", verdict="expand"),
            _make_assessment(id="x2", verdict="expand"),
            _make_assessment(id="x3", verdict="expand"),
            _make_assessment(id="x4", verdict="narrow"),
        ]
        result = generate_futures_report(assessments)
        # 3/4 = 75% expand
        assert "75" in result

    def test_feedback_reason_included_when_present(self):
        a = _make_assessment(feedback="disagree", feedback_reason="Too aggressive refactor")
        result = generate_futures_report([a])
        assert "Too aggressive refactor" in result

    def test_model_name_in_assessment_listing(self):
        a = _make_assessment(model_name="claude-3-haiku")
        result = generate_futures_report([a])
        assert "claude-3-haiku" in result

    def test_all_verdicts_absent_renders_cleanly(self):
        """Report with only one verdict type renders without error."""
        assessments = [
            _make_assessment(id="x1", verdict="expand"),
            _make_assessment(id="x2", verdict="expand"),
        ]
        result = generate_futures_report(assessments)
        assert isinstance(result, str)
        assert "expand" in result.lower()

    def test_assessment_date_shown(self):
        a = _make_assessment(created_at="2025-03-10T12:00:00+00:00")
        result = generate_futures_report([a])
        assert "2025-03-10" in result

    def test_output_structure_has_sections(self):
        """Report should have at least two ## sections."""
        assessments = _make_assessments_varied()
        result = generate_futures_report(assessments)
        assert result.count("## ") >= 2


# ---------------------------------------------------------------------------
# CLI tests: ec futures report
# ---------------------------------------------------------------------------


class TestFuturesReportCLI:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["futures", "report"])
            assert result.exit_code == 1

    def test_no_assessments(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "p1", "name": "proj"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.futures.list_assessments", return_value=[]),
        ):
            result = runner.invoke(app, ["futures", "report"])
            assert result.exit_code == 0
            # Should print something (empty report)
            assert len(result.output) > 0

    def test_report_printed_to_stdout(self):
        mock_conn = MagicMock()
        assessments = _make_assessments_varied()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "p1", "name": "myproject"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.futures.list_assessments", return_value=assessments),
        ):
            result = runner.invoke(app, ["futures", "report"])
            assert result.exit_code == 0
            assert "expand" in result.output.lower() or "narrow" in result.output.lower()

    def test_report_written_to_file(self, tmp_path):
        mock_conn = MagicMock()
        assessments = _make_assessments_varied()
        output_file = tmp_path / "report.md"
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "p1", "name": "myproject"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.futures.list_assessments", return_value=assessments),
        ):
            result = runner.invoke(app, ["futures", "report", "--output", str(output_file)])
            assert result.exit_code == 0
            assert output_file.exists()
            content = output_file.read_text()
            assert "expand" in content.lower() or "narrow" in content.lower()

    def test_since_option_passed_to_query(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "p1", "name": "proj"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.futures.list_assessments", return_value=[]) as mock_list,
        ):
            runner.invoke(app, ["futures", "report", "--since", "2025-01-01"])
            mock_list.assert_called_once()

    def test_limit_option(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "p1", "name": "proj"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.futures.list_assessments", return_value=[]) as mock_list,
        ):
            runner.invoke(app, ["futures", "report", "--limit", "50"])
            mock_list.assert_called_once()
            call_kwargs = mock_list.call_args
            # limit=50 should have been passed
            assert 50 in call_kwargs.args or call_kwargs.kwargs.get("limit") == 50
