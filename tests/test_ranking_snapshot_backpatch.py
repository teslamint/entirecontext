"""Tests that callers backpatch ranking_snapshots.retrieval_event_id."""

from __future__ import annotations


def test_backpatch_links_snapshot_to_event(ec_db):
    """After a caller creates a retrieval_event, the snapshot row gets the event_id."""
    conn = ec_db

    conn.execute(
        "INSERT INTO retrieval_events (id, source, search_type, target, query, result_count, latency_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("evt-1", "test", "test", "decision", "", 0, 0),
    )
    conn.execute(
        "INSERT INTO ranking_snapshots (id, scored_candidates, effective_limit) VALUES (?, ?, ?)",
        ("snap-1", "[]", 5),
    )

    from entirecontext.core.decisions import backpatch_snapshot_event

    backpatch_snapshot_event(conn, snapshot_id="snap-1", retrieval_event_id="evt-1")

    row = conn.execute(
        "SELECT retrieval_event_id FROM ranking_snapshots WHERE id = ?", ("snap-1",)
    ).fetchone()
    assert row["retrieval_event_id"] == "evt-1"


def test_backpatch_noop_when_no_snapshot(ec_db):
    """Backpatch on a missing snapshot_id is a no-op (no error)."""
    conn = ec_db

    from entirecontext.core.decisions import backpatch_snapshot_event

    backpatch_snapshot_event(conn, snapshot_id=None, retrieval_event_id="evt-1")


def test_backpatch_noop_when_snapshot_row_absent(ec_db):
    """Backpatch with a non-existent snapshot_id is a no-op (no error)."""
    conn = ec_db

    from entirecontext.core.decisions import backpatch_snapshot_event

    backpatch_snapshot_event(conn, snapshot_id="nonexistent", retrieval_event_id="evt-1")
    count = conn.execute("SELECT COUNT(*) FROM ranking_snapshots").fetchone()[0]
    assert count == 0


def test_session_start_wiring_backpatches_snapshot(ec_repo, ec_db, monkeypatch):
    """on_session_start_decisions captures a snapshot and backpatches the event_id."""
    conn = ec_db
    repo_path = str(ec_repo)

    # Use existing project from init_project
    proj_row = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
    project_id = proj_row["id"]
    from entirecontext.core.session import create_session

    sess = create_session(conn, project_id=project_id, session_type="chat")
    sess_id = sess["id"]

    # Create a decision with file link
    from entirecontext.core.decisions import create_decision

    dec = create_decision(conn, title="Test Decision", rationale="r")
    conn.execute(
        "INSERT INTO decision_files (decision_id, file_path) VALUES (?, ?)",
        (dec["id"], "src/main.py"),
    )

    # Monkeypatch _load_decisions_config
    def mock_load_decisions_config(rp):
        return {"show_related_on_start": True, "capture_ranking_snapshots": True}

    monkeypatch.setattr("entirecontext.hooks.decision_hooks._load_decisions_config", mock_load_decisions_config)

    # Monkeypatch load_config (used for full_config)
    def mock_load_config(rp):
        return {"decisions": {"show_related_on_start": True, "capture_ranking_snapshots": True}}

    monkeypatch.setattr("entirecontext.hooks.decision_hooks.load_config", mock_load_config, raising=False)

    # Monkeypatch git helpers to provide signals
    monkeypatch.setattr(
        "entirecontext.hooks.decision_hooks._get_recently_changed_files",
        lambda rp: ["src/main.py"],
    )
    monkeypatch.setattr(
        "entirecontext.hooks.decision_hooks._get_uncommitted_diff",
        lambda rp: "diff --git a/src/main.py",
    )
    monkeypatch.setattr(
        "entirecontext.hooks.decision_hooks._get_recent_commit_shas",
        lambda rp, limit=5: [],
    )

    # Monkeypatch get_db to return our test connection, preventing close
    original_close = conn.close
    monkeypatch.setattr(conn, "close", lambda: None)
    monkeypatch.setattr("entirecontext.db.get_db", lambda rp: conn)

    from entirecontext.hooks.decision_hooks import on_session_start_decisions

    data = {"session_id": sess_id, "repo_path": repo_path}
    on_session_start_decisions(data)

    # A snapshot should exist and be backpatched
    row = conn.execute(
        "SELECT id, retrieval_event_id FROM ranking_snapshots"
    ).fetchone()
    assert row is not None, "Expected a ranking snapshot to be captured"
    assert row["retrieval_event_id"] is not None, "Expected retrieval_event_id to be backpatched"

    # Restore close for fixture cleanup
    conn.close = original_close


