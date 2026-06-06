from __future__ import annotations

import datetime
import json
import subprocess
from uuid import uuid4

from entirecontext.core.checkpoint import list_checkpoints


def _get_head(repo_path):
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_path, capture_output=True, text=True, check=True)
    return r.stdout.strip()


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
