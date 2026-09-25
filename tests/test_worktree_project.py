"""Linked Git worktrees share one logical EntireContext project."""

from __future__ import annotations

import os

from entirecontext.core.context import RepoContext
from entirecontext.core.project import get_status, init_project
from entirecontext.core.session import create_session
from entirecontext.db import db_path_for, get_db, get_global_db


def _project_rows(main):
    conn = get_db(str(main))
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM projects").fetchall()]
    finally:
        conn.close()


def test_init_from_linked_joins_existing_project(ec_worktree):
    main, linked = ec_worktree
    main_project = _project_rows(main)[0]

    result = init_project(str(linked))

    assert result["id"] == main_project["id"]
    assert result["repo_path"] == str(main)
    assert result["workspace_root"] == str(linked)
    assert result["is_linked_worktree"] is True
    assert result["joined_existing"] is True
    assert result["legacy_worktree_db"] is None
    assert not (linked / ".entirecontext").exists()


def test_init_from_linked_initializes_main(linked_worktree, isolated_global_db):
    main, linked = linked_worktree

    result = init_project(str(linked))

    assert db_path_for(main).exists()
    assert not (linked / ".entirecontext").exists()
    assert result["joined_existing"] is False
    rows = _project_rows(main)
    assert len(rows) == 1
    assert rows[0]["name"] == main.name
    assert rows[0]["repo_path"] == str(main)
    assert rows[0]["git_common_dir"] == str(main / ".git")


def test_init_is_idempotent_across_worktrees(linked_worktree, isolated_global_db):
    main, linked = linked_worktree

    first = init_project(str(linked))
    second = init_project(str(main))
    third = init_project(str(linked))

    assert first["id"] == second["id"] == third["id"]
    assert len(_project_rows(main)) == 1


def test_repo_index_registers_only_canonical_root(linked_worktree, isolated_global_db):
    main, linked = linked_worktree

    init_project(str(main))
    init_project(str(linked))

    gconn = get_global_db()
    try:
        rows = gconn.execute("SELECT repo_path, db_path FROM repo_index").fetchall()
    finally:
        gconn.close()
    assert [(r["repo_path"], r["db_path"]) for r in rows] == [(str(main), str(db_path_for(main)))]


def test_status_from_linked_reports_logical_project_and_workspace(ec_worktree, monkeypatch):
    main, linked = ec_worktree
    monkeypatch.chdir(linked)

    status = get_status()

    assert status["initialized"] is True
    assert status["logical_project"]["repo_path"] == str(main)
    assert status["logical_project"]["git_common_dir"] == str(main / ".git")
    assert status["workspace"]["root"] == str(linked)
    assert status["workspace"]["branch"] == "wt"
    assert status["workspace"]["is_linked"] is True
    assert status["legacy_worktree_db"] is None


def test_active_session_is_scoped_to_workspace(ec_worktree):
    main, linked = ec_worktree
    conn = get_db(str(main))
    try:
        project_id = conn.execute("SELECT id FROM projects").fetchone()["id"]
        create_session(conn, project_id, session_id="main-session", workspace_root=str(main))
        create_session(conn, project_id, session_id="linked-session", workspace_root=str(linked))
        conn.execute("UPDATE sessions SET last_activity_at = '2000-01-01' WHERE id = 'linked-session'")
    finally:
        conn.close()

    main_status = get_status(str(main))
    linked_status = get_status(str(linked))

    assert main_status["active_session"]["id"] == "main-session"
    assert linked_status["active_session"]["id"] == "linked-session"
    assert main_status["session_count"] == linked_status["session_count"] == 2
    assert linked_status["workspace_session_count"] == 1


def test_status_reports_legacy_worktree_db_read_only(legacy_worktree_db, isolated_global_db):
    main, linked, legacy_db = legacy_worktree_db
    init_project(str(main))
    before = (legacy_db.read_bytes(), os.stat(legacy_db).st_mtime_ns)

    status = get_status(str(linked))

    legacy = status["legacy_worktree_db"]
    assert legacy["path"] == str(legacy_db)
    assert legacy["session_count"] == 1
    assert legacy["decision_count"] == 1
    assert (legacy_db.read_bytes(), os.stat(legacy_db).st_mtime_ns) == before


def test_repo_context_from_linked_path_opens_main_db(ec_worktree):
    main, linked = ec_worktree

    context = RepoContext.from_repo_path(str(linked), require_project=True)
    assert context is not None
    try:
        assert context.repo_path == str(main)
        assert context.project_root == str(main)
        assert context.workspace_root == str(linked)
        assert context.project["repo_path"] == str(main)
    finally:
        context.close()
    assert not (linked / ".entirecontext").exists()


def _two_workspace_sessions(main, linked, *, legacy: bool = False) -> None:
    """Main-checkout session plus a more recent linked-worktree session (both with a turn)."""
    conn = get_db(str(main))
    try:
        project_id = conn.execute("SELECT id FROM projects").fetchone()["id"]
        create_session(conn, project_id, session_id="main-session", workspace_root=None if legacy else str(main))
        create_session(conn, project_id, session_id="linked-session", workspace_root=str(linked))
        conn.execute("UPDATE sessions SET last_activity_at = '2000-01-01' WHERE id = 'main-session'")
        for sid in ("main-session", "linked-session"):
            conn.execute(
                "INSERT INTO turns (id, session_id, turn_number, content_hash, timestamp) "
                "VALUES (?, ?, 1, 'h', datetime('now'))",
                (f"{sid}-turn", sid),
            )
        conn.commit()
    finally:
        conn.close()


