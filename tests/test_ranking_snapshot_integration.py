"""Integration: full lifecycle -- capture -> backpatch -> purge."""

import json
from datetime import datetime, timedelta, timezone

from entirecontext.core.decisions import (
    backpatch_snapshot_event,
    create_decision,
    link_decision_to_file,
    rank_related_decisions,
)
from entirecontext.core.purge import purge_ranking_snapshots
from entirecontext.core.telemetry import record_retrieval_event


def test_full_snapshot_lifecycle(ec_db):
    conn = ec_db

    # 1. Create decision
    decision = create_decision(conn, title="lifecycle test", rationale="test", scope="module")
    link_decision_to_file(conn, decision["id"], "src/app.py")

    # 2. Rank with capture enabled (direct param, no config mock)
    results, stats = rank_related_decisions(
        conn, file_paths=["src/app.py"], _return_stats=True, _capture_snapshots=True
    )
    assert len(results) >= 1
    snapshot_id = stats["snapshot_id"]

    # 3. Backpatch -- requires a real retrieval_events row: ranking_snapshots.retrieval_event_id
    # has a FOREIGN KEY REFERENCES retrieval_events(id) and PRAGMA foreign_keys=ON, so an
    # arbitrary placeholder string would raise an FK violation on the UPDATE.
    event = record_retrieval_event(
        conn,
        source="hook",
        search_type="decision_surface",
        target="decisions",
        query="test",
        result_count=1,
        latency_ms=1,
    )
    backpatch_snapshot_event(conn, snapshot_id=snapshot_id, retrieval_event_id=event["id"])
    row = conn.execute(
        "SELECT retrieval_event_id FROM ranking_snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()
    assert row["retrieval_event_id"] == event["id"]

    # 4. Verify snapshot content
    row = conn.execute("SELECT * FROM ranking_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    candidates = json.loads(row["scored_candidates"])
    assert len(candidates) >= 1
    assert row["effective_limit"] == 10

    # 5. Purge (not yet old enough)
    result = purge_ranking_snapshots(conn, retention_days=90, dry_run=False)
    assert result["deleted"] == 0

    # 6. Manually age the snapshot
    old_date = (datetime.now(timezone.utc) - timedelta(days=100)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE ranking_snapshots SET created_at = ? WHERE id = ?", (old_date, snapshot_id))

    # 7. Purge (now old enough)
    result = purge_ranking_snapshots(conn, retention_days=90, dry_run=False)
    assert result["deleted"] == 1

    # 8. Verify gone
    row = conn.execute("SELECT * FROM ranking_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    assert row is None
