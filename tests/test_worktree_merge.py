"""Tests for merging a legacy per-worktree DB into the canonical project DB."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from entirecontext.cli import app as ec_app
from entirecontext.core.worktree_merge import (
    MERGE_TABLES,
    SKIPPED_TABLES,
    WorktreeMergeError,
    merge_worktree,
)
from entirecontext.db import get_db
from entirecontext.db.connection import _configure_connection, _ECConnection, get_global_db
from entirecontext.db.global_schema import init_global_schema
from entirecontext.db.migration import init_schema

runner = CliRunner()


def _content(linked: Path, session_id: str, turn_id: str, text: str) -> tuple[str, str]:
    rel = f"content/{session_id}/{turn_id}.jsonl"
    path = linked / ".entirecontext" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return rel, hashlib.md5(text.encode()).hexdigest()


def _build_legacy_db(linked: Path, *, version: int = 21) -> Path:
    """Write ``<linked>/.entirecontext/db/local.db`` with sessions, turns, content, checkpoints and decisions."""
    db_path = linked / ".entirecontext" / "db" / "local.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path), factory=_ECConnection)
    _configure_connection(conn)
    init_schema(conn)
    conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('legacy-project', 'linked', ?)", (str(linked),))
    conn.execute("INSERT INTO agents (id, agent_type) VALUES ('agent-parent', 'claude')")
    conn.execute("INSERT INTO agents (id, agent_type, parent_agent_id) VALUES ('agent-child', 'sub', 'agent-parent')")
    conn.execute(
        "INSERT INTO sessions (id, project_id, agent_id, session_type, started_at, last_activity_at, total_turns) "
        "VALUES ('sess-1', 'legacy-project', 'agent-parent', 'claude', '2026-01-01', '2026-01-01', 2)"
    )
    for number, (turn_id, message) in enumerate((("turn-1", "unicorn migration"), ("turn-2", "second turn")), 1):
        rel, digest = _content(linked, "sess-1", turn_id, f'{{"msg": "{message}"}}\n')
        conn.execute(
            "INSERT INTO turns (id, session_id, turn_number, user_message, content_hash, timestamp) "
            "VALUES (?, 'sess-1', ?, ?, ?, '2026-01-01')",
            (turn_id, number, message, digest),
        )
        conn.execute(
            "INSERT INTO turn_content (turn_id, content_path, content_size, content_hash) VALUES (?, ?, 10, ?)",
            (turn_id, rel, digest),
        )
    conn.execute(
        "INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch) VALUES ('cp-1', 'sess-1', 'abc', 'wt')"
    )
    conn.execute(
        "INSERT INTO checkpoints (id, session_id, git_commit_hash, parent_checkpoint_id) "
        "VALUES ('cp-2', 'sess-1', 'def', 'cp-1')"
    )
    conn.execute("INSERT INTO assessments (id, checkpoint_id, verdict) VALUES ('as-1', 'cp-1', 'expand')")
    conn.execute("INSERT INTO decisions (id, title) VALUES ('dec-old', 'Old way')")
    conn.execute("INSERT INTO decisions (id, title) VALUES ('dec-new', 'New way')")
    conn.execute("UPDATE decisions SET superseded_by_id = 'dec-new' WHERE id = 'dec-old'")
    conn.execute("INSERT INTO decision_files (decision_id, file_path) VALUES ('dec-new', 'src/wt.py')")
    if version == 20:
        conn.execute("DROP INDEX IF EXISTS idx_sessions_workspace")
        for column in ("workspace_root", "worktree_git_dir", "git_branch"):
            conn.execute(f"ALTER TABLE sessions DROP COLUMN {column}")
        conn.execute("DROP INDEX IF EXISTS idx_projects_git_common_dir")
        conn.execute("ALTER TABLE projects DROP COLUMN git_common_dir")
        conn.execute("DROP TABLE decision_file_lineage_worktree_state")
    if version != 21:
        conn.execute("DELETE FROM schema_version")
        conn.execute("INSERT INTO schema_version (version, description) VALUES (?, 'test')", (version,))
    conn.close()
    return db_path


def _fingerprint(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), os.stat(path).st_mtime_ns


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608


@pytest.fixture
def merge_env(ec_worktree):
    main, linked = ec_worktree
    return main, linked, _build_legacy_db(linked)


def test_every_schema_table_is_merged_or_explicitly_skipped():
    conn = sqlite3.connect(":memory:", factory=_ECConnection)
    _configure_connection(conn)
    init_schema(conn)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'fts_%'"
        )
    }
    assert tables - set(MERGE_TABLES) - set(SKIPPED_TABLES) == set()


def test_merge_tables_are_in_foreign_key_order():
    conn = sqlite3.connect(":memory:", factory=_ECConnection)
    _configure_connection(conn)
    init_schema(conn)
    order = {table: index for index, table in enumerate(MERGE_TABLES)}
    for table in MERGE_TABLES:
        for ref in {r[2] for r in conn.execute(f"PRAGMA foreign_key_list({table})")}:
            assert ref in SKIPPED_TABLES or order[ref] <= order[table], (table, ref)


def test_dry_run_reports_without_writing(merge_env):
    main, linked, db_path = merge_env
    before = _fingerprint(db_path)
    target = get_db(str(main))
    counts_before = {t: _count(target, t) for t in ("sessions", "turns", "decisions", "projects")}
    target.close()

    report = merge_worktree(linked)

    assert report.applied is False
    assert report.inserted["sessions"] == 1
    assert report.inserted["turns"] == 2
    assert report.inserted["decisions"] == 2
    assert report.inserted["checkpoints"] == 2
    assert report.content == {"copy": 2}
    assert "projects" in report.skipped_tables
    assert report.divergent == [] and report.collisions == []
    assert _fingerprint(db_path) == before
    target = get_db(str(main))
    assert {t: _count(target, t) for t in counts_before} == counts_before
    target.close()
    assert not (main / ".entirecontext" / "content" / "sess-1").exists()
    assert not (main / ".entirecontext" / "backups").exists()


def test_apply_merges_rows_content_and_workspace_fields(merge_env):
    main, linked, db_path = merge_env
    before = _fingerprint(db_path)

    report = merge_worktree(linked, apply=True)

    assert report.applied is True
    assert report.inserted_total > 0
    target = get_db(str(main))
    try:
        project_id = target.execute("SELECT id FROM projects").fetchone()[0]
        session = target.execute("SELECT * FROM sessions WHERE id = 'sess-1'").fetchone()
        assert session["project_id"] == project_id
        assert session["workspace_root"] == str(linked.resolve())
        assert session["worktree_git_dir"].endswith("worktrees/linked")
        assert session["git_branch"] == "wt"
        assert target.execute("SELECT COUNT(*) FROM projects WHERE id = 'legacy-project'").fetchone()[0] == 0
        hits = target.execute("SELECT rowid FROM fts_turns WHERE fts_turns MATCH 'unicorn'").fetchall()
        assert len(hits) == 1
        superseded = target.execute("SELECT superseded_by_id FROM decisions WHERE id = 'dec-old'").fetchone()[0]
        assert superseded == "dec-new"
        assert target.execute("SELECT parent_checkpoint_id FROM checkpoints WHERE id = 'cp-2'").fetchone()[0] == "cp-1"
        assert target.execute("SELECT parent_agent_id FROM agents WHERE id = 'agent-child'").fetchone()[0] == (
            "agent-parent"
        )
        assert _count(target, "decision_files") == 1
        for row in target.execute("SELECT content_path, content_hash FROM turn_content"):
            copied = main / ".entirecontext" / row["content_path"]
            assert hashlib.md5(copied.read_bytes()).hexdigest() == row["content_hash"]
    finally:
        target.close()

    assert db_path.is_file()
    assert _fingerprint(db_path) == before
    for backup in (report.source_backup, report.target_backup):
        assert Path(backup).is_file()
    snapshot = sqlite3.connect(report.source_backup)
    try:
        assert snapshot.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 2
        assert snapshot.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    finally:
        snapshot.close()


def test_apply_is_idempotent(merge_env):
    _, linked, _ = merge_env
    merge_worktree(linked, apply=True)

    second = merge_worktree(linked, apply=True)

    assert second.inserted_total == 0
    assert second.identical["turns"] == 2
    assert second.content == {"already_present": 2}
    assert second.divergent == [] and second.collisions == []


def test_v20_source_fills_workspace_fields_and_branch(ec_worktree):
    main, linked = ec_worktree
    _build_legacy_db(linked, version=20)

    report = merge_worktree(linked, apply=True)

    assert report.source_version == 20
    target = get_db(str(main))
    try:
        session = target.execute("SELECT * FROM sessions WHERE id = 'sess-1'").fetchone()
        assert session["workspace_root"] == str(linked.resolve())
        assert session["worktree_git_dir"] is not None
        assert session["git_branch"] == "wt"
    finally:
        target.close()


def test_rejects_unsupported_source_version(ec_worktree):
    main, linked = ec_worktree
    db_path = _build_legacy_db(linked, version=19)
    before = _fingerprint(db_path)

    with pytest.raises(WorktreeMergeError, match="Unsupported source schema version 19"):
        merge_worktree(linked, apply=True)

    assert _fingerprint(db_path) == before
    assert not (main / ".entirecontext" / "backups").exists()


def test_divergent_rows_and_unique_collisions_are_reported_not_overwritten(merge_env):
    main, linked, _ = merge_env
    target = get_db(str(main))
    project_id = target.execute("SELECT id FROM projects").fetchone()[0]
    target.execute(
        "INSERT INTO sessions (id, project_id, agent_id, session_type, started_at, last_activity_at, total_turns) "
        "VALUES ('sess-1', ?, NULL, 'claude', '2026-01-01', '2026-01-01', 9)",
        (project_id,),
    )
    target.execute(
        "INSERT INTO turns (id, session_id, turn_number, user_message, content_hash, timestamp) "
        "VALUES ('turn-main', 'sess-1', 2, 'main turn', 'x', '2026-01-01')"
    )
    target.execute("INSERT INTO decisions (id, title) VALUES ('dec-new', 'Canonical title')")
    target.close()

    dry = merge_worktree(linked)
    report = merge_worktree(linked, apply=True)

    for result in (dry, report):
        divergent = {(d["table"], tuple(d["key"].values())): d["columns"] for d in result.divergent}
        assert {"agent_id", "total_turns"} <= set(divergent[("sessions", ("sess-1",))])
        assert "title" in divergent[("decisions", ("dec-new",))]
        collided = {(c["table"], tuple(c["key"].values())) for c in result.collisions}
        assert ("turns", ("turn-2",)) in collided
        assert ("turn_content", ("turn-2",)) in collided
        assert result.inserted["turns"] == 1
        orphan = "orphan_copy" if result.applied else "would_orphan"
        assert {"turn_id": "turn-2", "content_path": "content/sess-1/turn-2.jsonl", "status": orphan} in (
            result.content_issues
        )
    target = get_db(str(main))
    try:
        session = target.execute("SELECT total_turns, workspace_root FROM sessions WHERE id = 'sess-1'").fetchone()
        assert session["total_turns"] == 9
        assert session["workspace_root"] is None
        assert target.execute("SELECT title FROM decisions WHERE id = 'dec-new'").fetchone()[0] == "Canonical title"
        assert target.execute("SELECT superseded_by_id FROM decisions WHERE id = 'dec-old'").fetchone()[0] == (
            "dec-new"
        )
        turns = {r[0] for r in target.execute("SELECT id FROM turns WHERE session_id = 'sess-1'")}
        assert turns == {"turn-main", "turn-1"}
    finally:
        target.close()


def test_content_hash_mismatch_and_destination_conflict_are_not_copied(merge_env):
    main, linked, _ = merge_env
    (linked / ".entirecontext" / "content" / "sess-1" / "turn-1.jsonl").write_text("tampered\n")
    conflict = main / ".entirecontext" / "content" / "sess-1" / "turn-2.jsonl"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("canonical copy\n")

    report = merge_worktree(linked, apply=True)

    assert report.content == {"hash_mismatch": 1, "conflict": 1}
    statuses = {i["turn_id"]: i["status"] for i in report.content_issues}
    assert statuses == {"turn-1": "hash_mismatch", "turn-2": "conflict"}
    assert not (main / ".entirecontext" / "content" / "sess-1" / "turn-1.jsonl").exists()
    assert conflict.read_text() == "canonical copy\n"
    target = get_db(str(main))
    try:
        assert _count(target, "turn_content") == 0
        assert {r[0] for r in target.execute("SELECT id FROM turns")} == {"turn-1", "turn-2"}
    finally:
        target.close()


def test_content_path_escaping_entirecontext_is_not_copied(merge_env):
    main, linked, db_path = merge_env
    outside = linked / "escaped.jsonl"
    outside.write_text("secret\n")
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE turn_content SET content_path = '../escaped.jsonl' WHERE turn_id = 'turn-1'")
    conn.commit()
    conn.close()

    report = merge_worktree(linked, apply=True)

    assert report.content == {"unsafe_path": 1, "copy": 1}
    assert {"turn_id": "turn-1", "content_path": "../escaped.jsonl", "status": "unsafe_path"} in report.content_issues
    assert not (main / "escaped.jsonl").exists()
    target = get_db(str(main))
    try:
        assert [r[0] for r in target.execute("SELECT turn_id FROM turn_content")] == ["turn-2"]
    finally:
        target.close()


def test_absolute_content_path_outside_entirecontext_is_not_linked(merge_env, tmp_path):
    main, linked, db_path = merge_env
    outside = tmp_path / "elsewhere.jsonl"
    outside.write_text("elsewhere\n")
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE turn_content SET content_path = ? WHERE turn_id = 'turn-1'", (str(outside),))
    conn.commit()
    conn.close()

    report = merge_worktree(linked, apply=True)

    assert report.content == {"external": 1, "copy": 1}
    target = get_db(str(main))
    try:
        assert [r[0] for r in target.execute("SELECT turn_id FROM turn_content")] == ["turn-2"]
    finally:
        target.close()
    result = runner.invoke(ec_app, ["project", "merge-worktree", str(linked)])
    assert "row not merged" in result.output


def test_absolute_content_path_is_rewritten_relative(ec_worktree):
    main, linked = ec_worktree
    db_path = _build_legacy_db(linked)
    conn = sqlite3.connect(str(db_path))
    absolute = str(linked / ".entirecontext" / "content" / "sess-1" / "turn-1.jsonl")
    conn.execute("UPDATE turn_content SET content_path = ? WHERE turn_id = 'turn-1'", (absolute,))
    conn.commit()
    conn.close()

    merge_worktree(linked, apply=True)

    target = get_db(str(main))
    try:
        path = target.execute("SELECT content_path FROM turn_content WHERE turn_id = 'turn-1'").fetchone()[0]
    finally:
        target.close()
    assert path == "content/sess-1/turn-1.jsonl"
    assert (main / ".entirecontext" / path).is_file()


def test_stale_repo_index_row_is_removed_only_after_apply(merge_env):
    main, linked, db_path = merge_env
    gconn = get_global_db()
    init_global_schema(gconn)
    gconn.execute(
        "INSERT OR REPLACE INTO repo_index (repo_path, repo_name, db_path) VALUES (?, 'linked', ?)",
        (str(linked.resolve()), str(db_path)),
    )
    gconn.close()

    def rows():
        conn = get_global_db()
        try:
            return {r[0] for r in conn.execute("SELECT repo_path FROM repo_index")}
        finally:
            conn.close()

    merge_worktree(linked)
    assert str(linked.resolve()) in rows()

    report = merge_worktree(linked, apply=True)

    assert report.repo_index_removed == 1
    remaining = rows()
    assert str(linked.resolve()) not in remaining
    assert str(main.resolve()) in remaining


def test_failed_merge_keeps_repo_index_row(ec_worktree):
    _, linked = ec_worktree
    db_path = _build_legacy_db(linked, version=19)
    gconn = get_global_db()
    init_global_schema(gconn)
    gconn.execute(
        "INSERT OR REPLACE INTO repo_index (repo_path, repo_name, db_path) VALUES (?, 'linked', ?)",
        (str(linked.resolve()), str(db_path)),
    )
    gconn.close()

    with pytest.raises(WorktreeMergeError):
        merge_worktree(linked, apply=True)

    gconn = get_global_db()
    try:
        assert (
            gconn.execute("SELECT COUNT(*) FROM repo_index WHERE repo_path = ?", (str(linked.resolve()),)).fetchone()[0]
            == 1
        )
    finally:
        gconn.close()


def test_uninitialized_canonical_project_is_rejected(linked_worktree, isolated_global_db):
    main, linked = linked_worktree
    _build_legacy_db(linked)

    with pytest.raises(WorktreeMergeError, match="ec init"):
        merge_worktree(linked)

    assert not (main / ".entirecontext").exists()


def test_main_worktree_path_is_rejected(ec_repo):
    with pytest.raises(WorktreeMergeError, match="not a linked Git worktree"):
        merge_worktree(ec_repo)


def test_cli_dry_run_then_apply(merge_env):
    main, linked, db_path = merge_env

    dry = runner.invoke(ec_app, ["project", "merge-worktree", str(db_path)])
    assert dry.exit_code == 0, dry.output
    assert "Dry run" in dry.output
    assert "Would insert" in dry.output
    assert "Nothing was written" in dry.output

    applied = runner.invoke(ec_app, ["project", "merge-worktree", str(linked), "--apply", "--json"])
    assert applied.exit_code == 0, applied.output
    data = json.loads(applied.output)
    assert data["applied"] is True
    assert data["inserted"]["sessions"] == 1
    assert Path(data["source_backup"]).is_file()


def test_cli_reports_error_for_non_worktree(ec_repo):
    result = runner.invoke(ec_app, ["project", "merge-worktree", str(ec_repo)])

    assert result.exit_code == 1
    assert "not a linked Git worktree" in result.output
