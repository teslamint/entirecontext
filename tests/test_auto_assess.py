from __future__ import annotations

import json
import subprocess
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from entirecontext.core.auto_assess import (
    apply_git_evidence_feedback,
    auto_assess_checkpoint,
    backfill_unassessed_checkpoints,
    compute_rule_verdict,
    enrich_assessment,
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


def _create_enrichment_candidate(
    conn,
    session_id: str,
    git_commit_hash: str,
    verdict: str,
    created_at: datetime,
    *,
    assessment_id: str | None = None,
    feedback: str | None = None,
    model_name: str = "rule-based",
) -> str:
    checkpoint = create_checkpoint(conn, session_id, git_commit_hash)
    assessment = create_assessment(
        conn,
        checkpoint_id=checkpoint["id"],
        verdict=verdict,
        model_name=model_name,
    )
    candidate_id = assessment_id or assessment["id"]
    conn.execute(
        "UPDATE assessments SET id = ?, created_at = ?, feedback = ? WHERE id = ?",
        (candidate_id, created_at.isoformat(), feedback, assessment["id"]),
    )
    return candidate_id


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


def test_auto_assess_backfill_uses_correct_predecessor(ec_repo, ec_db):
    """When backfilling an older checkpoint, from_commit must be the predecessor, not the newest."""
    session_id = _create_test_session(ec_db, str(ec_repo))
    # cp1 at initial HEAD
    create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    # feat commit, then cp2
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "feat: first"], cwd=ec_repo, capture_output=True, check=True
    )
    cp2 = create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    # fix commit, then cp3
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "fix: second"], cwd=ec_repo, capture_output=True, check=True
    )
    create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    # Backfill cp2 (not the newest) — should see "feat: first" between cp1 and cp2
    result = auto_assess_checkpoint(ec_db, cp2["id"], str(ec_repo), session_id)
    assert result is not None
    assert result["verdict"] == "expand"


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


def test_get_enrichment_candidates_balances_available_verdicts(ec_repo, ec_db):
    session_id = _create_test_session(ec_db)
    head = _get_head(ec_repo)
    now = datetime.now(timezone.utc)
    candidate_ids = {
        "neutral-1": _create_enrichment_candidate(ec_db, session_id, head, "neutral", now - timedelta(minutes=1)),
        "expand-1": _create_enrichment_candidate(ec_db, session_id, head, "expand", now - timedelta(minutes=2)),
        "neutral-2": _create_enrichment_candidate(ec_db, session_id, head, "neutral", now - timedelta(minutes=3)),
        "narrow-1": _create_enrichment_candidate(ec_db, session_id, head, "narrow", now - timedelta(minutes=4)),
        "neutral-3": _create_enrichment_candidate(ec_db, session_id, head, "neutral", now - timedelta(minutes=5)),
        "expand-2": _create_enrichment_candidate(ec_db, session_id, head, "expand", now - timedelta(minutes=6)),
        "neutral-4": _create_enrichment_candidate(ec_db, session_id, head, "neutral", now - timedelta(minutes=7)),
    }

    first_round = get_enrichment_candidates(ec_db, limit=3)
    second_round = get_enrichment_candidates(ec_db, limit=5)

    assert [row["id"] for row in first_round] == [
        candidate_ids["neutral-1"],
        candidate_ids["expand-1"],
        candidate_ids["narrow-1"],
    ]
    assert [row["id"] for row in second_round] == [
        candidate_ids["neutral-1"],
        candidate_ids["expand-1"],
        candidate_ids["narrow-1"],
        candidate_ids["neutral-2"],
        candidate_ids["expand-2"],
    ]
    assert set(first_round[0]) == {
        "id",
        "checkpoint_id",
        "verdict",
        "model_name",
        "impact_summary",
        "git_commit_hash",
        "diff_summary",
        "session_id",
    }


def test_get_enrichment_candidates_orders_each_verdict_deterministically(ec_repo, ec_db):
    session_id = _create_test_session(ec_db)
    head = _get_head(ec_repo)
    created_at = datetime.now(timezone.utc)
    neutral_second_id = _create_enrichment_candidate(
        ec_db,
        session_id,
        head,
        "neutral",
        created_at,
        assessment_id="00000000-0000-0000-0000-000000000002",
    )
    neutral_first_id = _create_enrichment_candidate(
        ec_db,
        session_id,
        head,
        "neutral",
        created_at,
        assessment_id="00000000-0000-0000-0000-000000000003",
    )
    expand_first_id = _create_enrichment_candidate(
        ec_db,
        session_id,
        head,
        "expand",
        created_at,
        assessment_id="00000000-0000-0000-0000-000000000001",
    )

    candidates = get_enrichment_candidates(ec_db, limit=3)

    assert [row["id"] for row in candidates] == [
        neutral_first_id,
        expand_first_id,
        neutral_second_id,
    ]


