"""TFAR red-phase tests: confirm_candidate → link_decision_to_commit integration.

Invariants tested (option A — best-effort try/except:pass):
  INV1: checkpoint exists → decision_commits row created
  INV2: checkpoint_id=None → no decision_commits, promotion succeeds
  INV3: stale checkpoint FK → fails silently, decision persists
  INV4: link_decision_to_commit raises → swallowed, decision persists
  INV7: return value shape unchanged
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from entirecontext.core.decision_candidates import confirm_candidate
from entirecontext.core.decision_extraction import (
    CandidateDraft,
    DedupResult,
    compute_dedup_key,
    persist_candidate,
    score_confidence,
)
from entirecontext.core.project import get_project
from entirecontext.core.session import create_session
from entirecontext.core.turn import create_turn


def _seed_session(conn, ec_repo, session_id):
    project = get_project(str(ec_repo))
    return create_session(conn, project["id"], session_id=session_id)


def _seed_turn(conn, session_id, turn_number, summary, files=None):
    turn = create_turn(conn, session_id, turn_number, user_message=f"msg {turn_number}")
    conn.execute(
        "UPDATE turns SET assistant_summary = ?, files_touched = ?, turn_status = 'completed' WHERE id = ?",
        (summary, json.dumps(files) if files else None, turn["id"]),
    )
    conn.commit()
    return turn


def _seed_checkpoint(conn, session_id, commit_hash="abc123"):
    checkpoint_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO checkpoints (id, session_id, git_commit_hash, diff_summary, created_at) VALUES (?, ?, ?, ?, ?)",
        (checkpoint_id, session_id, commit_hash, "a.py|1", now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)).fetchone()
    return dict(row)


def _seed_candidate(ec_db, ec_repo, *, session_id, checkpoint_id=None, assessment_id=None):
    session = _seed_session(ec_db, ec_repo, session_id=session_id)
    draft = CandidateDraft(
        title="Commit-link test decision",
        rationale="a sufficiently long rationale to pass the heuristic",
        scope="test",
        rejected_alternatives=["alt"],
        supporting_evidence=[],
        source_type="session",
        source_id=session["id"],
        session_id=session["id"],
        checkpoint_id=checkpoint_id,
        assessment_id=assessment_id,
        files=["src/a.py"],
    )
    dr = DedupResult(dedup_key=compute_dedup_key(draft.title))
    score, breakdown = score_confidence(draft, dr)
    result = persist_candidate(ec_db, draft, score, breakdown, dr)
    return result.candidate_id


class TestConfirmCommitLink:
    def test_confirm_creates_commit_link_from_checkpoint(self, ec_repo, ec_db):
        """INV1: checkpoint exists → decision_commits row with matching commit_sha."""
        session = _seed_session(ec_db, ec_repo, "inv1-happy")
        _seed_turn(ec_db, session["id"], 1, "work", files=["src/a.py"])
        cp = _seed_checkpoint(ec_db, session["id"], commit_hash="deadbeef1234")

        cid = _seed_candidate(ec_db, ec_repo, session_id="inv1-happy-cand", checkpoint_id=cp["id"])
        result = confirm_candidate(ec_db, cid, reviewer="test")

        assert result["promoted"] is True
        decision_id = result["decision_id"]

        row = ec_db.execute(
            "SELECT commit_sha FROM decision_commits WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        assert row is not None, "decision_commits row must exist after confirm with checkpoint"
        assert row["commit_sha"] == "deadbeef1234"

    def test_confirm_no_checkpoint_skips_commit_link(self, ec_repo, ec_db):
        """INV2: checkpoint_id=None → no decision_commits, promotion succeeds."""
        cid = _seed_candidate(ec_db, ec_repo, session_id="inv2-no-cp")
        result = confirm_candidate(ec_db, cid, reviewer="test")

        assert result["promoted"] is True
        count = ec_db.execute(
            "SELECT COUNT(*) AS c FROM decision_commits WHERE decision_id = ?",
            (result["decision_id"],),
        ).fetchone()["c"]
        assert count == 0

    def test_confirm_stale_checkpoint_skips_commit_link(self, ec_repo, ec_db):
        """INV3: checkpoint deleted after candidate seeded → silent skip, decision persists."""
        session = _seed_session(ec_db, ec_repo, "inv3-stale")
        _seed_turn(ec_db, session["id"], 1, "work", files=["src/a.py"])
        cp = _seed_checkpoint(ec_db, session["id"], commit_hash="stale999")
        cp_id = cp["id"]

        cid = _seed_candidate(ec_db, ec_repo, session_id="inv3-stale-cand", checkpoint_id=cp_id)

        ec_db.execute("DELETE FROM checkpoints WHERE id = ?", (cp_id,))
        ec_db.commit()

        result = confirm_candidate(ec_db, cid, reviewer="test")
        assert result["promoted"] is True

        decision_count = ec_db.execute(
            "SELECT COUNT(*) AS c FROM decisions WHERE id = ?", (result["decision_id"],)
        ).fetchone()["c"]
        assert decision_count == 1

        commit_count = ec_db.execute(
            "SELECT COUNT(*) AS c FROM decision_commits WHERE decision_id = ?",
            (result["decision_id"],),
        ).fetchone()["c"]
        assert commit_count == 0

    def test_confirm_swallows_commit_link_failure(self, ec_repo, ec_db, monkeypatch):
        """INV4: link_decision_to_commit raises → swallowed, decision persists."""
        session = _seed_session(ec_db, ec_repo, "inv4-swallow")
        _seed_turn(ec_db, session["id"], 1, "work", files=["src/a.py"])
        cp = _seed_checkpoint(ec_db, session["id"], commit_hash="swallow999")

        cid = _seed_candidate(ec_db, ec_repo, session_id="inv4-swallow-cand", checkpoint_id=cp["id"])

        def failing_link(*args, **kwargs):
            raise RuntimeError("simulated link_decision_to_commit failure")

        monkeypatch.setattr(
            "entirecontext.core.decisions.link_decision_to_commit",
            failing_link,
        )

        result = confirm_candidate(ec_db, cid, reviewer="test")
        assert result["promoted"] is True

        decision_count = ec_db.execute(
            "SELECT COUNT(*) AS c FROM decisions WHERE id = ?", (result["decision_id"],)
        ).fetchone()["c"]
        assert decision_count == 1

        commit_count = ec_db.execute(
            "SELECT COUNT(*) AS c FROM decision_commits WHERE decision_id = ?",
            (result["decision_id"],),
        ).fetchone()["c"]
        assert commit_count == 0

    def test_confirm_return_value_shape(self, ec_repo, ec_db):
        """INV7: return value keys are exactly {candidate_id, decision_id, promoted}."""
        session = _seed_session(ec_db, ec_repo, "inv7-shape")
        _seed_turn(ec_db, session["id"], 1, "work", files=["src/a.py"])
        cp = _seed_checkpoint(ec_db, session["id"], commit_hash="shape123")

        cid = _seed_candidate(ec_db, ec_repo, session_id="inv7-shape-cand", checkpoint_id=cp["id"])
        result = confirm_candidate(ec_db, cid, reviewer="test")

        assert set(result.keys()) == {"candidate_id", "decision_id", "promoted"}
        assert result["promoted"] is True
