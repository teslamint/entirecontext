"""Tests for Layer 2 outcome inference: refined/replaced classification."""

from __future__ import annotations

import json
import subprocess

import pytest

from entirecontext.core.auto_apply import infer_applied_decisions
from entirecontext.core.decisions import create_decision, link_decision_to_file
from entirecontext.core.session import create_session
from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection
from entirecontext.core.turn import create_turn


@pytest.fixture
def outcome_setup(ec_db, ec_repo):
    """Seed: surfaced decision + new decision in same session + file overlap."""
    conn = ec_db
    repo_path = str(ec_repo)
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

    # Surfaced (old) decision
    old_decision = create_decision(conn, title="Original auth approach", rationale="Basic token")
    link_decision_to_file(conn, old_decision["id"], "src/auth.py")

    # Session
    session = create_session(conn, project_id, session_type="claude")
    session_id = session["id"]

    # Record start commit
    start_sha = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    conn.execute(
        "UPDATE sessions SET metadata = ? WHERE id = ?",
        (json.dumps({"start_git_commit": start_sha}), session_id),
    )

    turn = create_turn(
        conn,
        session_id,
        turn_number=1,
        user_message="refine auth",
        files_touched=json.dumps(["src/auth.py"]),
        tools_used=json.dumps(["Edit"]),
    )

    # Surface old decision
    event = record_retrieval_event(
        conn,
        source="hook",
        search_type="decision_surface",
        target="decisions",
        query="auth",
        result_count=1,
        latency_ms=5,
        session_id=session_id,
        turn_id=turn["id"],
    )
    selection = record_retrieval_selection(
        conn,
        event["id"],
        result_type="decision",
        result_id=old_decision["id"],
        session_id=session_id,
        turn_id=turn["id"],
    )

    # New decision in same session (overlapping file)
    new_decision = create_decision(conn, title="Refined auth with refresh tokens", rationale="Better UX")
    link_decision_to_file(conn, new_decision["id"], "src/auth.py")

    return {
        "conn": conn,
        "repo_path": repo_path,
        "session_id": session_id,
        "old_decision_id": old_decision["id"],
        "new_decision_id": new_decision["id"],
        "selection_id": selection["id"],
        "turn_id": turn["id"],
        "start_sha": start_sha,
    }


def test_refined_outcome_on_net_additions(outcome_setup):
    """New decision + net additions in overlapping files => refined."""
    import pathlib

    ctx = outcome_setup
    conn = ctx["conn"]
    repo_path = ctx["repo_path"]

    auth_file = pathlib.Path(repo_path) / "src" / "auth.py"
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    auth_file.write_text("# auth\ndef login():\n    pass\n\ndef refresh():\n    pass\n")
    subprocess.run(["git", "-C", repo_path, "add", "src/auth.py"], capture_output=True)
    subprocess.run(
        ["git", "-C", repo_path, "commit", "-m", "add auth"],
        capture_output=True,
    )

    result = infer_applied_decisions(conn, ctx["session_id"], repo_path=repo_path)
    assert result["applied_count"] == 1

    outcome = conn.execute(
        "SELECT * FROM decision_outcomes WHERE decision_id = ? AND session_id = ?",
        (ctx["old_decision_id"], ctx["session_id"]),
    ).fetchone()
    assert outcome is not None
    assert outcome["outcome_type"] == "refined"