def test_detect_current_context_is_scoped_to_workspace(ec_worktree):
    from entirecontext.core.telemetry import detect_current_context

    main, linked = ec_worktree
    _two_workspace_sessions(main, linked)

    conn = get_db(str(main))
    try:
        assert detect_current_context(conn, workspace_root=str(main)) == ("main-session", "main-session-turn")
        assert detect_current_context(conn, workspace_root=str(linked)) == (
            "linked-session",
            "linked-session-turn",
        )
    finally:
        conn.close()


def test_legacy_null_workspace_session_is_not_used_by_linked_worktree(ec_worktree):
    from entirecontext.core.session import get_current_session

    main, linked = ec_worktree
    conn = get_db(str(main))
    try:
        project_id = conn.execute("SELECT id FROM projects").fetchone()["id"]
        create_session(conn, project_id, session_id="legacy-main-session")
        conn.commit()

        assert get_current_session(conn, workspace_root=str(main))["id"] == "legacy-main-session"
        assert get_current_session(conn, workspace_root=str(linked)) is None
    finally:
        conn.close()


def test_cli_telemetry_uses_current_workspace_session(ec_worktree, monkeypatch):
    from typer.testing import CliRunner

    from entirecontext.cli import app

    main, linked = ec_worktree
    _two_workspace_sessions(main, linked, legacy=True)
    runner = CliRunner()

    monkeypatch.chdir(main)
    current = runner.invoke(app, ["session", "current"])
    applied = runner.invoke(app, ["context", "apply", "reference", "--source-type", "turn", "--source-id", "x"])

    assert current.exit_code == 0, current.output
    assert "main-session" in current.output
    assert applied.exit_code == 0, applied.output

    monkeypatch.chdir(linked)
    linked_current = runner.invoke(app, ["session", "current"])
    assert "linked-session" in linked_current.output

    conn = get_db(str(main))
    try:
        row = conn.execute("SELECT session_id, turn_id FROM context_applications").fetchone()
    finally:
        conn.close()
    assert (row["session_id"], row["turn_id"]) == ("main-session", "main-session-turn")


def test_mcp_session_detection_is_scoped_to_workspace(ec_worktree, monkeypatch):
    from entirecontext.mcp import runtime

    main, linked = ec_worktree
    _two_workspace_sessions(main, linked)
    monkeypatch.delenv("ENTIRECONTEXT_REPO_PATH", raising=False)
    monkeypatch.setattr(runtime, "_workspace_roots", {})

    monkeypatch.chdir(main)
    conn, repo_path = runtime.get_repo_db()
    try:
        assert repo_path == str(main)
        assert runtime.detect_current_session(conn, repo_path) == "main-session"
        assert runtime.detect_current_context(conn, repo_path) == ("main-session", "main-session-turn")
    finally:
        conn.close()

    monkeypatch.chdir(linked)
    conn, repo_path = runtime.get_repo_db()
    try:
        assert repo_path == str(main)
        assert runtime.detect_current_session(conn, repo_path) == "linked-session"
    finally:
        conn.close()


def test_auto_distill_writes_lessons_to_active_workspace(ec_worktree, monkeypatch):
    from entirecontext.core import futures

    main, linked = ec_worktree
    monkeypatch.setattr(
        "entirecontext.core.config.load_config",
        lambda repo_path=None: {"futures": {"auto_distill": True, "lessons_output": "LESSONS.md"}},
    )

    assert futures.auto_distill_lessons(str(main), workspace_root=str(linked)) is True

    assert (linked / "LESSONS.md").exists()
    assert not (main / "LESSONS.md").exists()


def test_session_end_auto_distill_targets_session_workspace(ec_worktree, monkeypatch):
    from entirecontext.hooks import session_lifecycle

    main, linked = ec_worktree
    calls = []
    monkeypatch.setattr(
        "entirecontext.core.futures.auto_distill_lessons",
        lambda repo_path, **kwargs: calls.append((repo_path, kwargs)) or True,
    )

    session_lifecycle._maybe_trigger_auto_distill(str(main), workspace_root=str(linked))
    session_lifecycle._maybe_trigger_auto_distill(str(main), workspace_root=str(main))

    assert calls == [(str(main), {"workspace_root": str(linked)}), (str(main), {})]


def test_legacy_null_workspace_sessions_count_for_main_checkout_only(ec_worktree):
    from entirecontext.core.session import list_sessions

    main, linked = ec_worktree
    conn = get_db(str(main))
    try:
        project_id = conn.execute("SELECT id FROM projects").fetchone()["id"]
        create_session(conn, project_id, session_id="legacy-main-session")
        create_session(conn, project_id, session_id="linked-session", workspace_root=str(linked))
        conn.commit()

        main_ids = {s["id"] for s in list_sessions(conn, workspace_root=str(main))}
        linked_ids = {s["id"] for s in list_sessions(conn, workspace_root=str(linked))}
    finally:
        conn.close()

    assert main_ids == {"legacy-main-session"}
    assert linked_ids == {"linked-session"}
    assert get_status(str(main))["workspace_session_count"] == 1
    assert get_status(str(linked))["workspace_session_count"] == 1
