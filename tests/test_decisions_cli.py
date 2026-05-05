"""CLI tests for decision commands."""

from __future__ import annotations

import sqlite3

import pytest
from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.checkpoint import create_checkpoint
from entirecontext.core.decisions import create_decision
from entirecontext.core.futures import create_assessment
from entirecontext.core.project import get_project
from entirecontext.core.session import create_session
from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection
from entirecontext.core.turn import create_turn
from entirecontext.db import SCHEMA_VERSION, get_db, get_current_version
from entirecontext.db.migrations.v009 import MIGRATION_STEPS as V009_MIGRATION_STEPS

runner = CliRunner()


def _seed_v9_decision_repo(repo_path, *, decision_id: str | None = None) -> str:
    conn = get_db(str(repo_path))
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT, description TEXT)")
    conn.execute("INSERT INTO schema_version (version, description) VALUES (9, 'v9')")
    conn.execute("CREATE TABLE assessments (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE checkpoints (id TEXT PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE retrieval_selections (id TEXT PRIMARY KEY, result_type TEXT, result_id TEXT, session_id TEXT, turn_id TEXT)"
    )
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE turns (id TEXT PRIMARY KEY)")
    for statement in V009_MIGRATION_STEPS:
        conn.execute(statement)

    seeded_decision_id = decision_id or "11111111-2222-3333-4444-555555555555"
    conn.execute(
        """
        INSERT INTO decisions (
            id, title, rationale, scope, staleness_status, rejected_alternatives,
            supporting_evidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            seeded_decision_id,
            "Legacy decision",
            "carry forward compatibility",
            "cli",
            "fresh",
            "[]",
            "[]",
            "2025-01-01T00:00:00Z",
            "2025-01-01T00:00:00Z",
        ),
    )
    conn.commit()
    conn.close()
    return seeded_decision_id


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

        result = runner.invoke(app, ["decision", "link", decision["id"][:12], "--commit", "abc999"])
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

    def test_outcome_records_and_show_displays_quality(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Use queue retries")
        project = get_project(str(ec_repo))
        session = create_session(conn, project["id"], session_id="decision-cli-outcome")
        turn = create_turn(conn, session["id"], 1, user_message="search retries", assistant_summary="found decision")
        event = record_retrieval_event(
            conn,
            source="cli",
            search_type="decision_related",
            target="decision",
            query="retries",
            result_count=1,
            latency_ms=5,
            session_id=session["id"],
            turn_id=turn["id"],
        )
        selection = record_retrieval_selection(conn, event["id"], "decision", decision["id"])
        conn.close()

        result = runner.invoke(
            app,
            [
                "decision",
                "outcome",
                decision["id"][:12],
                "--outcome",
                "accepted",
                "--selection-id",
                selection["id"],
                "--note",
                "Applied in retry worker",
            ],
        )
        assert result.exit_code == 0
        assert "Recorded decision outcome:" in result.stdout

        show = runner.invoke(app, ["decision", "show", decision["id"][:12]])
        assert show.exit_code == 0
        assert "accepted=1" in show.stdout
        assert "Recent outcomes:" in show.stdout

    def test_show_migrates_v9_repo_before_querying_outcomes(self, git_repo, monkeypatch):
        monkeypatch.chdir(git_repo)
        decision_id = _seed_v9_decision_repo(git_repo)

        conn = get_db(str(git_repo))
        assert get_current_version(conn) == 9
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("SELECT 1 FROM decision_outcomes LIMIT 1").fetchone()
        conn.close()

        result = runner.invoke(app, ["decision", "show", decision_id[:12]])

        assert result.exit_code == 0
        assert "Legacy decision" in result.stdout

        conn = get_db(str(git_repo))
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = 'decision_outcomes'"
        ).fetchone()
        version = get_current_version(conn)
        conn.close()

        assert table is not None
        assert version == SCHEMA_VERSION

    def test_create_migrates_v9_repo_before_querying_outcomes(self, git_repo, monkeypatch):
        monkeypatch.chdir(git_repo)
        _seed_v9_decision_repo(git_repo)

        result = runner.invoke(app, ["decision", "create", "Upgrade-safe decision"])

        assert result.exit_code == 0
        assert "Created decision:" in result.stdout

        conn = get_db(str(git_repo))
        created = conn.execute("SELECT title FROM decisions WHERE title = ?", ("Upgrade-safe decision",)).fetchone()
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = 'decision_outcomes'"
        ).fetchone()
        version = get_current_version(conn)
        conn.close()

        assert created is not None
        assert table is not None
        assert version == SCHEMA_VERSION

    def test_outcome_rejects_invalid_selection(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Use queue retries")
        project = get_project(str(ec_repo))
        session = create_session(conn, project["id"], session_id="decision-cli-outcome-invalid")
        turn = create_turn(conn, session["id"], 1, user_message="search retries", assistant_summary="found turn")
        event = record_retrieval_event(
            conn,
            source="cli",
            search_type="regex",
            target="turn",
            query="retries",
            result_count=1,
            latency_ms=5,
            session_id=session["id"],
            turn_id=turn["id"],
        )
        selection = record_retrieval_selection(conn, event["id"], "turn", "t1")
        conn.close()

        result = runner.invoke(
            app,
            ["decision", "outcome", decision["id"][:12], "--outcome", "accepted", "--selection-id", selection["id"]],
        )
        assert result.exit_code == 1

    def test_outcome_uses_selection_context_when_current_session_has_no_turns(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Use queue retries")
        project = get_project(str(ec_repo))
        source_session = create_session(conn, project["id"], session_id="decision-cli-source")
        source_turn = create_turn(
            conn, source_session["id"], 1, user_message="search retries", assistant_summary="found decision"
        )
        event = record_retrieval_event(
            conn,
            source="cli",
            search_type="decision_related",
            target="decision",
            query="retries",
            result_count=1,
            latency_ms=5,
            session_id=source_session["id"],
            turn_id=source_turn["id"],
        )
        selection = record_retrieval_selection(conn, event["id"], "decision", decision["id"])
        create_session(conn, project["id"], session_id="decision-cli-current-empty")
        conn.close()

        result = runner.invoke(
            app,
            ["decision", "outcome", decision["id"][:12], "--outcome", "accepted", "--selection-id", selection["id"]],
        )
        assert result.exit_code == 0

        conn = get_db(str(ec_repo))
        row = conn.execute(
            "SELECT session_id, turn_id FROM decision_outcomes WHERE retrieval_selection_id = ?",
            (selection["id"],),
        ).fetchone()
        conn.close()

        assert row["session_id"] == source_session["id"]
        assert row["turn_id"] == source_turn["id"]

    @pytest.mark.parametrize(
        ("argv", "patched_symbol"),
        [
            (["decision", "create", "Use idempotency keys"], "create_decision"),
            (["decision", "show", "decision-123"], "get_decision"),
        ],
    )
    def test_create_and_show_close_connection_on_exception(self, ec_repo, monkeypatch, argv, patched_symbol):
        monkeypatch.chdir(ec_repo)

        class SpyConnection:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        conn = SpyConnection()

        def raise_error(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr("entirecontext.db.get_db", lambda repo_path: conn)
        monkeypatch.setattr("entirecontext.db.check_and_migrate", lambda db_conn: None)
        monkeypatch.setattr(f"entirecontext.core.decisions.{patched_symbol}", raise_error)

        result = runner.invoke(app, argv)

        assert result.exit_code == 1
        assert isinstance(result.exception, RuntimeError)
        assert conn.closed is True

    @pytest.mark.parametrize("outcome_type", ["refined", "replaced"])
    def test_outcome_accepts_new_values(self, outcome_type, ec_repo, monkeypatch):
        """CLI must accept 'refined' and 'replaced' without error."""
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Test new outcome types")
        conn.close()

        result = runner.invoke(
            app,
            ["decision", "outcome", decision["id"][:12], "--outcome", outcome_type],
        )
        assert result.exit_code == 0, result.stdout
        assert "Recorded decision outcome:" in result.stdout

    def test_outcome_still_rejects_invalid_value(self, ec_repo, monkeypatch):
        """Invalid outcome values must still be rejected after enum expansion."""
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Test invalid outcome")
        conn.close()

        result = runner.invoke(
            app,
            ["decision", "outcome", decision["id"][:12], "--outcome", "unknown_value"],
        )
        assert result.exit_code == 1


class TestDecisionsCLIExtended:
    def test_decision_update_success(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Old title", rationale="Old rationale")
        conn.close()

        result = runner.invoke(
            app, ["decision", "update", decision["id"][:12], "--title", "New Title", "--rationale", "New Rationale"]
        )
        assert result.exit_code == 0
        assert "Updated decision:" in result.stdout
        assert "New Title" in result.stdout

    def test_decision_supersede_success(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        old = create_decision(conn, title="Old approach")
        new = create_decision(conn, title="New approach")
        conn.close()

        result = runner.invoke(app, ["decision", "supersede", old["id"][:12], new["id"][:12]])
        assert result.exit_code == 0
        assert "superseded" in result.stdout.lower()

    def test_decision_chain_includes_terminal_at_depth_cap(self, ec_repo, monkeypatch):
        from entirecontext.core.decisions import _SUCCESSOR_CHAIN_DEPTH_CAP, supersede_decision

        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        chain = [create_decision(conn, title=f"Decision {idx}") for idx in range(_SUCCESSOR_CHAIN_DEPTH_CAP + 1)]
        for old, new in zip(chain, chain[1:]):
            supersede_decision(conn, old["id"], new["id"])
        conn.close()

        result = runner.invoke(app, ["decision", "chain", chain[0]["id"][:12]])

        assert result.exit_code == 0
        assert chain[-1]["id"][:12] in result.stdout
        assert f"Decision {_SUCCESSOR_CHAIN_DEPTH_CAP}" in result.stdout

    def test_decision_unlink_file_success(self, ec_repo, monkeypatch):
        from entirecontext.core.decisions import link_decision_to_file

        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Unlink test")
        link_decision_to_file(conn, decision["id"], "src/foo.py")
        conn.close()

        result = runner.invoke(app, ["decision", "unlink", decision["id"][:12], "--file", "src/foo.py"])
        assert result.exit_code == 0
        assert "Link removed" in result.stdout

    def test_decision_unlink_assessment_success(self, ec_repo, monkeypatch):
        from entirecontext.core.decisions import link_decision_to_assessment

        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Unlink assessment test")
        assessment = create_assessment(conn, verdict="expand", impact_summary="test")
        link_decision_to_assessment(conn, decision["id"], assessment["id"])
        conn.close()

        result = runner.invoke(app, ["decision", "unlink", decision["id"][:12], "--assessment", assessment["id"][:12]])
        assert result.exit_code == 0
        assert "Link removed" in result.stdout

    def test_decision_unlink_checkpoint_success(self, ec_repo, monkeypatch):
        from entirecontext.core.decisions import link_decision_to_checkpoint

        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Unlink checkpoint test")
        project = get_project(str(ec_repo))
        session = create_session(conn, project["id"], session_id="unlink-ckpt-session")
        checkpoint = create_checkpoint(conn, session["id"], git_commit_hash="abc123", git_branch="main")
        link_decision_to_checkpoint(conn, decision["id"], checkpoint["id"])
        conn.close()

        result = runner.invoke(app, ["decision", "unlink", decision["id"][:12], "--checkpoint", checkpoint["id"][:12]])
        assert result.exit_code == 0
        assert "Link removed" in result.stdout

    def test_decision_unlink_commit_success(self, ec_repo, monkeypatch):
        from entirecontext.core.decisions import link_decision_to_commit

        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Unlink commit test")
        link_decision_to_commit(conn, decision["id"], "deadbeef")
        conn.close()

        result = runner.invoke(app, ["decision", "unlink", decision["id"][:12], "--commit", "deadbeef"])
        assert result.exit_code == 0
        assert "Link removed" in result.stdout

    def test_decision_unlink_no_args_error(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        decision = create_decision(conn, title="Unlink error test")
        conn.close()

        result = runner.invoke(app, ["decision", "unlink", decision["id"][:12]])
        assert result.exit_code == 1
        assert "Exactly one" in result.stdout

    def test_decision_stale_all_no_stale(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        create_decision(conn, title="Fresh decision")
        conn.close()

        monkeypatch.setattr(
            "entirecontext.core.decisions.check_staleness",
            lambda conn, did, rp: {"stale": False, "changed_files": []},
        )

        result = runner.invoke(app, ["decision", "stale-all"])
        assert result.exit_code == 0
        assert "up to date" in result.stdout

    def test_decision_stale_all_found_stale(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        create_decision(conn, title="Stale candidate")
        conn.close()

        monkeypatch.setattr(
            "entirecontext.core.decisions.check_staleness",
            lambda conn, did, rp: {"stale": True, "changed_files": ["a.py"]},
        )

        result = runner.invoke(app, ["decision", "stale-all"])
        assert result.exit_code == 0
        assert "1/" in result.stdout
        assert "stale" in result.stdout.lower()

    def test_extract_from_session_success(self, ec_repo, monkeypatch):
        import json

        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        project = get_project(str(ec_repo))
        session = create_session(conn, project["id"], session_id="extract-session")
        create_turn(
            conn,
            session["id"],
            1,
            user_message="how to handle auth",
            assistant_summary="Decided to use JWT over sessions",
            files_touched=json.dumps(["src/auth.py"]),
        )
        conn.close()

        llm_response = json.dumps([{"title": "Use JWT", "rationale": "Stateless auth", "scope": "auth"}])
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda summaries, repo_path: llm_response,
        )

        result = runner.invoke(app, ["decision", "extract-from-session", session["id"]])
        assert result.exit_code == 0

        conn = get_db(str(ec_repo))
        # Candidate row (not decision) is produced; decisions table stays empty.
        row = conn.execute("SELECT * FROM decision_candidates WHERE title = 'Use JWT'").fetchone()
        assert row is not None
        assert row["review_status"] == "pending"
        assert row["source_type"] == "session"
        decision_count = conn.execute("SELECT COUNT(*) AS c FROM decisions").fetchone()["c"]
        assert decision_count == 0

        meta = json.loads(
            conn.execute("SELECT metadata FROM sessions WHERE id = ?", (session["id"],)).fetchone()["metadata"]
        )
        assert meta.get("candidates_extracted") is True
        conn.close()

    def test_extract_from_session_idempotent(self, ec_repo, monkeypatch):
        import json

        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        project = get_project(str(ec_repo))
        session = create_session(conn, project["id"], session_id="extract-idempotent")
        create_turn(
            conn,
            session["id"],
            1,
            user_message="auth",
            assistant_summary="Decided to use JWT",
        )
        conn.execute(
            "UPDATE sessions SET metadata = ? WHERE id = ?",
            (json.dumps({"decisions_extracted": True}), session["id"]),
        )
        conn.commit()
        conn.close()

        call_count = 0

        def mock_llm(summaries, repo_path):
            nonlocal call_count
            call_count += 1
            return "[]"

        monkeypatch.setattr("entirecontext.cli.decisions_cmds._get_llm_response", mock_llm)

        result = runner.invoke(app, ["decision", "extract-from-session", session["id"]])
        assert result.exit_code == 0
        assert call_count == 0

    def test_extract_from_session_no_turns(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        project = get_project(str(ec_repo))
        create_session(conn, project["id"], session_id="extract-empty")
        conn.close()

        call_count = 0

        def mock_llm(summaries, repo_path):
            nonlocal call_count
            call_count += 1
            return "[]"

        monkeypatch.setattr("entirecontext.cli.decisions_cmds._get_llm_response", mock_llm)

        result = runner.invoke(app, ["decision", "extract-from-session", "extract-empty"])
        assert result.exit_code == 0
        assert call_count == 0

    def test_extract_from_session_invalid_llm_json(self, ec_repo, monkeypatch):
        monkeypatch.chdir(ec_repo)
        conn = get_db(str(ec_repo))
        project = get_project(str(ec_repo))
        session = create_session(conn, project["id"], session_id="extract-bad-json")
        create_turn(
            conn,
            session["id"],
            1,
            user_message="test",
            assistant_summary="Decided something important",
        )
        conn.close()

        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda summaries, repo_path: "NOT VALID JSON {{{",
        )

        result = runner.invoke(app, ["decision", "extract-from-session", session["id"]])
        assert result.exit_code == 0

        conn = get_db(str(ec_repo))
        count = conn.execute("SELECT count(*) as c FROM decisions").fetchone()["c"]
        conn.close()
        assert count == 0
