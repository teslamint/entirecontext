"""Tests for After-Action Report (AAR) generation and hook integration."""

from __future__ import annotations

import datetime
import json
import subprocess
from pathlib import Path
from uuid import uuid4

from entirecontext.core.aar import format_aar_summary, generate_aar
from entirecontext.hooks.session_lifecycle import _maybe_emit_aar


def _get_head(repo_path):
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_path, capture_output=True, text=True)
    return r.stdout.strip()


def _create_test_session(conn, repo_path=None):
    sid = str(uuid4())
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
    meta = None
    if repo_path:
        head = _get_head(repo_path)
        meta = json.dumps({"start_git_commit": head})
    conn.execute(
        "INSERT INTO sessions (id, project_id, session_type, workspace_path, started_at, last_activity_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sid, project_id, "claude", "/tmp", now, now, meta),
    )
    return sid


def test_generate_aar_empty_session(ec_repo, ec_db):
    sid = _create_test_session(ec_db, str(ec_repo))
    aar = generate_aar(ec_db, sid, str(ec_repo))
    assert aar["session_id"] == sid
    assert aar["generated_at"]
    assert aar["decisions_extracted"]["count"] == 0
    assert aar["decisions_extracted"]["titles"] == []
    assert "(extraction worker" in aar["decisions_extracted"]["note"]
    assert aar["decisions_surfaced"]["count"] == 0
    assert aar["pdi_delta"]["surfaced"] == 0
    assert aar["pdi_delta"]["applied"] == 0
    assert aar["pdi_delta"]["rate"] == 0.0
    assert aar["assessments"]["new_count"] == 0


def test_generate_aar_with_assessments(ec_repo, ec_db):
    sid = _create_test_session(ec_db, str(ec_repo))
    head = _get_head(ec_repo)
    cp_id = str(uuid4())
    ec_db.execute(
        "INSERT INTO checkpoints (id, session_id, git_commit_hash) VALUES (?, ?, ?)",
        (cp_id, sid, head),
    )
    a_id = str(uuid4())
    ec_db.execute(
        "INSERT INTO assessments (id, checkpoint_id, verdict) VALUES (?, ?, ?)",
        (a_id, cp_id, "expand"),
    )
    aar = generate_aar(ec_db, sid, str(ec_repo))
    assert aar["assessments"]["new_count"] == 1


def test_generate_aar_with_retrieval(ec_repo, ec_db):
    sid = _create_test_session(ec_db, str(ec_repo))
    # create a decision to reference
    dec_id = str(uuid4())
    ec_db.execute("INSERT INTO decisions (id, title) VALUES (?, ?)", (dec_id, "Use SQLite WAL"))
    # retrieval event
    re_id = str(uuid4())
    ec_db.execute(
        "INSERT INTO retrieval_events (id, session_id, source, search_type, target, query, result_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (re_id, sid, "hook", "decision", "decisions", "test query", 1),
    )
    # retrieval selection
    rs_id = str(uuid4())
    ec_db.execute(
        "INSERT INTO retrieval_selections (id, retrieval_event_id, session_id, result_type, result_id) VALUES (?, ?, ?, ?, ?)",
        (rs_id, re_id, sid, "decision", dec_id),
    )
    aar = generate_aar(ec_db, sid, str(ec_repo))
    assert aar["decisions_surfaced"]["count"] == 1
    assert "Use SQLite WAL" in aar["decisions_surfaced"]["titles"]


def test_generate_aar_pdi_delta(ec_repo, ec_db):
    sid = _create_test_session(ec_db, str(ec_repo))
    # create decisions
    dec1 = str(uuid4())
    dec2 = str(uuid4())
    dec3 = str(uuid4())
    for did, title in [(dec1, "D1"), (dec2, "D2"), (dec3, "D3")]:
        ec_db.execute("INSERT INTO decisions (id, title) VALUES (?, ?)", (did, title))
    # retrieval event
    re_id = str(uuid4())
    ec_db.execute(
        "INSERT INTO retrieval_events (id, session_id, source, search_type, target, query, result_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (re_id, sid, "hook", "decision", "decisions", "query", 3),
    )
    # 3 selections
    rs_ids = []
    for did in [dec1, dec2, dec3]:
        rs_id = str(uuid4())
        rs_ids.append(rs_id)
        ec_db.execute(
            "INSERT INTO retrieval_selections (id, retrieval_event_id, session_id, result_type, result_id) VALUES (?, ?, ?, ?, ?)",
            (rs_id, re_id, sid, "decision", did),
        )
    # 1 application
    ca_id = str(uuid4())
    ec_db.execute(
        "INSERT INTO context_applications (id, session_id, retrieval_selection_id, source_type, source_id, application_type) VALUES (?, ?, ?, ?, ?, ?)",
        (ca_id, sid, rs_ids[0], "decision", dec1, "lesson_applied"),
    )
    aar = generate_aar(ec_db, sid, str(ec_repo))
    assert aar["pdi_delta"]["surfaced"] == 3
    assert aar["pdi_delta"]["applied"] == 1
    assert abs(aar["pdi_delta"]["rate"] - 1 / 3) < 0.01


def test_format_aar_summary():
    aar = {
        "session_id": "af44f9ee-1234-5678-9abc-def012345678",
        "generated_at": "2026-06-07T00:00:00+00:00",
        "decisions_extracted": {"count": 0, "titles": [], "note": "(extraction worker may still be running)"},
        "decisions_surfaced": {"count": 3, "titles": ["A", "B", "C"]},
        "pdi_delta": {"surfaced": 3, "applied": 1, "rate": 1 / 3},
        "assessments": {"new_count": 2},
    }
    text = format_aar_summary(aar)
    assert "Session af44f9ee" in text
    assert "Decisions extracted: 0" in text
    assert "extraction worker" in text
    assert "Decisions surfaced: 3" in text
    assert "1/3 applied" in text
    assert "33.3%" in text
    assert "Assessments created: 2" in text


def test_format_aar_summary_no_surfaced():
    aar = {
        "session_id": "00000000-0000-0000-0000-000000000000",
        "generated_at": "2026-06-07T00:00:00+00:00",
        "decisions_extracted": {"count": 0, "titles": [], "note": "(extraction worker may still be running)"},
        "decisions_surfaced": {"count": 0, "titles": []},
        "pdi_delta": {"surfaced": 0, "applied": 0, "rate": 0.0},
        "assessments": {"new_count": 0},
    }
    text = format_aar_summary(aar)
    assert "no decisions surfaced" in text


def test_maybe_emit_aar_writes_json(ec_repo, ec_db):
    sid = _create_test_session(ec_db, str(ec_repo))
    _maybe_emit_aar(str(ec_repo), sid)
    aar_files = list(Path(str(ec_repo)).glob(".entirecontext/aar-*.json"))
    assert len(aar_files) == 1
    data = json.loads(aar_files[0].read_text())
    assert data["session_id"] == sid
    assert "generated_at" in data


def test_maybe_emit_aar_config_off(ec_repo, ec_db, monkeypatch):
    sid = _create_test_session(ec_db, str(ec_repo))
    monkeypatch.setattr(
        "entirecontext.core.config.load_config",
        lambda *a, **kw: {"capture": {"emit_aar": False}},
    )
    _maybe_emit_aar(str(ec_repo), sid)
    aar_files = list(Path(str(ec_repo)).glob(".entirecontext/aar-*.json"))
    assert len(aar_files) == 0


def test_maybe_emit_aar_never_crashes():
    # bad repo path and session id — must not raise
    _maybe_emit_aar("/nonexistent/repo/path", "bad-session-id-!!!!")
