"""Tests for `ec session backfill-applied` CLI command."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.decisions import create_decision, link_decision_to_file
from entirecontext.core.session import create_session
from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection
from entirecontext.core.turn import create_turn

runner = CliRunner()


def _seed_eligible_session(conn):
    """Create a session with a decision retrieval selection and file overlap."""
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

    session = create_session(conn, project_id, session_type="claude")
    session_id = session["id"]

    turn = create_turn(
        conn,
        session_id,
        turn_number=1,
        user_message="implement feature X",
        files_touched=json.dumps(["src/foo.py"]),
    )

    conn.execute(
        "UPDATE sessions SET ended_at = datetime('now') WHERE id = ?",
        (session_id,),
    )

    decision = create_decision(conn, title="Use approach A", rationale="simpler")
    link_decision_to_file(conn, decision["id"], "src/foo.py")

    event = record_retrieval_event(
        conn,
        source="hook",
        search_type="decision_surface",
        target="decisions",
        query="feature X",
        result_count=1,
        latency_ms=10,
        session_id=session_id,
        turn_id=turn["id"],
    )
    record_retrieval_selection(
        conn,
        event["id"],
        result_type="decision",
        result_id=decision["id"],
        session_id=session_id,
        turn_id=turn["id"],
    )

    return session_id, decision["id"]


class _NoCloseConn:
    """Wraps a connection and makes close() a no-op so the fixture keeps ownership."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass  # fixture owns the connection; CLI must not close it


def test_backfill_applied_dry_run(ec_db, ec_repo, monkeypatch):
    """Dry run reports candidates without writing."""
    conn = ec_db
    _seed_eligible_session(conn)

    monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda: str(ec_repo))
    monkeypatch.setattr("entirecontext.core.project.get_project", lambda _: {"id": "proj-1"})
    monkeypatch.setattr("entirecontext.db.get_db", lambda _: _NoCloseConn(conn))

    result = runner.invoke(app, ["session", "backfill-applied", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert "--apply" in result.output

    apps = conn.execute("SELECT COUNT(*) FROM context_applications").fetchone()[0]
    assert apps == 0


def test_backfill_applied_apply(ec_db, ec_repo, monkeypatch):
    """--apply actually writes applications."""
    conn = ec_db
    _seed_eligible_session(conn)

    monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda: str(ec_repo))
    monkeypatch.setattr("entirecontext.core.project.get_project", lambda _: {"id": "proj-1"})
    monkeypatch.setattr("entirecontext.db.get_db", lambda _: _NoCloseConn(conn))

    result = runner.invoke(app, ["session", "backfill-applied", "--apply"])
    assert result.exit_code == 0, result.output
    assert "Applied" in result.output

    apps = conn.execute("SELECT COUNT(*) FROM context_applications").fetchone()[0]
    assert apps >= 1
