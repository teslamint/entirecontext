"""E2E wiring test: capture→distill→retrieve→intervene→outcome.

Proves the v1.0 loop gate mechanically: all five stages complete in-process
without human intervention. LLM mocked; everything else runs through real
business logic. This is a wiring regression test, not a production proof.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest

from entirecontext.core.auto_apply import infer_applied_decisions
from entirecontext.core.auto_assess import auto_assess_checkpoint
from entirecontext.core.decisions import (
    create_decision,
    get_decision,
    link_decision_to_file,
    rank_related_decisions,
    _load_ranking_weights,
)
from entirecontext.core.session import create_session
from entirecontext.core.turn import create_turn


def _write_repo_config(repo: Path, body: str) -> None:
    cfg = repo / ".entirecontext" / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(body, encoding="utf-8")


_MOCK_LLM_RESPONSE = json.dumps([
    {
        "title": "Use SQLite WAL mode for concurrent reads",
        "rationale": "WAL allows readers and writers to operate concurrently",
        "scope": "database",
        "rejected_alternatives": [
            {"alternative": "Default journal mode", "reason": "Blocks concurrent readers"}
        ],
    }
])


class TestAutonomousLoopE2E:
    """Wiring test: all five loop stages complete in-process."""

    def test_full_loop(self, ec_repo, ec_db, monkeypatch):
        repo_path = str(ec_repo)

        _write_repo_config(ec_repo, "\n".join([
            "[decisions]",
            "auto_extract = true",
            "infer_applied_on_session_end = true",
            "infer_outcome_type = true",
            "",
            "[decisions.ranking]",
            "file_exact_weight = 10.0",
        ]))

        (ec_repo / "src").mkdir(exist_ok=True)
        (ec_repo / "src" / "db.py").write_text("# database module\n")
        subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feat: add WAL mode"],
            cwd=repo_path, capture_output=True,
        )
        commit_hash = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path, capture_output=True, text=True,
        ).stdout.strip()

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

        # ── CAPTURE ──
        session1 = create_session(ec_db, project_id)
        for i, (user, assistant) in enumerate([
            ("How should we configure SQLite?", "We decided to use WAL mode"),
            ("What about the journal?", "WAL lets readers not block writers"),
            ("Update src/db.py", "Updated src/db.py with WAL pragma"),
        ], 1):
            turn = create_turn(
                ec_db,
                session_id=session1["id"],
                turn_number=i,
                user_message=user,
                assistant_summary=assistant,
                turn_status="completed",
            )
            ec_db.execute(
                "UPDATE turns SET files_touched = ?, tools_used = ? WHERE id = ?",
                (json.dumps(["src/db.py"]), json.dumps(["Edit"]), turn["id"]),
            )
        ec_db.commit()

        cp_id = str(uuid.uuid4())
        ec_db.execute(
            "INSERT INTO checkpoints (id, session_id, git_commit_hash, diff_summary) "
            "VALUES (?, ?, ?, ?)",
            (cp_id, session1["id"], commit_hash, "src/db.py | 3 +++"),
        )
        ec_db.commit()

        # ── DISTILL ──
        assessment = auto_assess_checkpoint(ec_db, cp_id, repo_path, session1["id"])
        assert assessment is not None

        monkeypatch.setattr(
            "entirecontext.core.decision_extraction.call_extraction_llm",
            lambda text, repo, source_type="session": _MOCK_LLM_RESPONSE,
        )

        from entirecontext.core.decision_extraction import run_extraction

        extraction = run_extraction(ec_db, session1["id"], repo_path)
        assert extraction.candidates_inserted > 0, (
            f"Expected candidates, got: {extraction.__dict__}"
        )

        # Confirm candidate → decision
        candidate = ec_db.execute(
            "SELECT id, title, rationale, scope FROM decision_candidates "
            "WHERE review_status = 'pending' LIMIT 1"
        ).fetchone()
        assert candidate is not None

        decision = create_decision(
            ec_db,
            title=candidate["title"],
            rationale=candidate["rationale"] or "",
            scope=candidate["scope"] or "",
        )
        decision_id = decision["id"]
        ec_db.execute(
            "UPDATE decision_candidates SET review_status = 'confirmed', promoted_decision_id = ? WHERE id = ?",
            (decision_id, candidate["id"]),
        )
        ec_db.commit()

        link_decision_to_file(ec_db, decision_id, "src/db.py")

        # ── RETRIEVE ──
        from entirecontext.core.config import load_config

        config = load_config(repo_path)
        weights = _load_ranking_weights(config)

        ranked = rank_related_decisions(ec_db, file_paths=["src/db.py"], ranking=weights)
        assert any(r["id"] == decision_id for r in ranked), (
            f"Decision {decision_id} not found in ranked: {[r['id'] for r in ranked]}"
        )

        # Simulate retrieval_selection (what PDI does)
        # retrieval_selections requires a retrieval_events FK
        session2 = create_session(ec_db, project_id)
        retrieval_event_id = str(uuid.uuid4())
        ec_db.execute(
            "INSERT INTO retrieval_events "
            "(id, session_id, source, search_type, target, query, result_count) "
            "VALUES (?, ?, 'test', 'session_start', 'decisions', 'WAL mode', 1)",
            (retrieval_event_id, session2["id"]),
        )
        selection_id = str(uuid.uuid4())
        ec_db.execute(
            "INSERT INTO retrieval_selections "
            "(id, retrieval_event_id, session_id, result_type, result_id, rank) "
            "VALUES (?, ?, ?, 'decision', ?, 1)",
            (selection_id, retrieval_event_id, session2["id"], decision_id),
        )
        ec_db.commit()

        # ── INTERVENE ──
        turn2 = create_turn(
            ec_db,
            session_id=session2["id"],
            turn_number=1,
            user_message="Optimize WAL checkpoint interval",
            assistant_summary="Set WAL auto-checkpoint to 1000 pages",
            turn_status="completed",
        )
        ec_db.execute(
            "UPDATE turns SET files_touched = ?, tools_used = ? WHERE id = ?",
            (json.dumps(["src/db.py"]), json.dumps(["Edit"]), turn2["id"]),
        )
        ec_db.commit()

        # ── OUTCOME ──
        result = infer_applied_decisions(ec_db, session2["id"], repo_path=repo_path)
        assert result["applied_count"] > 0, f"No applications inferred: {result}"

        outcomes = ec_db.execute(
            "SELECT outcome_type FROM decision_outcomes WHERE decision_id = ?",
            (decision_id,),
        ).fetchall()
        assert any(o["outcome_type"] == "accepted" for o in outcomes), (
            f"Expected 'accepted', got: {[o['outcome_type'] for o in outcomes]}"
        )