def test_get_enrichment_candidates_excludes_feedbacked_rows(ec_repo, ec_db):
    session_id = _create_test_session(ec_db)
    head = _get_head(ec_repo)
    now = datetime.now(timezone.utc)
    _create_enrichment_candidate(
        ec_db,
        session_id,
        head,
        "expand",
        now,
        feedback="agree",
    )
    _create_enrichment_candidate(
        ec_db,
        session_id,
        head,
        "narrow",
        now - timedelta(seconds=30),
        feedback="disagree",
    )
    eligible_id = _create_enrichment_candidate(
        ec_db,
        session_id,
        head,
        "neutral",
        now - timedelta(minutes=1),
    )

    candidates = get_enrichment_candidates(ec_db)

    assert [row["id"] for row in candidates] == [eligible_id]


def test_get_enrichment_candidates_preserves_session_window_and_limit(ec_repo, ec_db):
    selected_session = _create_test_session(ec_db)
    other_session = _create_test_session(ec_db)
    head = _get_head(ec_repo)
    now = datetime.now(timezone.utc)
    selected_id = _create_enrichment_candidate(
        ec_db,
        selected_session,
        head,
        "neutral",
        now - timedelta(minutes=1),
    )
    _create_enrichment_candidate(
        ec_db,
        selected_session,
        head,
        "expand",
        now - timedelta(days=8),
    )
    _create_enrichment_candidate(
        ec_db,
        other_session,
        head,
        "narrow",
        now,
    )

    candidates = get_enrichment_candidates(
        ec_db,
        session_id=selected_session,
        window_days=7,
        limit=10,
    )
    limited_candidates = get_enrichment_candidates(
        ec_db,
        session_id=selected_session,
        window_days=30,
        limit=1,
    )

    assert [row["id"] for row in candidates] == [selected_id]
    assert [row["id"] for row in limited_candidates] == [selected_id]


def test_enrich_assessment_updates_model_name(ec_repo, ec_db, monkeypatch):
    session_id = _create_test_session(ec_db)
    cp = create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    assessment = create_assessment(ec_db, checkpoint_id=cp["id"], verdict="neutral", model_name="rule-based")
    mock_response = json.dumps(
        {
            "verdict": "expand",
            "impact_summary": "Added new feature",
            "roadmap_alignment": "Aligns with v0.8",
            "tidy_suggestion": "None",
        }
    )
    monkeypatch.setattr(
        "entirecontext.core.llm.get_backend",
        lambda *args, **kwargs: type("B", (), {"complete": lambda self, system, user: mock_response})(),
    )
    config = {"futures": {"default_backend": "claude", "default_model": ""}}

    ok = enrich_assessment(ec_db, assessment, str(ec_repo), config)

    assert ok is True
    row = ec_db.execute(
        "SELECT model_name, verdict, feedback, feedback_reason FROM assessments WHERE id = ?",
        (assessment["id"],),
    ).fetchone()
    assert row["model_name"] != "rule-based"
    assert row["verdict"] == "expand"
    assert row["feedback"] == "disagree"
    assert "revised" in row["feedback_reason"]


def test_enrich_assessment_agree_when_same_verdict(ec_repo, ec_db, monkeypatch):
    session_id = _create_test_session(ec_db)
    cp = create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    assessment = create_assessment(ec_db, checkpoint_id=cp["id"], verdict="expand", model_name="rule-based")
    mock_response = json.dumps(
        {
            "verdict": "expand",
            "impact_summary": "Added new feature",
            "roadmap_alignment": "Aligns with v0.8",
            "tidy_suggestion": "None",
        }
    )
    monkeypatch.setattr(
        "entirecontext.core.llm.get_backend",
        lambda *args, **kwargs: type("B", (), {"complete": lambda self, system, user: mock_response})(),
    )
    config = {"futures": {"default_backend": "claude", "default_model": ""}}

    ok = enrich_assessment(ec_db, assessment, str(ec_repo), config)

    assert ok is True
    row = ec_db.execute(
        "SELECT feedback, feedback_reason FROM assessments WHERE id = ?",
        (assessment["id"],),
    ).fetchone()
    assert row["feedback"] == "agree"
    assert "confirmed" in row["feedback_reason"]


def test_config_defaults():
    from entirecontext.core.config import DEFAULT_CONFIG

    futures = DEFAULT_CONFIG["futures"]
    assert futures["default_backend"] == "claude"
    assert futures["assess_enrich"] is True
    assert futures["assess_backfill_window_days"] == 7