def test_replaced_outcome_on_net_deletions(outcome_setup):
    """New decision + net deletions in overlapping files => replaced."""
    import pathlib

    ctx = outcome_setup
    conn = ctx["conn"]
    repo_path = ctx["repo_path"]

    # Create initial file, commit, then replace with less content
    auth_file = pathlib.Path(repo_path) / "src" / "auth.py"
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    auth_file.write_text(
        "# auth\ndef old_login():\n    pass\n\ndef old_refresh():\n    pass\n\ndef old_validate():\n    pass\n"
    )
    subprocess.run(["git", "-C", repo_path, "add", "src/auth.py"], capture_output=True)
    subprocess.run(
        ["git", "-C", repo_path, "commit", "-m", "old auth"],
        capture_output=True,
    )

    # Update start_sha to before the replacement
    start_sha = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    conn.execute(
        "UPDATE sessions SET metadata = ? WHERE id = ?",
        (json.dumps({"start_git_commit": start_sha}), ctx["session_id"]),
    )

    # Now replace with less content
    auth_file.write_text("# new auth\ndef login():\n    pass\n")
    subprocess.run(["git", "-C", repo_path, "add", "src/auth.py"], capture_output=True)
    subprocess.run(
        ["git", "-C", repo_path, "commit", "-m", "replace auth"],
        capture_output=True,
    )

    result = infer_applied_decisions(conn, ctx["session_id"], repo_path=repo_path)
    assert result["applied_count"] == 1

    outcome = conn.execute(
        "SELECT * FROM decision_outcomes WHERE decision_id = ? AND session_id = ?",
        (ctx["old_decision_id"], ctx["session_id"]),
    ).fetchone()
    assert outcome is not None
    assert outcome["outcome_type"] == "replaced"


def test_accepted_outcome_when_no_new_decision(ec_db, ec_repo):
    """File overlap without new decision => accepted (existing behavior)."""
    conn = ec_db
    repo_path = str(ec_repo)
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

    decision = create_decision(conn, title="Original approach", rationale="Simple")
    link_decision_to_file(conn, decision["id"], "src/foo.py")

    session = create_session(conn, project_id)
    turn = create_turn(
        conn,
        session["id"],
        turn_number=1,
        user_message="work",
        files_touched=json.dumps(["src/foo.py"]),
        tools_used=json.dumps(["Edit"]),
    )

    event = record_retrieval_event(
        conn,
        source="hook",
        search_type="decision_surface",
        target="decisions",
        query="foo",
        result_count=1,
        latency_ms=5,
        session_id=session["id"],
        turn_id=turn["id"],
    )
    record_retrieval_selection(
        conn,
        event["id"],
        result_type="decision",
        result_id=decision["id"],
        session_id=session["id"],
        turn_id=turn["id"],
    )

    result = infer_applied_decisions(conn, session["id"], repo_path=repo_path)
    assert result["applied_count"] == 1

    outcome = conn.execute(
        "SELECT * FROM decision_outcomes WHERE decision_id = ?",
        (decision["id"],),
    ).fetchone()
    assert outcome["outcome_type"] == "accepted"


def test_infer_outcome_type_config_off_falls_back_to_accepted(outcome_setup, monkeypatch):
    """infer_outcome_type=False => always 'accepted' even with new decision."""
    import pathlib

    ctx = outcome_setup
    conn = ctx["conn"]
    repo_path = ctx["repo_path"]

    auth_file = pathlib.Path(repo_path) / "src" / "auth.py"
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    auth_file.write_text("# new\ndef login():\n    pass\n\ndef extra():\n    pass\n")
    subprocess.run(["git", "-C", repo_path, "add", "src/auth.py"], capture_output=True)
    subprocess.run(["git", "-C", repo_path, "commit", "-m", "change"], capture_output=True)

    import entirecontext.core.config as config_mod

    original_load = config_mod.load_config

    def patched_load(path):
        c = original_load(path)
        c.setdefault("decisions", {})["infer_outcome_type"] = False
        return c

    monkeypatch.setattr(config_mod, "load_config", patched_load)

    result = infer_applied_decisions(conn, ctx["session_id"], repo_path=repo_path)

    outcome = conn.execute(
        "SELECT * FROM decision_outcomes WHERE decision_id = ? AND session_id = ?",
        (ctx["old_decision_id"], ctx["session_id"]),
    ).fetchone()
    assert outcome["outcome_type"] == "accepted"
