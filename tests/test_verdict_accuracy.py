from __future__ import annotations

from datetime import datetime, timezone

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.auto_assess import compute_verdict_accuracy

runner = CliRunner()


def _create_session(conn, session_id="sess-va"):
    """Insert a minimal valid session and return its id."""
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO sessions (id, project_id, session_type, workspace_path, started_at, last_activity_at)"
        " VALUES (?, ?, 'claude', '/tmp', ?, ?)",
        (session_id, project_id, now, now),
    )
    return session_id


def test_compute_verdict_accuracy_empty(ec_repo, ec_db):
    result = compute_verdict_accuracy(ec_db)
    assert result["total_rule_based"] == 0
    assert result["total_enriched"] == 0
    assert result["agreement_rate"] is None
    assert result["per_verdict"] == {}


def test_compute_verdict_accuracy_with_feedback(ec_repo, ec_db):
    session_id = _create_session(ec_db)
    ec_db.execute(
        "INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch, created_at)"
        " VALUES ('ckp-va-1', ?, 'abc', 'main', datetime('now'))",
        (session_id,),
    )
    ec_db.execute(
        "INSERT INTO assessments (id, checkpoint_id, verdict, model_name, feedback, feedback_reason, created_at)"
        " VALUES ('asmt-va-1', 'ckp-va-1', 'expand', 'claude-cli', 'agree', 'auto:llm-confirmed', datetime('now'))"
    )
    ec_db.execute(
        "INSERT INTO assessments (id, checkpoint_id, verdict, model_name, feedback, feedback_reason, created_at)"
        " VALUES ('asmt-va-2', 'ckp-va-1', 'expand', 'claude-cli', 'disagree', 'auto:revised:neutral->expand', datetime('now'))"
    )
    ec_db.execute(
        "INSERT INTO assessments (id, checkpoint_id, verdict, model_name, feedback, created_at)"
        " VALUES ('asmt-va-3', 'ckp-va-1', 'expand', 'rule-based', NULL, datetime('now'))"
    )

    result = compute_verdict_accuracy(ec_db)
    assert result["total_rule_based"] == 1
    assert result["total_enriched"] == 2
    assert result["agreement_rate"] == 0.5
    assert result["per_verdict"]["expand"]["agree"] == 1
    # disagree attributed to original rule verdict 'neutral', not current 'expand'
    assert result["per_verdict"]["neutral"]["disagree"] == 1


def test_compute_verdict_accuracy_disagree_with_reason(ec_repo, ec_db):
    session_id = _create_session(ec_db)
    ec_db.execute(
        "INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch, created_at)"
        " VALUES ('ckp-va-1', ?, 'abc', 'main', datetime('now'))",
        (session_id,),
    )
    ec_db.execute(
        "INSERT INTO assessments (id, checkpoint_id, verdict, model_name, feedback, feedback_reason, created_at)"
        " VALUES ('asmt-va-1', 'ckp-va-1', 'expand', 'claude-cli', 'disagree',"
        " 'auto:revised:neutral->expand', datetime('now'))"
    )

    result = compute_verdict_accuracy(ec_db)
    # attributed to original 'neutral', not current 'expand'
    assert "neutral" in result["per_verdict"]
    assert result["per_verdict"]["neutral"]["disagree"] == 1
    assert result["agreement_rate"] == 0.0


def test_compute_verdict_accuracy_excludes_manual_feedback(ec_repo, ec_db):
    session_id = _create_session(ec_db)
    ec_db.execute(
        "INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch, created_at)"
        " VALUES ('ckp-va-m', ?, 'abc', 'main', datetime('now'))",
        (session_id,),
    )
    # Manual feedback (no auto: prefix in feedback_reason) should be excluded
    ec_db.execute(
        "INSERT INTO assessments (id, checkpoint_id, verdict, model_name, feedback, feedback_reason, created_at)"
        " VALUES ('asmt-manual', 'ckp-va-m', 'expand', 'mcp-agent', 'agree', 'user manual review', datetime('now'))"
    )

    result = compute_verdict_accuracy(ec_db)
    assert result["total_enriched"] == 0
    assert result["agreement_rate"] is None


def test_assess_accuracy_cli(ec_repo, ec_db, monkeypatch):
    monkeypatch.chdir(ec_repo)
    result = runner.invoke(app, ["checkpoint", "assess-accuracy"])
    assert result.exit_code == 0
    assert "Verdict Accuracy Baseline" in result.output
