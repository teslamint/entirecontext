"""Hooks in a linked worktree write to the canonical project and record the workspace."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.conftest import git_commit_env

from entirecontext.core.cross_repo import resolve_content_path
from entirecontext.core.session import create_session
from entirecontext.db import get_db
from entirecontext.hooks.session_lifecycle import on_post_commit, on_session_start
from entirecontext.hooks.turn_capture import on_stop, on_user_prompt


def _commit(repo: Path, name: str, message: str | None = None) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", name], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", message or f"add {name}"],
        check=True,
        capture_output=True,
        env=git_commit_env(),
    )
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _session(main: Path, session_id: str) -> dict:
    conn = get_db(str(main))
    try:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def test_session_start_in_linked_writes_main_db(ec_worktree):
    main, linked = ec_worktree
    linked_head = _commit(linked, "only_on_wt.txt")
    sub = linked / "sub"
    sub.mkdir()

    on_session_start({"session_id": "wt-s1", "cwd": str(sub), "source": "startup"})

    session = _session(main, "wt-s1")
    assert session["workspace_path"] == str(sub)
    assert session["workspace_root"] == str(linked)
    assert session["git_branch"] == "wt"
    assert Path(session["worktree_git_dir"]).parent == main / ".git" / "worktrees"
    assert json.loads(session["metadata"])["start_git_commit"] == linked_head
    assert not (linked / ".entirecontext").exists()


def test_turn_content_lands_under_main(ec_worktree, transcript_file):
    main, linked = ec_worktree
    cwd = str(linked)
    on_session_start({"session_id": "wt-s2", "cwd": cwd, "source": "startup"})
    on_user_prompt({"session_id": "wt-s2", "cwd": cwd, "prompt": "Fix the worktree bug"})
    transcript = transcript_file(
        [
            {"role": "user", "content": "Fix the worktree bug"},
            {"role": "assistant", "content": "Fixed the worktree bug"},
        ]
    )

    on_stop({"session_id": "wt-s2", "cwd": cwd, "transcript_path": transcript})

    conn = get_db(str(main))
    try:
        row = conn.execute(
            "SELECT tc.content_path FROM turn_content tc JOIN turns t ON t.id = tc.turn_id WHERE t.session_id = ?",
            ("wt-s2",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    content_file = main / ".entirecontext" / row["content_path"]
    assert content_file.is_file()
    assert resolve_content_path(str(main), row["content_path"]) == content_file.resolve()
    assert not (linked / ".entirecontext").exists()


def test_post_commit_attaches_to_linked_workspace_session(ec_worktree):
    main, linked = ec_worktree
    conn = get_db(str(main))
    try:
        project_id = conn.execute("SELECT id FROM projects").fetchone()["id"]
        create_session(conn, project_id, session_id="main-open", workspace_root=str(main))
        create_session(conn, project_id, session_id="linked-open", workspace_root=str(linked))
        conn.execute("UPDATE sessions SET last_activity_at = '2000-01-01' WHERE id = 'linked-open'")
    finally:
        conn.close()
    linked_head = _commit(linked, "feature.txt")

    on_post_commit({"cwd": str(linked)})

    conn = get_db(str(main))
    try:
        rows = conn.execute("SELECT session_id, git_branch, git_commit_hash FROM checkpoints").fetchall()
    finally:
        conn.close()
    assert [(r["session_id"], r["git_branch"], r["git_commit_hash"]) for r in rows] == [
        ("linked-open", "wt", linked_head)
    ]


def test_resume_refreshes_workspace_branch(ec_worktree):
    main, linked = ec_worktree
    on_session_start({"session_id": "wt-s3", "cwd": str(linked), "source": "startup"})
    subprocess.run(["git", "-C", str(linked), "checkout", "-b", "wt-2"], check=True, capture_output=True)

    on_session_start({"session_id": "wt-s3", "cwd": str(linked), "source": "resume"})

    assert _session(main, "wt-s3")["git_branch"] == "wt-2"


def test_codex_ingest_from_linked_lands_in_main(ec_worktree, tmp_path):
    from entirecontext.hooks.codex_ingest import _save_state, ingest_codex_notify_event

    main, linked = ec_worktree
    codex_home = tmp_path / "codex-home"
    session_dir = codex_home / "sessions" / "2026" / "02" / "24"
    session_dir.mkdir(parents=True)
    records = [
        {
            "type": "session_meta",
            "payload": {"id": "codex-wt", "timestamp": "2026-02-24T00:00:00Z", "cwd": str(linked)},
        },
        {
            "type": "response_item",
            "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]},
        },
        {
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "yo"}]},
        },
    ]
    (session_dir / "rollout-codex-wt.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    _save_state(str(main), {})

    ingest_codex_notify_event({"thread_id": "codex-wt", "cwd": str(linked), "codex_home": str(codex_home)})

    session = _session(main, "codex-wt")
    assert session["session_type"] == "codex"
    assert session["workspace_root"] == str(linked)
    assert session["git_branch"] == "wt"
    assert not (linked / ".entirecontext" / "db").exists()


def test_normal_repo_session_start_records_repo_root(ec_repo):
    on_session_start({"session_id": "plain-s1", "cwd": str(ec_repo), "source": "startup"})

    session = _session(ec_repo, "plain-s1")
    assert session["workspace_path"] == str(ec_repo)
    assert session["workspace_root"] == str(ec_repo)
    assert session["worktree_git_dir"] == str(ec_repo / ".git")
    assert session["git_branch"] is not None
