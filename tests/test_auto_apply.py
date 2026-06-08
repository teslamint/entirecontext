"""Tests for core/auto_apply.py — SessionEnd auto-apply inference."""

from __future__ import annotations

import json

import pytest

from entirecontext.core.auto_apply import infer_applied_decisions
from entirecontext.core.decisions import create_decision, link_decision_to_file, record_decision_outcome
from entirecontext.core.session import create_session
from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection
from entirecontext.core.turn import create_turn


@pytest.fixture
def auto_apply_setup(ec_db, ec_repo):
    """Seed: 1 session (ended), 1 turn with Edit + files_touched, 1 decision + file link, 1 retrieval + selection."""
    conn = ec_db
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

    session = create_session(conn, project_id, session_type="claude")
    session_id = session["id"]

    turn = create_turn(
        conn,
        session_id,
        turn_number=1,
        user_message="implement feature X",
        files_touched=json.dumps(["src/foo.py", "src/bar.py"]),
        tools_used=json.dumps(["Edit", "Read"]),
    )
    turn_id = turn["id"]

    conn.execute(
        "UPDATE sessions SET ended_at = datetime('now') WHERE id = ?",
        (session_id,),
    )

    decision = create_decision(conn, title="Use approach A for feature X", rationale="simpler")
    decision_id = decision["id"]
    link_decision_to_file(conn, decision_id, "src/foo.py")

    event = record_retrieval_event(
        conn,
        source="hook",
        search_type="decision_surface",
        target="decisions",
        query="feature X",
        result_count=1,
        latency_ms=10,
        session_id=session_id,
        turn_id=turn_id,
    )

    selection = record_retrieval_selection(
        conn,
        event["id"],
        result_type="decision",
        result_id=decision_id,
        session_id=session_id,
        turn_id=turn_id,
    )

    return {
        "conn": conn,
        "project_id": project_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "decision_id": decision_id,
        "selection_id": selection["id"],
        "event_id": event["id"],
    }


def test_infer_applied_creates_application_and_outcome(auto_apply_setup):
    """Verify both context_application and decision_outcome are created."""
    ctx = auto_apply_setup
    conn = ctx["conn"]

    result = infer_applied_decisions(conn, ctx["session_id"])

    assert result["applied_count"] == 1
    assert len(result["applied_decisions"]) == 1
    assert result["applied_decisions"][0]["decision_id"] == ctx["decision_id"]

    app_row = conn.execute(
        "SELECT * FROM context_applications WHERE session_id = ? AND source_id = ?",
        (ctx["session_id"], ctx["decision_id"]),
    ).fetchone()
    assert app_row is not None
    assert app_row["application_type"] == "decision_change"

    outcome_row = conn.execute(
        "SELECT * FROM decision_outcomes WHERE decision_id = ? AND session_id = ?",
        (ctx["decision_id"], ctx["session_id"]),
    ).fetchone()
    assert outcome_row is not None
    assert outcome_row["outcome_type"] == "accepted"
    assert "auto: session_end file_overlap" in outcome_row["note"]


def test_infer_applied_atomicity_both_or_neither(auto_apply_setup, monkeypatch):
    """If record_decision_outcome raises, no context_application should persist."""
    ctx = auto_apply_setup
    conn = ctx["conn"]

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("entirecontext.core.auto_apply.record_decision_outcome", _raise)

    with pytest.raises(RuntimeError, match="boom"):
        infer_applied_decisions(conn, ctx["session_id"])

    app_count = conn.execute(
        "SELECT COUNT(*) FROM context_applications WHERE session_id = ?",
        (ctx["session_id"],),
    ).fetchone()[0]
    assert app_count == 0

    outcome_count = conn.execute(
        "SELECT COUNT(*) FROM decision_outcomes WHERE decision_id = ? AND session_id = ?",
        (ctx["decision_id"], ctx["session_id"]),
    ).fetchone()[0]
    assert outcome_count == 0


def test_infer_applied_skips_existing_outcome(auto_apply_setup):
    """Pre-recorded outcome causes the decision to be skipped."""
    ctx = auto_apply_setup
    conn = ctx["conn"]

    record_decision_outcome(
        conn,
        ctx["decision_id"],
        outcome_type="accepted",
        retrieval_selection_id=ctx["selection_id"],
        session_id=ctx["session_id"],
        turn_id=ctx["turn_id"],
        note="manual",
    )

    result = infer_applied_decisions(conn, ctx["session_id"])
    assert result["applied_count"] == 0


