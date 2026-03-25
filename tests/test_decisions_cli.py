"""CLI tests for decision commands."""

from __future__ import annotations

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.checkpoint import create_checkpoint
from entirecontext.core.decisions import create_decision
from entirecontext.core.futures import create_assessment
from entirecontext.core.project import get_project
from entirecontext.core.session import create_session
from entirecontext.db import get_db

runner = CliRunner()


class TestDecisionsCLI:
    def test_create_list_show(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)

        result = runner.invoke(app, ["decision", "create", "Use idempotency keys", "--scope", "payments"])
        assert result.exit_code == 0
        assert "Created decision:" in result.stdout

        result = runner.invoke(app, ["decision", "list"])
        assert result.exit_code == 0
        assert "Use idempotency keys" in result.stdout

        conn = get_db(str(ec_repo))
        decision_id = conn.execute("SELECT id FROM decisions LIMIT 1").fetchone()["id"]
        conn.close()

        result = runner.invoke(app, ["decision", "show", decision_id[:12]])
        assert result.exit_code == 0
        assert "Use idempotency keys" in result.stdout

    def test_link_assessment_and_file_and_checkpoint(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Adopt queue")
        assessment = create_assessment(conn, verdict="expand", impact_summary="good")
        project = get_project(str(ec_repo))
        session = create_session(conn, project["id"], session_id="decision-cli-session")
        checkpoint = create_checkpoint(conn, session["id"], git_commit_hash="abc123", git_branch="main")
        conn.close()

        result = runner.invoke(
            app,
            [
                "decision",
                "link",
                decision["id"][:12],
                "--assessment",
                assessment["id"][:12],
                "--relation-type",
                "supports",
            ],
        )
        assert result.exit_code == 0

        result = runner.invoke(
            app, ["decision", "link", decision["id"][:12], "--file", "src/entirecontext/core/search.py"]
        )
        assert result.exit_code == 0

        result = runner.invoke(app, ["decision", "link", decision["id"][:12], "--checkpoint", checkpoint["id"][:12]])
        assert result.exit_code == 0

    def test_stale_and_error_cases(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="x")
        conn.close()

        ok = runner.invoke(app, ["decision", "stale", decision["id"][:12], "--status", "stale"])
        assert ok.exit_code == 0
        assert "-> stale" in ok.stdout

        bad = runner.invoke(app, ["decision", "stale", decision["id"][:12], "--status", "invalid"])
        assert bad.exit_code == 1

        invalid_link = runner.invoke(
            app,
            ["decision", "link", decision["id"][:12], "--assessment", "a", "--file", "src/x.py"],
        )
        assert invalid_link.exit_code == 1
