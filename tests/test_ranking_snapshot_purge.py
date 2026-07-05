"""Tests for ranking snapshot purge and retention."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_purge_removes_old_snapshots(ec_db):
    conn = ec_db
    old_date = (datetime.now(timezone.utc) - timedelta(days=100)).strftime("%Y-%m-%d %H:%M:%S")
    recent_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        "INSERT INTO ranking_snapshots (id, scored_candidates, effective_limit, created_at) VALUES (?, ?, ?, ?)",
        ("old-1", "[]", 5, old_date),
    )
    conn.execute(
        "INSERT INTO ranking_snapshots (id, scored_candidates, effective_limit, created_at) VALUES (?, ?, ?, ?)",
        ("recent-1", "[]", 5, recent_date),
    )

    from entirecontext.core.purge import purge_ranking_snapshots

    result = purge_ranking_snapshots(conn, retention_days=90, dry_run=False)
    assert result["deleted"] == 1

    remaining = conn.execute("SELECT id FROM ranking_snapshots").fetchall()
    assert len(remaining) == 1
    assert remaining[0]["id"] == "recent-1"


def test_purge_dry_run_does_not_delete(ec_db):
    conn = ec_db
    old_date = (datetime.now(timezone.utc) - timedelta(days=100)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO ranking_snapshots (id, scored_candidates, effective_limit, created_at) VALUES (?, ?, ?, ?)",
        ("old-1", "[]", 5, old_date),
    )

    from entirecontext.core.purge import purge_ranking_snapshots

    result = purge_ranking_snapshots(conn, retention_days=90, dry_run=True)
    assert result["deleted"] == 0
    assert result["matched"] == 1

    remaining = conn.execute("SELECT COUNT(*) FROM ranking_snapshots").fetchone()[0]
    assert remaining == 1
