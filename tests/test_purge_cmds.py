"""Tests for purge CLI commands."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.session import create_session
from entirecontext.core.turn import create_turn
from entirecontext.db import get_db

runner = CliRunner()


@pytest.fixture
def seeded_repo(ec_repo):
    conn = get_db(str(ec_repo))
    project = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
    session = create_session(conn, project["id"], session_id="purge-session")
    create_turn(conn, session["id"], 1, user_message="fix auth bug", assistant_summary="Fixed it")
    create_turn(conn, session["id"], 2, user_message="add password=secret123", assistant_summary="Added password")
    create_turn(conn, session["id"], 3, user_message="refactor code", assistant_summary="Refactored")
    from entirecontext.core.session import update_session

    update_session(conn, session["id"], ended_at="2025-01-02T00:00:00+00:00")
    conn.close()
    return ec_repo


class TestPurgeCmds:
    def test_purge_session_dry_run(self, seeded_repo, monkeypatch):
        monkeypatch.chdir(seeded_repo)
        result = runner.invoke(app, ["purge", "session", "purge-session"])
        assert result.exit_code == 0
        assert "DRY RUN" in result.output

        conn = get_db(str(seeded_repo))
        assert conn.execute("SELECT * FROM sessions WHERE id = 'purge-session'").fetchone() is not None
        conn.close()

    def test_purge_session_execute(self, seeded_repo, monkeypatch):
        monkeypatch.chdir(seeded_repo)
        result = runner.invoke(app, ["purge", "session", "purge-session", "--execute", "--force"])
        assert result.exit_code == 0
        assert "Deleted" in result.output

        conn = get_db(str(seeded_repo))
        assert conn.execute("SELECT * FROM sessions WHERE id = 'purge-session'").fetchone() is None
        conn.close()

    def test_purge_turn_execute(self, seeded_repo, monkeypatch):
        monkeypatch.chdir(seeded_repo)
        conn = get_db(str(seeded_repo))
        turn = conn.execute("SELECT id FROM turns WHERE session_id = 'purge-session' LIMIT 1").fetchone()
        turn_id = turn["id"]
        conn.close()

        result = runner.invoke(app, ["purge", "turn", turn_id, "--execute"])
        assert result.exit_code == 0
        assert "Deleted" in result.output

        conn = get_db(str(seeded_repo))
        assert conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone() is None
        conn.close()

    def test_purge_match_dry_run(self, seeded_repo, monkeypatch):
        monkeypatch.chdir(seeded_repo)
        result = runner.invoke(app, ["purge", "match", "password"])
        assert result.exit_code == 0
        assert "DRY RUN" in result.output

    def test_purge_match_execute_force(self, seeded_repo, monkeypatch):
        monkeypatch.chdir(seeded_repo)
        result = runner.invoke(app, ["purge", "match", "password", "--execute", "--force"])
        assert result.exit_code == 0
        assert "Deleted" in result.output

        conn = get_db(str(seeded_repo))
        remaining = conn.execute("SELECT * FROM turns WHERE session_id = 'purge-session'").fetchall()
        assert len(remaining) == 2
        assert all("password" not in (r["user_message"] or "") for r in remaining)
        conn.close()