def test_mcp_ec_decision_related_backpatches_snapshot(ec_repo, ec_db, monkeypatch):
    """ec_decision_related captures a snapshot and backpatches the event_id."""
    import asyncio
    import json

    conn = ec_db
    repo_path = str(ec_repo)

    # Use existing project from init_project
    proj_row = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
    project_id = proj_row["id"]
    from entirecontext.core.session import create_session

    create_session(conn, project_id=project_id, session_type="chat")

    # Create a decision with file link
    from entirecontext.core.decisions import create_decision

    dec = create_decision(conn, title="Test Decision", rationale="r")
    conn.execute(
        "INSERT INTO decision_files (decision_id, file_path) VALUES (?, ?)",
        (dec["id"], "src/main.py"),
    )

    # Monkeypatch resolve_repo
    monkeypatch.setattr(
        "entirecontext.mcp.tools.decisions.runtime.resolve_repo",
        lambda: ((conn, repo_path), None),
    )

    # Monkeypatch load_config (imported lazily inside the function)
    def mock_load_config(rp):
        return {"decisions": {"capture_ranking_snapshots": True}}

    monkeypatch.setattr(
        "entirecontext.core.config.load_config",
        mock_load_config,
    )

    # Insert a retrieval event so the FK constraint is satisfied
    conn.execute(
        "INSERT INTO retrieval_events (id, source, search_type, target, query, result_count, latency_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("evt-test-1", "mcp", "decision_related", "decision", "", 0, 0),
    )

    # Monkeypatch record_search_event to return a known event_id
    monkeypatch.setattr(
        "entirecontext.mcp.tools.decisions.runtime.record_search_event",
        lambda conn, **kw: "evt-test-1",
    )
    monkeypatch.setattr(
        "entirecontext.mcp.tools.decisions.runtime.record_selection",
        lambda conn, **kw: "sel-test-1",
    )

    # Don't let conn.close() close our test connection
    monkeypatch.setattr(conn, "close", lambda: None)

    from entirecontext.mcp.tools.decisions import ec_decision_related

    result = asyncio.run(
        ec_decision_related(
            files=["src/main.py"],
            diff_text="diff --git a/src/main.py",
        )
    )

    payload = json.loads(result)
    assert "error" not in payload

    # A snapshot should exist and be backpatched
    row = conn.execute(
        "SELECT id, retrieval_event_id FROM ranking_snapshots"
    ).fetchone()
    assert row is not None, "Expected a ranking snapshot to be captured"
    assert row["retrieval_event_id"] == "evt-test-1"


def test_worker_path_backpatches_snapshot(ec_repo, ec_db, monkeypatch):
    """run_prompt_surface_worker captures a snapshot and backpatches the event_id."""
    from pathlib import Path

    conn = ec_db
    repo_path = str(ec_repo)

    # Create session so telemetry FK constraints pass
    proj_row = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
    from entirecontext.core.session import create_session

    sess = create_session(conn, project_id=proj_row["id"], session_type="chat")
    sess_id = sess["id"]

    # Create a decision with file link
    from entirecontext.core.decisions import create_decision, link_decision_to_file

    dec = create_decision(conn, title="Worker Path Decision", rationale="test")
    link_decision_to_file(conn, dec["id"], "src/worker.py")

    # Enable capture in config
    monkeypatch.setattr(
        "entirecontext.core.config.load_config",
        lambda rp: {"decisions": {"capture_ranking_snapshots": True}},
    )

    # Write a tmp prompt file with content that will match
    prompt_dir = Path(repo_path) / ".entirecontext" / "tmp"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = prompt_dir / "test-prompt.txt"
    prompt_file.write_text("working on src/worker.py changes")

    # Monkeypatch git helpers used inside rank_decisions_for_prompt
    monkeypatch.setattr(
        "entirecontext.core.decision_prompt_surfacing._get_uncommitted_diff",
        lambda rp: "",
    )
    monkeypatch.setattr(
        "entirecontext.core.decision_prompt_surfacing._get_uncommitted_file_paths",
        lambda rp: ["src/worker.py"],
    )
    monkeypatch.setattr(
        "entirecontext.core.decision_prompt_surfacing._get_recent_commit_shas",
        lambda rp, limit=5: [],
    )
    monkeypatch.setattr(
        "entirecontext.core.decision_prompt_surfacing._get_recent_commit_file_paths",
        lambda rp, limit=5: [],
    )

    from entirecontext.core.decision_prompt_surfacing import run_prompt_surface_worker

    result = run_prompt_surface_worker(repo_path, sess_id, "no-turn", str(prompt_file))

    assert result["count"] >= 1, f"Expected surfaced decisions, got {result}"
    assert not result["warnings"], f"Unexpected warnings: {result['warnings']}"

    # Worker uses its own connection and closes it. Re-open to query.
    from entirecontext.db import get_db

    conn2 = get_db(repo_path)
    try:
        # A snapshot should exist and be backpatched with a real event_id
        row = conn2.execute(
            "SELECT id, retrieval_event_id FROM ranking_snapshots"
        ).fetchone()
        assert row is not None, "Expected a ranking snapshot from the worker path"
        assert row["retrieval_event_id"] is not None, "Expected retrieval_event_id to be backpatched"
    finally:
        conn2.close()


def test_sync_pdi_path_does_not_capture_snapshot(ec_repo, ec_db, monkeypatch):
    """The sync PDI fast path in handler.py must not capture snapshots (no event to link)."""
    conn = ec_db
    repo_path = str(ec_repo)

    from entirecontext.core.decisions import create_decision, link_decision_to_file

    dec = create_decision(conn, title="Sync Path Decision", rationale="test")
    link_decision_to_file(conn, dec["id"], "src/sync.py")

    # Enable capture in config
    config = {
        "decisions": {
            "injection": {
                "inject_on_user_prompt": True,
                "top_k": 5,
                "max_tokens": 800,
                "min_confidence": 0.0,
                "inject_timeout_ms": 5000,
            },
            "capture_ranking_snapshots": True,
        }
    }

    from entirecontext.core.decision_prompt_surfacing import rank_decisions_for_prompt

    # Call rank_decisions_for_prompt with capture_snapshots=False (as sync path does)
    surfaced, warnings, snapshot_id = rank_decisions_for_prompt(
        conn,
        repo_path=repo_path,
        prompt_text="working on src/sync.py",
        config=config,
        capture_snapshots=False,
    )

    assert snapshot_id is None, "Sync path should not capture snapshots"
    count = conn.execute("SELECT COUNT(*) FROM ranking_snapshots").fetchone()[0]
    assert count == 0, "No snapshot rows should exist when capture_snapshots=False"
