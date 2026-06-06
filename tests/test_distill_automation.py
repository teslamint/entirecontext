from __future__ import annotations

import datetime
import json
import subprocess
from unittest.mock import patch
from uuid import uuid4

from entirecontext.core.checkpoint import list_checkpoints


def _get_head(repo_path):
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_path, capture_output=True, text=True, check=True)
    return r.stdout.strip()


def _create_test_session(conn, repo_path=None):
    sid = str(uuid4())
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    project_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
    meta = None
    if repo_path:
        meta = json.dumps({"start_git_commit": _get_head(repo_path)})
    conn.execute(
        "INSERT INTO sessions (id, project_id, session_type, workspace_path, started_at, last_activity_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sid, project_id, "claude", "/tmp", now, now, meta),
    )
    return sid


def test_post_commit_creates_assessment(ec_repo, ec_db):
    """on_post_commit creates checkpoint AND assessment."""
    from entirecontext.core.session import create_session
    from entirecontext.hooks.session_lifecycle import on_post_commit

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
    session_id = create_session(ec_db, project_id, session_id=str(uuid4()), workspace_path=str(ec_repo))["id"]
    head = _get_head(ec_repo)
    meta = json.dumps({"start_git_commit": head})
    ec_db.execute(
        "UPDATE sessions SET started_at = ?, last_activity_at = ?, metadata = ? WHERE id = ?",
        (now, now, meta, session_id),
    )

    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "feat: endpoint"],
        cwd=ec_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    on_post_commit({"cwd": str(ec_repo)})

    checkpoints = list_checkpoints(ec_db)
    assert len(checkpoints) >= 1
    cp_id = checkpoints[0]["id"]
    assessment = ec_db.execute("SELECT * FROM assessments WHERE checkpoint_id = ?", (cp_id,)).fetchone()
    assert assessment is not None
    assert assessment["model_name"] == "rule-based"


def test_session_end_backfills_unassessed(ec_repo, ec_db):
    from entirecontext.core.checkpoint import create_checkpoint
    from entirecontext.hooks.session_lifecycle import _maybe_backfill_assessments

    session_id = _create_test_session(ec_db, str(ec_repo))

    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "feat: add endpoint"],
        cwd=ec_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    cp = create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "fix: follow-up"],
        cwd=ec_repo,
        capture_output=True,
        text=True,
        check=True,
    )

    with patch(
        "entirecontext.core.config.load_config",
        return_value={"futures": {"assess_backfill_window_days": 7, "assess_enrich": False}},
    ):
        _maybe_backfill_assessments(str(ec_repo), session_id)

    assessment = ec_db.execute(
        "SELECT model_name, feedback, feedback_reason FROM assessments WHERE checkpoint_id = ?",
        (cp["id"],),
    ).fetchone()
    assert assessment is not None
    assert assessment["model_name"] == "rule-based"
    assert assessment["feedback"] == "agree"
    assert "committed" in assessment["feedback_reason"]


def test_enrichment_worker_launched_by_default(ec_repo, ec_db):
    from entirecontext.core.checkpoint import create_checkpoint
    from entirecontext.hooks.session_lifecycle import _maybe_backfill_assessments

    session_id = _create_test_session(ec_db, str(ec_repo))
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "feat: add endpoint"],
        cwd=ec_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    create_checkpoint(ec_db, session_id, _get_head(ec_repo))

    with (
        patch(
            "entirecontext.core.config.load_config",
            return_value={"futures": {"assess_backfill_window_days": 7, "assess_enrich": True}},
        ),
        patch("entirecontext.core.async_worker.worker_status", return_value={"running": False, "pid": None}),
        patch("entirecontext.core.async_worker.launch_worker") as mock_launch,
    ):
        _maybe_backfill_assessments(str(ec_repo), session_id)

    mock_launch.assert_called_once()
    args = mock_launch.call_args.args
    kwargs = mock_launch.call_args.kwargs
    assert args[0] == str(ec_repo)
    assert args[1][1:] == ["-m", "entirecontext.cli", "futures", "enrich-backlog"]
    assert kwargs["pid_name"] == "worker-assess"
