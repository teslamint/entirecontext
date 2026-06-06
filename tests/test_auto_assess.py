from __future__ import annotations

import json
import subprocess
from uuid import uuid4

from entirecontext.core.auto_assess import (
    apply_git_evidence_feedback,
    auto_assess_checkpoint,
    backfill_unassessed_checkpoints,
    compute_rule_verdict,
    get_enrichment_candidates,
)
from entirecontext.core.checkpoint import create_checkpoint
from entirecontext.core.futures import create_assessment
from entirecontext.core.git_utils import get_commit_messages


def test_get_commit_messages_returns_empty_when_no_from(git_repo):
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "feat: add API"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )
    msgs = get_commit_messages(str(git_repo), from_commit=None, to_commit="HEAD")
    assert msgs == []


def test_get_commit_messages_with_range(git_repo):
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    base = result.stdout.strip()
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "feat: add login"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "fix: typo"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )
    msgs = get_commit_messages(str(git_repo), from_commit=base, to_commit="HEAD")
    assert "fix: typo" in msgs
    assert "feat: add login" in msgs
    assert len(msgs) == 2


def test_get_commit_messages_invalid_range(git_repo):
    msgs = get_commit_messages(str(git_repo), from_commit="deadbeef", to_commit="HEAD")
    assert msgs == []


def test_get_commit_messages_same_commit(git_repo):
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    sha = result.stdout.strip()
    msgs = get_commit_messages(str(git_repo), from_commit=sha, to_commit=sha)
    assert msgs == []



def test_verdict_feat():
    assert compute_rule_verdict(["feat: add API"]) == "expand"


def test_verdict_feat_scoped():
    assert compute_rule_verdict(["feat(auth): add SSO"]) == "expand"


def test_verdict_revert():
    assert compute_rule_verdict(["revert: undo feature"]) == "narrow"


def test_verdict_fix():
    assert compute_rule_verdict(["fix: null check"]) == "neutral"


def test_verdict_mixed_feat_revert():
    assert compute_rule_verdict(["feat: add", "revert: undo"]) == "neutral"


def test_verdict_empty():
    assert compute_rule_verdict([]) == "neutral"


def test_verdict_case_insensitive():
    assert compute_rule_verdict(["FEAT: big thing"]) == "expand"


def test_verdict_non_conventional():
    assert compute_rule_verdict(["Update README"]) == "neutral"


def test_verdict_merge_commit():
    assert compute_rule_verdict(["Merge branch 'feature' into 'main'"]) == "neutral"


def _get_head(repo_path):
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_path, capture_output=True, text=True)
    return r.stdout.strip()


def _create_test_session(conn, repo_path=None):
    sid = str(uuid4())
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
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


def test_auto_assess_creates_assessment(ec_repo, ec_db):
    session_id = _create_test_session(ec_db, str(ec_repo))
    subprocess.run(["git", "commit", "--allow-empty", "-m", "feat: add endpoint"], cwd=ec_repo, capture_output=True)
    head = _get_head(ec_repo)
    cp = create_checkpoint(ec_db, session_id, head)
    result = auto_assess_checkpoint(ec_db, cp["id"], str(ec_repo), session_id)
    assert result is not None
    assert result["verdict"] == "expand"
    assert result["model_name"] == "rule-based"


def test_auto_assess_no_prior_returns_neutral(ec_repo, ec_db):
    session_id = _create_test_session(ec_db)
    head = _get_head(ec_repo)
    cp = create_checkpoint(ec_db, session_id, head)
    result = auto_assess_checkpoint(ec_db, cp["id"], str(ec_repo), session_id)
    assert result is not None
    assert result["verdict"] == "neutral"


def test_auto_assess_never_raises(ec_repo, ec_db):
    result = auto_assess_checkpoint(ec_db, "nonexistent", "/bad/path", "bad-session")
    assert result is None


def test_backfill_creates_missing_assessments(ec_repo, ec_db):
    session_id = _create_test_session(ec_db)
    head = _get_head(ec_repo)
    cp1 = create_checkpoint(ec_db, session_id, head)
    create_checkpoint(ec_db, session_id, head)
    create_assessment(ec_db, checkpoint_id=cp1["id"], verdict="neutral")
    count = backfill_unassessed_checkpoints(ec_db, str(ec_repo), session_id=session_id)
    assert count == 1


def test_backfill_respects_window(ec_repo, ec_db):
    session_id = _create_test_session(ec_db)
    head = _get_head(ec_repo)
    cp = create_checkpoint(ec_db, session_id, head)
    ec_db.execute("UPDATE checkpoints SET created_at = datetime('now', '-30 days') WHERE id = ?", (cp["id"],))
    count = backfill_unassessed_checkpoints(ec_db, str(ec_repo), window_days=7)
    assert count == 0


def test_git_evidence_feedback(ec_repo, ec_db):
    session_id = _create_test_session(ec_db, str(ec_repo))
    head = _get_head(ec_repo)
    cp = create_checkpoint(ec_db, session_id, head)
    create_assessment(ec_db, checkpoint_id=cp["id"], verdict="neutral", model_name="rule-based")
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "fix: something"],
        cwd=ec_repo,
        check=True,
        capture_output=True,
    )
    count = apply_git_evidence_feedback(ec_db, str(ec_repo), session_id=session_id)
    assert count == 1
    row = ec_db.execute(
        "SELECT feedback, feedback_reason FROM assessments WHERE checkpoint_id = ?",
        (cp["id"],),
    ).fetchone()
    assert row["feedback"] == "agree"
    assert "committed" in row["feedback_reason"]


def test_git_evidence_feedback_skips_already_feedbacked(ec_repo, ec_db):
    session_id = _create_test_session(ec_db, str(ec_repo))
    head = _get_head(ec_repo)
    cp = create_checkpoint(ec_db, session_id, head)
    assessment = create_assessment(ec_db, checkpoint_id=cp["id"], verdict="neutral", model_name="rule-based")
    ec_db.execute(
        "UPDATE assessments SET feedback = ?, feedback_reason = ? WHERE id = ?",
        ("agree", "manual", assessment["id"]),
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "fix: something else"],
        cwd=ec_repo,
        check=True,
        capture_output=True,
    )
    count = apply_git_evidence_feedback(ec_db, str(ec_repo), session_id=session_id)
    assert count == 0


def test_get_enrichment_candidates_only_rule_based(ec_repo, ec_db):
    session_id = _create_test_session(ec_db)
    head = _get_head(ec_repo)
    cp = create_checkpoint(ec_db, session_id, head)
    create_assessment(ec_db, checkpoint_id=cp["id"], verdict="neutral", model_name="rule-based")
    create_assessment(ec_db, verdict="expand", model_name="gpt-4o-mini")
    candidates = get_enrichment_candidates(ec_db)
    assert len(candidates) == 1
    assert candidates[0]["model_name"] == "rule-based"