def test_infer_applied_skips_no_file_overlap(ec_db, ec_repo):
    """Decision linked to unrelated file => count=0."""
    conn = ec_db
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

    session = create_session(conn, project_id)
    session_id = session["id"]

    turn = create_turn(
        conn,
        session_id,
        turn_number=1,
        user_message="work on X",
        files_touched=json.dumps(["src/alpha.py"]),
        tools_used=json.dumps(["Edit"]),
    )

    decision = create_decision(conn, title="unrelated decision")
    link_decision_to_file(conn, decision["id"], "src/totally_different.py")

    event = record_retrieval_event(
        conn,
        source="hook",
        search_type="decision_surface",
        target="decisions",
        query="X",
        result_count=1,
        latency_ms=5,
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

    result = infer_applied_decisions(conn, session_id)
    assert result["applied_count"] == 0


def test_infer_applied_deduplicates_across_turns(ec_db, ec_repo):
    """Same decision surfaced in 2 turns => only 1 application."""
    conn = ec_db
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

    session = create_session(conn, project_id)
    session_id = session["id"]

    turn1 = create_turn(
        conn,
        session_id,
        turn_number=1,
        user_message="first",
        files_touched=json.dumps(["src/shared.py"]),
        tools_used=json.dumps(["Edit"]),
    )
    turn2 = create_turn(
        conn,
        session_id,
        turn_number=2,
        user_message="second",
        files_touched=json.dumps(["src/shared.py"]),
        tools_used=json.dumps(["Edit"]),
    )

    decision = create_decision(conn, title="shared decision")
    link_decision_to_file(conn, decision["id"], "src/shared.py")

    for turn in [turn1, turn2]:
        event = record_retrieval_event(
            conn,
            source="hook",
            search_type="decision_surface",
            target="decisions",
            query="shared",
            result_count=1,
            latency_ms=5,
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

    result = infer_applied_decisions(conn, session_id)
    assert result["applied_count"] == 1

    outcome_count = conn.execute(
        "SELECT COUNT(*) FROM decision_outcomes WHERE decision_id = ? AND session_id = ?",
        (decision["id"], session_id),
    ).fetchone()[0]
    assert outcome_count == 1


def test_infer_applied_dry_run_writes_nothing(auto_apply_setup):
    """dry_run=True returns count but writes no records."""
    ctx = auto_apply_setup
    conn = ctx["conn"]

    result = infer_applied_decisions(conn, ctx["session_id"], dry_run=True)
    assert result["applied_count"] == 1
    assert result["applied_decisions"] == []

    app_count = conn.execute(
        "SELECT COUNT(*) FROM context_applications WHERE session_id = ?",
        (ctx["session_id"],),
    ).fetchone()[0]
    assert app_count == 0


def test_infer_applied_null_turn_id_no_crash(ec_db, ec_repo):
    """Selection with turn_id=None (SessionStart surfacing) must not raise ValueError."""
    conn = ec_db
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

    session = create_session(conn, project_id)
    session_id = session["id"]

    create_turn(
        conn,
        session_id,
        turn_number=1,
        user_message="work on feature",
        files_touched=json.dumps(["src/target.py"]),
        tools_used=json.dumps(["Edit"]),
    )

    conn.execute(
        "UPDATE sessions SET ended_at = datetime('now') WHERE id = ?",
        (session_id,),
    )

    decision = create_decision(conn, title="SessionStart decision")
    link_decision_to_file(conn, decision["id"], "src/target.py")

    event = record_retrieval_event(
        conn,
        source="hook",
        search_type="decision_surface",
        target="decisions",
        query="feature",
        result_count=1,
        latency_ms=5,
        session_id=session_id,
        turn_id=None,
    )
    record_retrieval_selection(
        conn,
        event["id"],
        result_type="decision",
        result_id=decision["id"],
        session_id=session_id,
        turn_id=None,
    )

    result = infer_applied_decisions(conn, session_id)
    assert result["applied_count"] == 1


def test_infer_applied_path_normalization(ec_db, ec_repo):
    """Decision linked to './src/core/foo.py' overlaps with session touching 'src/core/foo.py'."""
    conn = ec_db
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

    session = create_session(conn, project_id)
    session_id = session["id"]

    turn = create_turn(
        conn,
        session_id,
        turn_number=1,
        user_message="edit foo",
        files_touched=json.dumps(["src/core/foo.py"]),
        tools_used=json.dumps(["Edit"]),
    )

    conn.execute(
        "UPDATE sessions SET ended_at = datetime('now') WHERE id = ?",
        (session_id,),
    )

    decision = create_decision(conn, title="Decision with dotslash path")
    link_decision_to_file(conn, decision["id"], "./src/core/foo.py")

    event = record_retrieval_event(
        conn,
        source="hook",
        search_type="decision_surface",
        target="decisions",
        query="foo",
        result_count=1,
        latency_ms=5,
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

    result = infer_applied_decisions(conn, session_id)
    assert result["applied_count"] == 1


def test_infer_applied_ignores_read_only_turns(ec_db, ec_repo):
    """Turn with only Read tool must not count as a file modification."""
    conn = ec_db
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

    session = create_session(conn, project_id)
    session_id = session["id"]

    create_turn(
        conn,
        session_id,
        turn_number=1,
        user_message="reading the file",
        files_touched=json.dumps(["src/target.py"]),
        tools_used=json.dumps(["Read"]),
    )

    decision = create_decision(conn, title="Read-only decision")
    link_decision_to_file(conn, decision["id"], "src/target.py")

    event = record_retrieval_event(
        conn,
        source="hook",
        search_type="decision_surface",
        target="decisions",
        query="target",
        result_count=1,
        latency_ms=5,
        session_id=session_id,
        turn_id=None,
    )
    record_retrieval_selection(
        conn,
        event["id"],
        result_type="decision",
        result_id=decision["id"],
        session_id=session_id,
    )

    result = infer_applied_decisions(conn, session_id)
    assert result["applied_count"] == 0, "Read-only turn should not trigger auto-apply"


def test_infer_applied_ignores_edits_before_surfacing(ec_db, ec_repo):
    """File edited BEFORE decision was surfaced should not count."""
    conn = ec_db
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

    session = create_session(conn, project_id)
    session_id = session["id"]

    # Turn 1: edit src/foo.py (BEFORE decision is surfaced)
    turn1 = create_turn(
        conn,
        session_id,
        turn_number=1,
        user_message="early edit",
        files_touched=json.dumps(["src/foo.py"]),
        tools_used=json.dumps(["Edit"]),
    )

    # Turn 3: decision surfaced (no edit in this turn)
    turn3 = create_turn(
        conn,
        session_id,
        turn_number=3,
        user_message="seeing decision",
        files_touched=json.dumps([]),
        tools_used=json.dumps(["Read"]),
    )

    decision = create_decision(conn, title="Decision surfaced late")
    link_decision_to_file(conn, decision["id"], "src/foo.py")

    event = record_retrieval_event(
        conn,
        source="mcp",
        search_type="decision_related",
        target="decisions",
        query="foo",
        result_count=1,
        latency_ms=5,
        session_id=session_id,
        turn_id=turn3["id"],
    )
    record_retrieval_selection(
        conn,
        event["id"],
        result_type="decision",
        result_id=decision["id"],
        session_id=session_id,
        turn_id=turn3["id"],
    )

    result = infer_applied_decisions(conn, session_id)
    assert result["applied_count"] == 0, "Edit before surfacing should not trigger auto-apply"


def test_infer_applied_counts_edits_after_surfacing(ec_db, ec_repo):
    """File edited AFTER decision was surfaced should count."""
    conn = ec_db
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

    session = create_session(conn, project_id)
    session_id = session["id"]

    # Turn 1: decision surfaced
    turn1 = create_turn(
        conn,
        session_id,
        turn_number=1,
        user_message="seeing decision",
    )

    # Turn 3: edit src/foo.py (AFTER decision was surfaced)
    create_turn(
        conn,
        session_id,
        turn_number=3,
        user_message="applying decision",
        files_touched=json.dumps(["src/foo.py"]),
        tools_used=json.dumps(["Edit"]),
    )

    decision = create_decision(conn, title="Decision surfaced early")
    link_decision_to_file(conn, decision["id"], "src/foo.py")

    event = record_retrieval_event(
        conn,
        source="mcp",
        search_type="decision_related",
        target="decisions",
        query="foo",
        result_count=1,
        latency_ms=5,
        session_id=session_id,
        turn_id=turn1["id"],
    )
    record_retrieval_selection(
        conn,
        event["id"],
        result_type="decision",
        result_id=decision["id"],
        session_id=session_id,
        turn_id=turn1["id"],
    )

    result = infer_applied_decisions(conn, session_id)
    assert result["applied_count"] == 1, "Edit after surfacing should trigger auto-apply"


def test_auto_apply_prevents_ignored_double_marking(ec_db, ec_repo):
    """After auto-apply writes 'accepted', the ignored inference query must skip the decision."""
    conn = ec_db
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

    session = create_session(conn, project_id)
    session_id = session["id"]

    turn1 = create_turn(
        conn,
        session_id,
        turn_number=1,
        user_message="feature work",
        files_touched=json.dumps(["src/target.py"]),
        tools_used=json.dumps(["Edit"]),
    )
    create_turn(conn, session_id, turn_number=2, user_message="more work")
    create_turn(conn, session_id, turn_number=3, user_message="finishing up")

    decision = create_decision(conn, title="decision to test mutual exclusion")
    link_decision_to_file(conn, decision["id"], "src/target.py")

    event = record_retrieval_event(
        conn,
        source="hook",
        search_type="decision_surface",
        target="decisions",
        query="feature",
        result_count=1,
        latency_ms=5,
        session_id=session_id,
        turn_id=turn1["id"],
    )
    record_retrieval_selection(
        conn,
        event["id"],
        result_type="decision",
        result_id=decision["id"],
        session_id=session_id,
        turn_id=turn1["id"],
    )

    result = infer_applied_decisions(conn, session_id)
    assert result["applied_count"] == 1

    ignored_candidates = conn.execute(
        """
        SELECT rs.result_id AS decision_id
        FROM retrieval_selections rs
        JOIN retrieval_events re ON re.id = rs.retrieval_event_id
        WHERE rs.session_id = ?
          AND rs.result_type = 'decision'
          AND NOT EXISTS (
              SELECT 1 FROM decision_outcomes do
              WHERE do.decision_id = rs.result_id
                AND do.session_id = ?
          )
        """,
        (session_id, session_id),
    ).fetchall()

    ignored_decision_ids = {row["decision_id"] for row in ignored_candidates}
    assert decision["id"] not in ignored_decision_ids
