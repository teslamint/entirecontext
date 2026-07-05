"""Tests for ranking snapshot capture inside rank_related_decisions."""

import json

from entirecontext.core.decisions import (
    rank_related_decisions,
    create_decision,
    link_decision_to_file,
)


def _make_decision(conn, title="test decision", files=None):
    """Helper -- create a decision with linked files."""
    decision = create_decision(
        conn,
        title=title,
        rationale="test",
        scope="module",
    )
    did = decision["id"]
    if files:
        for f in files:
            link_decision_to_file(conn, did, f)
    return did


def test_snapshot_captured_when_enabled(ec_db):
    """When _capture_snapshots=True, a snapshot row is written."""
    conn = ec_db
    _make_decision(conn, files=["src/foo.py"])

    results, stats = rank_related_decisions(
        conn,
        file_paths=["src/foo.py"],
        _return_stats=True,
        _capture_snapshots=True,
    )

    assert "snapshot_id" in stats
    row = conn.execute("SELECT * FROM ranking_snapshots WHERE id = ?", (stats["snapshot_id"],)).fetchone()
    assert row is not None
    candidates = json.loads(row["scored_candidates"])
    assert len(candidates) >= 1
    assert row["effective_limit"] == 10  # default limit
    assert row["retrieval_event_id"] is None  # not yet backpatched


def test_snapshot_not_captured_when_disabled(ec_db):
    """When _capture_snapshots=False (default), no snapshot row."""
    conn = ec_db
    _make_decision(conn, files=["src/foo.py"])

    results, stats = rank_related_decisions(
        conn,
        file_paths=["src/foo.py"],
        _return_stats=True,
    )

    assert "snapshot_id" not in stats
    count = conn.execute("SELECT COUNT(*) FROM ranking_snapshots").fetchone()[0]
    assert count == 0


def test_snapshot_diff_text_redacted(ec_db):
    """Diff text is filtered before storage (filter_secrets catches known patterns)."""
    conn = ec_db
    _make_decision(conn, files=["src/foo.py"])

    # Use a secret that matches DEFAULT_PATTERNS: sk- followed by 48 alphanums
    secret_key = "sk-" + "a" * 48
    secret_diff = f"added key {secret_key} in config"

    results, stats = rank_related_decisions(
        conn,
        file_paths=["src/foo.py"],
        diff_text=secret_diff,
        _return_stats=True,
        _capture_snapshots=True,
    )

    row = conn.execute(
        "SELECT input_diff_text FROM ranking_snapshots WHERE id = ?",
        (stats["snapshot_id"],),
    ).fetchone()
    assert secret_key not in (row["input_diff_text"] or "")
    assert "[REDACTED]" in (row["input_diff_text"] or "")


def test_snapshot_diff_text_truncated_at_8192(ec_db):
    """Diff text exceeding 8192 bytes is truncated."""
    conn = ec_db
    _make_decision(conn, files=["src/foo.py"])

    long_diff = "x" * 10000

    results, stats = rank_related_decisions(
        conn,
        file_paths=["src/foo.py"],
        diff_text=long_diff,
        _return_stats=True,
        _capture_snapshots=True,
    )

    row = conn.execute(
        "SELECT input_diff_text FROM ranking_snapshots WHERE id = ?",
        (stats["snapshot_id"],),
    ).fetchone()
    assert len(row["input_diff_text"]) <= 8192


def test_snapshot_diff_text_redacted_with_capture_config(ec_db):
    """When _capture_config is provided, redact_content is applied after filter_secrets."""
    conn = ec_db
    _make_decision(conn, files=["src/foo.py"])

    config = {
        "capture": {
            "exclusions": {
                "enabled": True,
                "redact_patterns": [r"INTERNAL_SECRET_\w+"],
            }
        }
    }
    diff_with_custom_secret = "refactored INTERNAL_SECRET_xyz123 handler"

    results, stats = rank_related_decisions(
        conn,
        file_paths=["src/foo.py"],
        diff_text=diff_with_custom_secret,
        _return_stats=True,
        _capture_snapshots=True,
        _capture_config=config,
    )

    row = conn.execute(
        "SELECT input_diff_text FROM ranking_snapshots WHERE id = ?",
        (stats["snapshot_id"],),
    ).fetchone()
    stored = row["input_diff_text"] or ""
    assert "INTERNAL_SECRET_xyz123" not in stored
    assert "[FILTERED]" in stored


def test_snapshot_stores_full_scored_set(ec_db):
    """Snapshot stores ALL scored candidates, not just top-k."""
    conn = ec_db
    for i in range(5):
        _make_decision(conn, title=f"decision {i}", files=["src/foo.py"])

    results, stats = rank_related_decisions(
        conn,
        file_paths=["src/foo.py"],
        limit=2,
        _return_stats=True,
        _capture_snapshots=True,
    )

    assert len(results) == 2  # truncated return
    row = conn.execute(
        "SELECT scored_candidates, effective_limit FROM ranking_snapshots WHERE id = ?",
        (stats["snapshot_id"],),
    ).fetchone()
    candidates = json.loads(row["scored_candidates"])
    assert len(candidates) == 5  # full set
    assert row["effective_limit"] == 2
