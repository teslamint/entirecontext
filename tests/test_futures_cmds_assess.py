"""Tests for futures CLI commands — assess, list, feedback, lessons."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.checkpoint import create_checkpoint
from entirecontext.core.futures import add_feedback, create_assessment
from entirecontext.core.project import get_project
from entirecontext.core.session import create_session
from entirecontext.db import get_db

runner = CliRunner()


def test_assess_staged_diff_success(ec_repo, monkeypatch):
    monkeypatch.chdir(ec_repo)
    llm_result = {
        "verdict": "expand",
        "impact_summary": "good",
        "roadmap_alignment": "aligned",
        "tidy_suggestion": "keep going",
    }
    with (
        patch("entirecontext.cli.futures_cmds._get_staged_diff", return_value="diff text"),
        patch("entirecontext.cli.futures_cmds._call_llm", return_value=llm_result),
    ):
        result = runner.invoke(app, ["futures", "assess"])
    assert result.exit_code == 0
    conn = get_db(str(ec_repo))
    row = conn.execute("SELECT * FROM assessments").fetchone()
    conn.close()
    assert row is not None
    assert row["verdict"] == "expand"
    assert row["impact_summary"] == "good"


def test_assess_checkpoint_success(ec_repo, monkeypatch):
    monkeypatch.chdir(ec_repo)
    conn = get_db(str(ec_repo))
    project = get_project(str(ec_repo))
    session = create_session(conn, project["id"], session_id="assess-ckpt-session")
    checkpoint = create_checkpoint(
        conn, session["id"], git_commit_hash="abc123", git_branch="main", diff_summary="checkpoint diff"
    )
    conn.close()

    llm_result = {
        "verdict": "narrow",
        "impact_summary": "risky",
        "roadmap_alignment": "off track",
        "tidy_suggestion": "reconsider",
    }
    with patch("entirecontext.cli.futures_cmds._call_llm", return_value=llm_result):
        result = runner.invoke(app, ["futures", "assess", "--checkpoint", checkpoint["id"][:12]])
    assert result.exit_code == 0

    conn = get_db(str(ec_repo))
    row = conn.execute("SELECT * FROM assessments").fetchone()
    conn.close()
    assert row is not None
    assert row["verdict"] == "narrow"
    assert row["checkpoint_id"] == checkpoint["id"]


def test_assess_checkpoint_not_found(ec_repo, monkeypatch):
    monkeypatch.chdir(ec_repo)
    result = runner.invoke(app, ["futures", "assess", "--checkpoint", "nonexistent-id"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_assess_no_staged_diff(ec_repo, monkeypatch):
    monkeypatch.chdir(ec_repo)
    with patch("entirecontext.cli.futures_cmds._get_staged_diff", return_value=""):
        result = runner.invoke(app, ["futures", "assess"])
    assert result.exit_code == 1
    assert "No staged changes" in result.output


def test_assess_llm_error(ec_repo, monkeypatch):
    monkeypatch.chdir(ec_repo)
    with (
        patch("entirecontext.cli.futures_cmds._get_staged_diff", return_value="diff text"),
        patch("entirecontext.cli.futures_cmds._call_llm", side_effect=RuntimeError("API timeout")),
    ):
        result = runner.invoke(app, ["futures", "assess"])
    assert result.exit_code == 1
    assert "LLM call failed" in result.output


def test_list_default(ec_repo, monkeypatch):
    monkeypatch.chdir(ec_repo)
    conn = get_db(str(ec_repo))
    a1 = create_assessment(conn, verdict="expand", impact_summary="first assessment")
    a2 = create_assessment(conn, verdict="narrow", impact_summary="second assessment")
    conn.close()

    result = runner.invoke(app, ["futures", "list"])
    assert result.exit_code == 0
    assert a1["id"][:12] in result.output
    assert a2["id"][:12] in result.output


def test_list_filter_by_verdict(ec_repo, monkeypatch):
    monkeypatch.chdir(ec_repo)
    conn = get_db(str(ec_repo))
    a_expand = create_assessment(conn, verdict="expand", impact_summary="expander")
    a_narrow = create_assessment(conn, verdict="narrow", impact_summary="narrower")
    conn.close()

    result = runner.invoke(app, ["futures", "list", "--verdict", "expand"])
    assert result.exit_code == 0
    assert a_expand["id"][:12] in result.output
    assert a_narrow["id"][:12] not in result.output


def test_list_empty(ec_repo, monkeypatch):
    monkeypatch.chdir(ec_repo)
    result = runner.invoke(app, ["futures", "list"])
    assert result.exit_code == 0
    assert "No assessments found" in result.output


def test_feedback_agree(ec_repo, monkeypatch):
    monkeypatch.chdir(ec_repo)
    conn = get_db(str(ec_repo))
    assessment = create_assessment(conn, verdict="expand", impact_summary="test feedback")
    conn.close()

    with (
        patch("entirecontext.core.futures.auto_distill_lessons", return_value=False),
        patch("entirecontext.core.config.load_config", return_value={}),
    ):
        result = runner.invoke(app, ["futures", "feedback", assessment["id"][:12], "agree"])
    assert result.exit_code == 0
    assert "Feedback recorded" in result.output


def test_lessons_output(ec_repo, monkeypatch, tmp_path):
    monkeypatch.chdir(ec_repo)
    conn = get_db(str(ec_repo))
    a = create_assessment(conn, verdict="expand", impact_summary="lesson one")
    add_feedback(conn, a["id"], "agree")
    conn.close()

    output_file = tmp_path / "test_lessons.md"
    result = runner.invoke(app, ["futures", "lessons", "--output", str(output_file)])
    assert result.exit_code == 0
    assert output_file.exists()
    content = output_file.read_text()
    assert "lesson one" in content
