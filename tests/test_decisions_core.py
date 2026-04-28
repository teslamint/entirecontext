"""Tests for decision domain core APIs."""

from __future__ import annotations

import pytest

from entirecontext.core.decisions import (
    check_staleness,
    create_decision,
    fts_search_decisions,
    get_decision,
    get_decision_quality_summary,
    hybrid_search_decisions,
    link_decision_to_assessment,
    link_decision_to_checkpoint,
    link_decision_to_commit,
    link_decision_to_file,
    list_decision_outcomes,
    list_decisions,
    record_decision_outcome,
    supersede_decision,
    unlink_decision_from_assessment,
    unlink_decision_from_checkpoint,
    unlink_decision_from_commit,
    unlink_decision_from_file,
    update_decision,
    update_decision_staleness,
)
from entirecontext.core.futures import create_assessment, list_assessments
from entirecontext.core.project import get_project
from entirecontext.core.decisions import (
    _DEFAULT_RANKING_WEIGHTS,
    RankingWeights,
    _load_ranking_weights,
    rank_related_decisions,
)
from entirecontext.core.session import create_session
from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection
from entirecontext.core.turn import create_turn


class TestDecisionsCore:
    def test_create_and_get_decision(self, ec_db):
        decision = create_decision(
            ec_db,
            title="Use queue based webhook retries",
            rationale="Prevent retry storms",
            scope="webhook",
            rejected_alternatives=["cron polling"],
            supporting_evidence=[{"kind": "incident", "id": "INC-12"}],
        )

        fetched = get_decision(ec_db, decision["id"])
        assert fetched is not None
        assert fetched["title"] == "Use queue based webhook retries"
        assert fetched["rejected_alternatives"] == ["cron polling"]
        assert fetched["supporting_evidence"][0]["id"] == "INC-12"

    def test_prefix_lookup(self, ec_db):
        decision = create_decision(ec_db, title="Adopt api v2")
        fetched = get_decision(ec_db, decision["id"][:10])
        assert fetched is not None
        assert fetched["id"] == decision["id"]

    def test_list_decisions_filter_by_status(self, ec_db):
        create_decision(ec_db, title="Fresh one", staleness_status="fresh")
        create_decision(ec_db, title="Stale one", staleness_status="stale")

        stale = list_decisions(ec_db, staleness_status="stale")
        assert len(stale) == 1
        assert stale[0]["title"] == "Stale one"

    def test_list_decisions_excludes_contradicted_by_default(self, ec_db):
        fresh = create_decision(ec_db, title="Fresh keeper")
        contradicted = create_decision(ec_db, title="Contradicted hidden")
        update_decision_staleness(ec_db, contradicted["id"], "contradicted")

        default_results = list_decisions(ec_db)
        default_ids = [d["id"] for d in default_results]
        assert fresh["id"] in default_ids
        assert contradicted["id"] not in default_ids

        inclusive_results = list_decisions(ec_db, include_contradicted=True)
        inclusive_ids = [d["id"] for d in inclusive_results]
        assert fresh["id"] in inclusive_ids
        assert contradicted["id"] in inclusive_ids

    def test_list_decisions_file_filter_escapes_like_wildcards(self, ec_db):
        one = create_decision(ec_db, title="Target")
        two = create_decision(ec_db, title="Other")
        link_decision_to_file(ec_db, one["id"], "src/%/target.py")
        link_decision_to_file(ec_db, two["id"], "src/any/target.py")

        filtered = list_decisions(ec_db, file_path="src/%")
        assert len(filtered) == 1
        assert filtered[0]["id"] == one["id"]

    def test_link_assessment_and_file(self, ec_db):
        assessment = create_assessment(ec_db, verdict="expand", impact_summary="enables retries")
        decision = create_decision(ec_db, title="Queue retries")

        rel = link_decision_to_assessment(ec_db, decision["id"][:12], assessment["id"][:12], relation_type="supports")
        file_rel = link_decision_to_file(ec_db, decision["id"][:12], "src/service/retry.py")

        assert rel["assessment_id"] == assessment["id"]
        assert file_rel["file_path"] == "src/service/retry.py"

        enriched = get_decision(ec_db, decision["id"])
        assert enriched is not None
        assert enriched["assessments"][0]["assessment_id"] == assessment["id"]
        assert "src/service/retry.py" in enriched["files"]

    def test_rank_related_decisions_escapes_assessment_prefix_wildcards(self, ec_db):
        ec_db.execute(
            """INSERT INTO assessments (
                id, checkpoint_id, verdict, impact_summary, roadmap_alignment,
                tidy_suggestion, diff_summary, model_name, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("abc%foo-1", None, "expand", "literal percent", None, None, None, None, "2025-01-01T00:00:00+00:00"),
        )
        ec_db.execute(
            """INSERT INTO assessments (
                id, checkpoint_id, verdict, impact_summary, roadmap_alignment,
                tidy_suggestion, diff_summary, model_name, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("abcXfoo-2", None, "expand", "wildcard match", None, None, None, None, "2025-01-01T00:00:01+00:00"),
        )
        first = create_decision(ec_db, title="Literal match")
        second = create_decision(ec_db, title="Wildcard candidate")
        link_decision_to_assessment(ec_db, first["id"], "abc%foo-1")
        link_decision_to_assessment(ec_db, second["id"], "abcXfoo-2")

        ranked = rank_related_decisions(ec_db, assessment_ids=["abc%f"], limit=10)

        assert [item["id"] for item in ranked] == [first["id"]]

    def test_link_decision_to_assessment_keeps_distinct_relation_types(self, ec_db):
        assessment = create_assessment(ec_db, verdict="expand", impact_summary="enables retries")
        decision = create_decision(ec_db, title="Queue retries")

        supports = link_decision_to_assessment(ec_db, decision["id"], assessment["id"], relation_type="supports")
        supports_again = link_decision_to_assessment(ec_db, decision["id"], assessment["id"], relation_type="supports")
        informed_by = link_decision_to_assessment(ec_db, decision["id"], assessment["id"], relation_type="informed_by")

        rows = ec_db.execute(
            "SELECT relation_type FROM decision_assessments WHERE decision_id = ? AND assessment_id = ? ORDER BY relation_type",
            (decision["id"], assessment["id"]),
        ).fetchall()

        assert supports["relation_type"] == "supports"
        assert supports_again["relation_type"] == "supports"
        assert informed_by["relation_type"] == "informed_by"
        assert [row["relation_type"] for row in rows] == ["informed_by", "supports"]

    def test_link_checkpoint_and_commit(self, ec_repo, ec_db):
        from entirecontext.core.checkpoint import create_checkpoint

        decision = create_decision(ec_db, title="pin dependency strategy")
        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="decision-core-session")
        checkpoint = create_checkpoint(ec_db, session["id"], git_commit_hash="abc123", git_branch="main")

        checkpoint_rel = link_decision_to_checkpoint(ec_db, decision["id"][:12], checkpoint["id"][:12])
        commit_rel = link_decision_to_commit(ec_db, decision["id"][:12], "deadbeef")

        assert checkpoint_rel["checkpoint_id"] == checkpoint["id"]
        assert commit_rel["commit_sha"] == "deadbeef"

    def test_staleness_transition(self, ec_db):
        decision = create_decision(ec_db, title="initial")
        updated = update_decision_staleness(ec_db, decision["id"][:12], "superseded")
        assert updated["staleness_status"] == "superseded"

    def test_invalid_status_rejected(self, ec_db):
        decision = create_decision(ec_db, title="x")
        with pytest.raises(ValueError, match="Invalid status"):
            update_decision_staleness(ec_db, decision["id"], "unknown")

    def test_assessment_flow_regression_unchanged(self, ec_db):
        create_assessment(ec_db, verdict="expand", impact_summary="A")
        create_assessment(ec_db, verdict="narrow", impact_summary="B")

        all_items = list_assessments(ec_db, limit=10)
        assert len(all_items) == 2
        assert {item["verdict"] for item in all_items} == {"expand", "narrow"}

    def test_list_decisions_parses_json_fields(self, ec_db):
        create_decision(
            ec_db, title="cache policy", rejected_alternatives=["disable-cache"], supporting_evidence=["loadtest"]
        )
        decisions = list_decisions(ec_db, limit=1)
        assert isinstance(decisions[0]["rejected_alternatives"], list)
        assert isinstance(decisions[0]["supporting_evidence"], list)

    def test_record_decision_outcome_with_selection_and_summary(self, ec_repo, ec_db):
        decision = create_decision(ec_db, title="Use queue based retries")
        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="decision-outcome-session")
        turn = create_turn(ec_db, session["id"], 1, user_message="search retries", assistant_summary="found decision")
        event = record_retrieval_event(
            ec_db,
            source="cli",
            search_type="decision_related",
            target="decision",
            query="retries",
            result_count=1,
            latency_ms=4,
            session_id=session["id"],
            turn_id=turn["id"],
        )
        selection = record_retrieval_selection(ec_db, event["id"], "decision", decision["id"], rank=1)

        created = record_decision_outcome(
            ec_db,
            decision["id"][:12],
            "accepted",
            retrieval_selection_id=selection["id"],
            note="Applied the retry design",
        )

        outcomes = list_decision_outcomes(ec_db, decision["id"])
        summary = get_decision_quality_summary(ec_db, decision["id"])
        fetched = get_decision(ec_db, decision["id"])

        assert created["retrieval_selection_id"] == selection["id"]
        assert outcomes[0]["outcome_type"] == "accepted"
        assert summary["counts"]["accepted"] == 1
        assert summary["quality_score"] == 1.0
        assert fetched is not None
        assert fetched["quality_summary"]["total_outcomes"] == 1
        assert fetched["recent_outcomes"][0]["note"] == "Applied the retry design"

    def test_record_decision_outcome_rejects_non_decision_selection(self, ec_repo, ec_db):
        decision = create_decision(ec_db, title="Use queue based retries")
        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="decision-outcome-invalid")
        turn = create_turn(ec_db, session["id"], 1, user_message="search retries", assistant_summary="found turn")
        event = record_retrieval_event(
            ec_db,
            source="cli",
            search_type="regex",
            target="turn",
            query="retries",
            result_count=1,
            latency_ms=4,
            session_id=session["id"],
            turn_id=turn["id"],
        )
        selection = record_retrieval_selection(ec_db, event["id"], "turn", "t-source", rank=1)

        with pytest.raises(ValueError, match="must point to a decision"):
            record_decision_outcome(ec_db, decision["id"], "accepted", retrieval_selection_id=selection["id"])

    def test_record_decision_outcome_rejects_partial_context_override(self, ec_repo, ec_db):
        decision = create_decision(ec_db, title="Use queue based retries")
        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="decision-outcome-partial")
        turn = create_turn(ec_db, session["id"], 1, user_message="search retries", assistant_summary="found decision")
        event = record_retrieval_event(
            ec_db,
            source="cli",
            search_type="decision_related",
            target="decision",
            query="retries",
            result_count=1,
            latency_ms=4,
            session_id=session["id"],
            turn_id=turn["id"],
        )
        selection = record_retrieval_selection(ec_db, event["id"], "decision", decision["id"], rank=1)

        with pytest.raises(ValueError, match="session_id and turn_id must be provided together"):
            record_decision_outcome(
                ec_db,
                decision["id"],
                "accepted",
                retrieval_selection_id=selection["id"],
                session_id=session["id"],
            )

    def test_record_decision_outcome_accepts_consistent_explicit_context_override(self, ec_repo, ec_db):
        decision = create_decision(ec_db, title="Use queue based retries")
        project = get_project(str(ec_repo))
        selection_session = create_session(ec_db, project["id"], session_id="decision-outcome-source")
        selection_turn = create_turn(
            ec_db, selection_session["id"], 1, user_message="search retries", assistant_summary="found decision"
        )
        event = record_retrieval_event(
            ec_db,
            source="cli",
            search_type="decision_related",
            target="decision",
            query="retries",
            result_count=1,
            latency_ms=4,
            session_id=selection_session["id"],
            turn_id=selection_turn["id"],
        )
        selection = record_retrieval_selection(ec_db, event["id"], "decision", decision["id"], rank=1)
        override_session = create_session(ec_db, project["id"], session_id="decision-outcome-override")
        override_turn = create_turn(
            ec_db, override_session["id"], 1, user_message="apply retries", assistant_summary="used decision"
        )

        created = record_decision_outcome(
            ec_db,
            decision["id"],
            "accepted",
            retrieval_selection_id=selection["id"],
            session_id=override_session["id"],
            turn_id=override_turn["id"],
        )

        assert created["session_id"] == override_session["id"]
        assert created["turn_id"] == override_turn["id"]

    def test_record_decision_outcome_rejects_nonexistent_session(self, ec_repo, ec_db):
        decision = create_decision(ec_db, title="Use queue based retries")
        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="decision-outcome-exists")
        turn = create_turn(ec_db, session["id"], 1, user_message="search retries", assistant_summary="found")

        with pytest.raises(ValueError, match="Session .* not found"):
            record_decision_outcome(
                ec_db,
                decision["id"],
                "accepted",
                session_id="nonexistent-session-id",
                turn_id=turn["id"],
            )

    def test_record_decision_outcome_rejects_mismatched_explicit_context_override(self, ec_repo, ec_db):
        decision = create_decision(ec_db, title="Use queue based retries")
        project = get_project(str(ec_repo))
        session_one = create_session(ec_db, project["id"], session_id="decision-outcome-mismatch-1")
        turn_one = create_turn(ec_db, session_one["id"], 1, user_message="search retries", assistant_summary="found")
        session_two = create_session(ec_db, project["id"], session_id="decision-outcome-mismatch-2")

        with pytest.raises(ValueError, match="does not belong to session_id"):
            record_decision_outcome(
                ec_db,
                decision["id"],
                "accepted",
                session_id=session_two["id"],
                turn_id=turn_one["id"],
            )

    def test_rank_related_decisions_applies_quality_adjustment(self, ec_db):
        promoted = create_decision(ec_db, title="Promoted")
        demoted = create_decision(ec_db, title="Demoted")
        link_decision_to_file(ec_db, promoted["id"], "src/service/retry.py")
        link_decision_to_file(ec_db, demoted["id"], "src/service/retry.py")
        record_decision_outcome(ec_db, promoted["id"], "accepted")
        record_decision_outcome(ec_db, promoted["id"], "accepted")
        # Use `ignored` instead of `contradicted` — under new staleness policy,
        # contradicted decisions are excluded from ranking results by default,
        # so this test now validates quality-score demotion via ignored signal.
        record_decision_outcome(ec_db, demoted["id"], "ignored")

        ranked = rank_related_decisions(ec_db, file_paths=["src/service/retry.py"], limit=10)

        assert [item["id"] for item in ranked[:2]] == [promoted["id"], demoted["id"]]
        assert ranked[0]["quality_score"] > ranked[1]["quality_score"]
        assert ranked[0]["base_score"] == ranked[1]["base_score"] == 3.0


class TestUpdateDecision:
    def test_update_title(self, ec_db):
        d = create_decision(ec_db, title="Old title")
        updated = update_decision(ec_db, d["id"], title="New title")
        assert updated["title"] == "New title"

    def test_update_rationale(self, ec_db):
        d = create_decision(ec_db, title="Test")
        updated = update_decision(ec_db, d["id"], rationale="New reasoning")
        assert updated["rationale"] == "New reasoning"

    def test_update_prefix_id(self, ec_db):
        d = create_decision(ec_db, title="Original")
        updated = update_decision(ec_db, d["id"][:12], title="Updated")
        assert updated["title"] == "Updated"

    def test_update_nonexistent_raises(self, ec_db):
        with pytest.raises(ValueError, match="not found"):
            update_decision(ec_db, "nonexistent-id", title="Nope")

    def test_no_changes_returns_current(self, ec_db):
        d = create_decision(ec_db, title="Same")
        result = update_decision(ec_db, d["id"])
        assert result["title"] == "Same"


class TestSupersedeDecision:
    def test_supersede(self, ec_db):
        old = create_decision(ec_db, title="Old approach")
        new = create_decision(ec_db, title="New approach")
        result = supersede_decision(ec_db, old["id"], new["id"])
        assert result["staleness_status"] == "superseded"
        assert result["superseded_by_id"] == new["id"]

    def test_supersede_preserves_scope(self, ec_db):
        old = create_decision(ec_db, title="Old", scope="auth module")
        new = create_decision(ec_db, title="New")
        supersede_decision(ec_db, old["id"], new["id"])
        fetched = get_decision(ec_db, old["id"])
        assert fetched["scope"] == "auth module"
        assert fetched["superseded_by_id"] == new["id"]

    def test_prefix_id_support(self, ec_db):
        old = create_decision(ec_db, title="Old")
        new = create_decision(ec_db, title="New")
        result = supersede_decision(ec_db, old["id"][:12], new["id"][:12])
        assert result["staleness_status"] == "superseded"

    def test_self_supersede_raises(self, ec_db):
        d = create_decision(ec_db, title="Self")
        with pytest.raises(ValueError, match="cannot supersede itself"):
            supersede_decision(ec_db, d["id"], d["id"])

    def test_nonexistent_raises(self, ec_db):
        new = create_decision(ec_db, title="New")
        with pytest.raises(ValueError, match="not found"):
            supersede_decision(ec_db, "nonexistent", new["id"])

    def test_supersede_respects_outer_transaction(self, ec_db):
        old = create_decision(ec_db, title="Old approach")
        new = create_decision(ec_db, title="New approach")

        # Simulate an outer caller that owns its own BEGIN IMMEDIATE boundary.
        # Under autocommit, raw conn.execute("BEGIN IMMEDIATE") opens a real
        # transaction but does NOT touch the helper's depth counter, so we
        # bracket it with _ec_tx_depth=1 to make supersede_decision's nested
        # transaction() call defer instead of trying to start another BEGIN.
        # ROLLBACK must also be issued via SQL: conn.rollback() is a no-op
        # under autocommit (Python's sqlite3 only tracks tx it opened itself).
        ec_db.execute("BEGIN IMMEDIATE")
        ec_db._ec_tx_depth = 1
        try:
            result = supersede_decision(ec_db, old["id"], new["id"])
            assert result["superseded_by_id"] == new["id"]
            assert getattr(ec_db, "_ec_tx_depth", 0) >= 1
        finally:
            ec_db._ec_tx_depth = 0
            ec_db.execute("ROLLBACK")

        row = ec_db.execute(
            "SELECT staleness_status, superseded_by_id FROM decisions WHERE id = ?",
            (old["id"],),
        ).fetchone()
        assert row["staleness_status"] == "fresh"
        assert row["superseded_by_id"] is None

    def test_supersede_writes_replaced_outcome_atomically(self, ec_db):
        """supersede_decision must write a 'replaced' outcome row in the same transaction."""
        old = create_decision(ec_db, title="Old approach")
        new = create_decision(ec_db, title="New approach")
        supersede_decision(ec_db, old["id"], new["id"])

        outcomes = list_decision_outcomes(ec_db, old["id"])
        assert len(outcomes) == 1
        assert outcomes[0]["outcome_type"] == "replaced"
        assert f"superseded by {new['id']}" in outcomes[0]["note"]

    def test_supersede_replaced_rollback_on_cycle_error(self, ec_db):
        """Cycle error inside supersede must roll back both the staleness update AND the replaced outcome."""
        a = create_decision(ec_db, title="A")
        b = create_decision(ec_db, title="B")
        supersede_decision(ec_db, a["id"], b["id"])

        with pytest.raises(ValueError, match="cycle"):
            supersede_decision(ec_db, b["id"], a["id"])

        # b must remain fresh with no replaced outcome.
        b_outcomes = list_decision_outcomes(ec_db, b["id"])
        assert not any(o["outcome_type"] == "replaced" for o in b_outcomes)
        b_row = ec_db.execute("SELECT staleness_status FROM decisions WHERE id=?", (b["id"],)).fetchone()
        assert b_row["staleness_status"] == "fresh"

    def test_supersede_rolls_back_started_transaction_on_cycle_error(self, ec_db):
        a = create_decision(ec_db, title="A")
        b = create_decision(ec_db, title="B")
        supersede_decision(ec_db, a["id"], b["id"])

        with pytest.raises(ValueError, match="cycle"):
            supersede_decision(ec_db, b["id"], a["id"])

        # Helper rolled back its owned boundary cleanly; depth back to 0.
        assert getattr(ec_db, "_ec_tx_depth", 0) == 0
        row = ec_db.execute(
            "SELECT staleness_status, superseded_by_id FROM decisions WHERE id = ?",
            (b["id"],),
        ).fetchone()
        assert row["staleness_status"] == "fresh"
        assert row["superseded_by_id"] is None


class TestUnlinkDecision:
    def test_unlink_file(self, ec_db):
        d = create_decision(ec_db, title="Test")
        link_decision_to_file(ec_db, d["id"], "src/a.py")
        assert unlink_decision_from_file(ec_db, d["id"], "src/a.py") is True
        fetched = get_decision(ec_db, d["id"])
        assert "src/a.py" not in fetched["files"]

    def test_unlink_nonexistent_returns_false(self, ec_db):
        d = create_decision(ec_db, title="Test")
        assert unlink_decision_from_file(ec_db, d["id"], "nonexistent.py") is False

    def test_unlink_commit(self, ec_db):
        d = create_decision(ec_db, title="Test")
        link_decision_to_commit(ec_db, d["id"], "abc123")
        assert unlink_decision_from_commit(ec_db, d["id"], "abc123") is True

    def test_unlink_assessment(self, ec_db):
        assessment = create_assessment(ec_db, verdict="expand", impact_summary="test")
        d = create_decision(ec_db, title="Test")
        link_decision_to_assessment(ec_db, d["id"], assessment["id"])
        assert unlink_decision_from_assessment(ec_db, d["id"], assessment["id"]) is True
        fetched = get_decision(ec_db, d["id"])
        assert len(fetched["assessments"]) == 0

    def test_unlink_checkpoint(self, ec_repo, ec_db):
        from entirecontext.core.checkpoint import create_checkpoint

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="unlink-cp-session")
        checkpoint = create_checkpoint(ec_db, session["id"], git_commit_hash="abc123", git_branch="main")
        d = create_decision(ec_db, title="Test")
        link_decision_to_checkpoint(ec_db, d["id"], checkpoint["id"])
        assert unlink_decision_from_checkpoint(ec_db, d["id"], checkpoint["id"]) is True


class TestLinkDecisionAtomicity:
    """S2a regressions: link_decision_to_* helpers wrap their INSERT + UPDATE
    pair in a single BEGIN IMMEDIATE so a failure between them rolls back both
    sides. Pre-S2a, link_decision_to_commit committed independently and a
    failure during the updated_at UPDATE left an orphan decision_commits row
    plus an unbumped decisions row visible to the same connection."""

    def test_link_decision_to_commit_atomic_rollback(self, ec_db, monkeypatch):
        d = create_decision(ec_db, title="Atomicity test")

        before = ec_db.execute("SELECT updated_at FROM decisions WHERE id = ?", (d["id"],)).fetchone()
        before_updated_at = before["updated_at"]

        # Setup's create_decision already called _now_iso. Patch it to fail on
        # the very next call — which is the UPDATE arg in link_decision_to_commit.
        # The INSERT runs first; then _now_iso() raises; the wrapped tx rolls
        # back both sides.
        def _failing_now_iso() -> str:
            raise RuntimeError("simulated update failure")

        monkeypatch.setattr("entirecontext.core.decisions._now_iso", _failing_now_iso)

        with pytest.raises(RuntimeError, match="simulated update failure"):
            link_decision_to_commit(ec_db, d["id"], "deadbeef")

        # Wrapped transaction rolled back; same connection sees no orphan row.
        commit_count = ec_db.execute(
            "SELECT COUNT(*) AS c FROM decision_commits WHERE decision_id = ?", (d["id"],)
        ).fetchone()["c"]
        assert commit_count == 0

        # UPDATE never landed; decisions.updated_at unchanged from setup.
        after = ec_db.execute("SELECT updated_at FROM decisions WHERE id = ?", (d["id"],)).fetchone()
        assert after["updated_at"] == before_updated_at

        # Rollback completed cleanly — depth back to 0, helper released its boundary.
        assert getattr(ec_db, "_ec_tx_depth", 0) == 0


class TestCheckStaleness:
    def test_no_files_not_stale(self, ec_db, ec_repo):
        d = create_decision(ec_db, title="No files")
        result = check_staleness(ec_db, d["id"], str(ec_repo))
        assert result["stale"] is False
        assert result["changed_files"] == []

    def test_nonexistent_raises(self, ec_db, ec_repo):
        with pytest.raises(ValueError, match="not found"):
            check_staleness(ec_db, "nonexistent", str(ec_repo))

    def test_stale_when_linked_file_changed(self, ec_db, ec_repo):
        import subprocess

        test_file = ec_repo / "staleness_test.py"
        test_file.write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=str(ec_repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "add file"], cwd=str(ec_repo), capture_output=True)

        d = create_decision(ec_db, title="Stale test")
        link_decision_to_file(ec_db, d["id"], "staleness_test.py")

        test_file.write_text("x = 2\n")
        subprocess.run(["git", "add", "."], cwd=str(ec_repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "modify file"], cwd=str(ec_repo), capture_output=True)

        result = check_staleness(ec_db, d["id"], str(ec_repo))
        assert result["stale"] is True
        assert "staleness_test.py" in result["changed_files"]


class TestFTSDecisions:
    def test_fts_search_by_title(self, ec_db):
        create_decision(ec_db, title="Adopt microservices architecture")
        create_decision(ec_db, title="Use monolith pattern")
        rows = ec_db.execute("SELECT * FROM fts_decisions WHERE fts_decisions MATCH ?", ("microservices",)).fetchall()
        assert len(rows) == 1

    def test_fts_search_by_rationale(self, ec_db):
        create_decision(ec_db, title="DB choice", rationale="PostgreSQL offers better JSON support")
        rows = ec_db.execute("SELECT * FROM fts_decisions WHERE fts_decisions MATCH ?", ("PostgreSQL",)).fetchall()
        assert len(rows) == 1

    def test_fts_updated_after_update_decision(self, ec_db):
        d = create_decision(ec_db, title="Old searchable title")
        update_decision(ec_db, d["id"], title="New searchable title")
        old_rows = ec_db.execute("SELECT * FROM fts_decisions WHERE fts_decisions MATCH ?", ("Old",)).fetchall()
        new_rows = ec_db.execute("SELECT * FROM fts_decisions WHERE fts_decisions MATCH ?", ("New",)).fetchall()
        assert len(old_rows) == 0
        assert len(new_rows) == 1


class TestDecisionsCoreExtended:
    def test_update_decision_scope_and_evidence(self, ec_db):
        d = create_decision(ec_db, title="Original", scope="old-scope")
        updated = update_decision(
            ec_db,
            d["id"],
            scope="new-scope",
            rejected_alternatives=["option-a", "option-b"],
            supporting_evidence=[{"kind": "benchmark", "url": "https://example.com"}],
        )
        assert updated["scope"] == "new-scope"
        assert updated["rejected_alternatives"] == ["option-a", "option-b"]
        assert updated["supporting_evidence"] == [{"kind": "benchmark", "url": "https://example.com"}]

    def test_supersede_new_decision_not_found(self, ec_db):
        old = create_decision(ec_db, title="Existing")
        with pytest.raises(ValueError, match="not found"):
            supersede_decision(ec_db, old["id"], "nonexistent-new-id")

    def test_unlink_from_file_decision_not_found(self, ec_db):
        assert unlink_decision_from_file(ec_db, "nonexistent-decision-id", "src/a.py") is False

    def test_unlink_from_commit_decision_not_found(self, ec_db):
        assert unlink_decision_from_commit(ec_db, "nonexistent-decision-id", "abc123") is False

    def test_unlink_from_assessment_decision_not_found(self, ec_db):
        assert unlink_decision_from_assessment(ec_db, "nonexistent-decision-id", "nonexistent-assessment-id") is False

    def test_unlink_from_checkpoint_decision_not_found(self, ec_db):
        assert unlink_decision_from_checkpoint(ec_db, "nonexistent-decision-id", "nonexistent-checkpoint-id") is False

    def test_rank_decisions_diff_fts_title_scoring(self, ec_db):
        matching = create_decision(ec_db, title="Adopt queue retries")
        other = create_decision(ec_db, title="Use monolith pattern")
        link_decision_to_file(ec_db, matching["id"], "src/retry.py")
        link_decision_to_file(ec_db, other["id"], "src/retry.py")

        ranked = rank_related_decisions(
            ec_db,
            file_paths=["src/retry.py"],
            diff_text="+adopt queue retries in the service layer\n+retry handler setup",
        )

        ids = [item["id"] for item in ranked]
        assert matching["id"] in ids
        assert other["id"] in ids
        matching_item = next(item for item in ranked if item["id"] == matching["id"])
        other_item = next(item for item in ranked if item["id"] == other["id"])
        assert matching_item["score"] > other_item["score"]

    def test_rank_decisions_diff_fts_rationale_scoring(self, ec_db):
        matching = create_decision(
            ec_db,
            title="Unique unrelated title xyz",
            rationale="prevents retry storms in production environment",
        )
        other = create_decision(ec_db, title="Another unrelated title abc", rationale="improves code readability")
        link_decision_to_file(ec_db, matching["id"], "src/service.py")
        link_decision_to_file(ec_db, other["id"], "src/service.py")

        ranked = rank_related_decisions(
            ec_db,
            file_paths=["src/service.py"],
            diff_text="+prevents retry storms in production environment\n+adds resilience layer",
        )

        matching_item = next(item for item in ranked if item["id"] == matching["id"])
        other_item = next(item for item in ranked if item["id"] == other["id"])
        assert matching_item["score"] > other_item["score"]


class TestDecisionFTSSearch:
    def test_fts_search_by_title(self, ec_db):
        create_decision(ec_db, title="Use queue based webhook retries", rationale="Prevent retry storms")
        create_decision(ec_db, title="Cache invalidation strategy", rationale="TTL-based approach")

        results = fts_search_decisions(ec_db, "webhook")
        assert len(results) == 1
        assert results[0]["title"] == "Use queue based webhook retries"

    def test_fts_search_by_rationale(self, ec_db):
        create_decision(ec_db, title="Caching approach", rationale="Use TTL-based cache invalidation")

        results = fts_search_decisions(ec_db, "invalidation")
        assert len(results) == 1
        assert results[0]["title"] == "Caching approach"

    def test_fts_search_no_match(self, ec_db):
        create_decision(ec_db, title="Some decision", rationale="Some rationale")

        results = fts_search_decisions(ec_db, "nonexistent")
        assert results == []

    def test_fts_search_since_filter(self, ec_db):
        create_decision(ec_db, title="Old decision", rationale="Old rationale")
        results = fts_search_decisions(ec_db, "decision", since="2099-01-01")
        assert results == []

    def test_fts_search_limit(self, ec_db):
        for i in range(5):
            create_decision(ec_db, title=f"Architecture decision {i}", rationale=f"Rationale {i}")

        results = fts_search_decisions(ec_db, "Architecture", limit=3)
        assert len(results) == 3

    def test_fts_search_bad_query_raises_error(self, ec_db):
        create_decision(ec_db, title="Some decision", rationale="Some rationale")
        with pytest.raises(ValueError, match="Invalid FTS query"):
            fts_search_decisions(ec_db, "AND OR NOT")

    def test_hybrid_search_returns_scores(self, ec_db):
        create_decision(ec_db, title="Migration safety", rationale="Always use reversible migrations")
        create_decision(ec_db, title="Migration strategy", rationale="Blue-green deployment for migrations")

        results = hybrid_search_decisions(ec_db, "migration")
        assert len(results) == 2
        assert all("hybrid_score" in r for r in results)
        assert results[0]["hybrid_score"] >= results[1]["hybrid_score"]


class TestRankingSignals:
    """Tests for multi-signal decision ranking (issue #40)."""

    # --- Signal isolation ---

    def test_file_exact_match(self, ec_db):
        d = create_decision(ec_db, title="Exact file decision")
        link_decision_to_file(ec_db, d["id"], "src/auth.py")

        ranked = rank_related_decisions(ec_db, file_paths=["src/auth.py"])
        assert len(ranked) >= 1
        item = next(r for r in ranked if r["id"] == d["id"])
        assert item["score_breakdown"]["file_exact"] == 3.0
        assert item["score_breakdown"]["file_proximity"] == 0.0

    def test_file_proximity_same_directory(self, ec_db):
        d = create_decision(ec_db, title="Nearby file decision")
        link_decision_to_file(ec_db, d["id"], "src/service/handler.py")

        ranked = rank_related_decisions(ec_db, file_paths=["src/service/router.py"])
        assert len(ranked) >= 1
        item = next(r for r in ranked if r["id"] == d["id"])
        assert item["score_breakdown"]["file_exact"] == 0.0
        assert item["score_breakdown"]["file_proximity"] == 1.5

    def test_file_proximity_parent_directory(self, ec_db):
        d = create_decision(ec_db, title="Parent dir decision")
        link_decision_to_file(ec_db, d["id"], "src/service/sub/deep.py")

        ranked = rank_related_decisions(ec_db, file_paths=["src/service/other.py"])
        assert len(ranked) >= 1
        item = next(r for r in ranked if r["id"] == d["id"])
        assert item["score_breakdown"]["file_proximity"] == 0.75

    def test_file_proximity_different_tree(self, ec_db):
        d = create_decision(ec_db, title="Unrelated dir")
        link_decision_to_file(ec_db, d["id"], "tests/unit/test_auth.py")

        ranked = rank_related_decisions(ec_db, file_paths=["src/service/auth.py"])
        found = [r for r in ranked if r["id"] == d["id"]]
        if found:
            assert found[0]["score_breakdown"]["file_proximity"] == 0.0
            assert found[0]["score_breakdown"]["file_exact"] == 0.0

    def test_file_exact_match_dotslash_stored_path(self, ec_db):
        """Exact match must work when the stored path has a ./ prefix."""
        d = create_decision(ec_db, title="Dotslash stored path")
        # Simulate a path stored with ./ prefix (as some tooling produces)
        link_decision_to_file(ec_db, d["id"], "./src/auth.py")

        ranked = rank_related_decisions(ec_db, file_paths=["src/auth.py"])
        assert len(ranked) >= 1
        item = next((r for r in ranked if r["id"] == d["id"]), None)
        assert item is not None, "Decision with ./src/auth.py should match query for src/auth.py"
        assert item["score_breakdown"]["file_exact"] == 3.0

    def test_file_proximity_sibling_directory(self, ec_db):
        """Decision in a sibling directory must be a candidate for proximity scoring."""
        d = create_decision(ec_db, title="Sibling dir decision")
        # Decision linked to src/service/y.py (sibling of src/service/sub/)
        link_decision_to_file(ec_db, d["id"], "src/service/y.py")

        # Changed file is src/service/sub/x.py — sibling should have proximity 0.75
        ranked = rank_related_decisions(ec_db, file_paths=["src/service/sub/x.py"])
        assert len(ranked) >= 1
        item = next((r for r in ranked if r["id"] == d["id"]), None)
        assert item is not None, "Decision in sibling dir should be a candidate"
        assert item["score_breakdown"]["file_proximity"] == 0.75

    def test_assessment_match(self, ec_db):
        assessment = create_assessment(ec_db, verdict="expand", impact_summary="assessment signal test")
        d = create_decision(ec_db, title="Assessment linked")
        link_decision_to_assessment(ec_db, d["id"], assessment["id"])

        ranked = rank_related_decisions(ec_db, assessment_ids=[assessment["id"]])
        assert len(ranked) >= 1
        item = next(r for r in ranked if r["id"] == d["id"])
        assert item["score_breakdown"]["assessment"] == 4.0

    def test_assessment_contradicts_weight(self, ec_db):
        assessment = create_assessment(ec_db, verdict="narrow", impact_summary="contradicts test")
        d = create_decision(ec_db, title="Contradicted decision")
        link_decision_to_assessment(ec_db, d["id"], assessment["id"], relation_type="contradicts")

        ranked = rank_related_decisions(ec_db, assessment_ids=[assessment["id"]])
        item = next(r for r in ranked if r["id"] == d["id"])
        assert item["score_breakdown"]["assessment"] == 5.0

    def test_assessment_dedupe_max_weight(self, ec_db):
        assessment = create_assessment(ec_db, verdict="expand", impact_summary="dedupe test")
        d = create_decision(ec_db, title="Multi-relation")
        link_decision_to_assessment(ec_db, d["id"], assessment["id"], relation_type="supports")
        link_decision_to_assessment(ec_db, d["id"], assessment["id"], relation_type="contradicts")

        ranked = rank_related_decisions(ec_db, assessment_ids=[assessment["id"]])
        item = next(r for r in ranked if r["id"] == d["id"])
        # Should use max weight (contradicts=5.0), not sum (4.0+5.0)
        assert item["score_breakdown"]["assessment"] == 5.0

    def test_diff_fts_match(self, ec_db):
        d = create_decision(ec_db, title="Queue retry backoff strategy")

        ranked = rank_related_decisions(
            ec_db,
            diff_text="+implement queue retry backoff\n+exponential delay strategy",
        )
        found = [r for r in ranked if r["id"] == d["id"]]
        assert len(found) >= 1
        assert found[0]["score_breakdown"]["diff_relevance"] > 0

    def test_diff_fts_no_match(self, ec_db):
        create_decision(ec_db, title="Cache invalidation policy")

        ranked = rank_related_decisions(
            ec_db,
            diff_text="+authentication middleware refactor\n+jwt token validation",
        )
        found = [r for r in ranked if r["title"] == "Cache invalidation policy"]
        if found:
            assert found[0]["score_breakdown"]["diff_relevance"] == 0.0

    def test_commit_match(self, ec_db):
        d = create_decision(ec_db, title="Commit-linked decision")
        link_decision_to_commit(ec_db, d["id"], "abc123def")

        ranked = rank_related_decisions(ec_db, commit_shas=["abc123def"])
        assert len(ranked) >= 1
        item = next(r for r in ranked if r["id"] == d["id"])
        assert item["score_breakdown"]["git_commit"] == 3.0

    # --- Staleness penalty ---

    def test_stale_penalty(self, ec_db):
        fresh = create_decision(ec_db, title="Fresh decision")
        stale = create_decision(ec_db, title="Stale decision")
        update_decision_staleness(ec_db, stale["id"], "stale")
        link_decision_to_file(ec_db, fresh["id"], "src/api.py")
        link_decision_to_file(ec_db, stale["id"], "src/api.py")

        ranked = rank_related_decisions(ec_db, file_paths=["src/api.py"])
        ids = [r["id"] for r in ranked]
        assert ids.index(fresh["id"]) < ids.index(stale["id"])
        fresh_item = next(r for r in ranked if r["id"] == fresh["id"])
        stale_item = next(r for r in ranked if r["id"] == stale["id"])
        assert fresh_item["score_breakdown"]["staleness_factor"] == 1.0
        assert stale_item["score_breakdown"]["staleness_factor"] == 0.85

    def test_superseded_penalty(self, ec_db):
        fresh = create_decision(ec_db, title="Fresh")
        superseded = create_decision(ec_db, title="Superseded")
        update_decision_staleness(ec_db, superseded["id"], "superseded")
        link_decision_to_file(ec_db, fresh["id"], "src/core.py")
        link_decision_to_file(ec_db, superseded["id"], "src/core.py")

        # Must opt in; default policy excludes superseded decisions.
        ranked = rank_related_decisions(ec_db, file_paths=["src/core.py"], include_superseded=True)
        fresh_item = next(r for r in ranked if r["id"] == fresh["id"])
        sup_item = next(r for r in ranked if r["id"] == superseded["id"])
        assert fresh_item["score"] > sup_item["score"]
        assert sup_item["score_breakdown"]["staleness_factor"] == 0.5

    # --- Scenario tests ---

    def test_repeated_task_scenario(self, ec_db):
        """Simulates revisiting the same files — decision should surface."""
        d = create_decision(ec_db, title="Retry strategy for webhook service")
        link_decision_to_file(ec_db, d["id"], "src/webhook/handler.py")
        link_decision_to_file(ec_db, d["id"], "src/webhook/retry.py")

        ranked = rank_related_decisions(
            ec_db,
            file_paths=["src/webhook/handler.py", "src/webhook/retry.py"],
        )
        assert len(ranked) >= 1
        item = next(r for r in ranked if r["id"] == d["id"])
        assert item["score_breakdown"]["file_exact"] == 6.0  # 3.0 * 2 files

    def test_regression_fix_scenario(self, ec_db):
        """Simulates fixing regression in area covered by a prior decision."""
        d = create_decision(ec_db, title="Connection pool sizing")
        link_decision_to_file(ec_db, d["id"], "src/db/pool.py")
        link_decision_to_commit(ec_db, d["id"], "fix123abc")

        ranked = rank_related_decisions(
            ec_db,
            file_paths=["src/db/pool.py"],
            commit_shas=["fix123abc"],
        )
        item = next(r for r in ranked if r["id"] == d["id"])
        assert item["score_breakdown"]["file_exact"] == 3.0
        assert item["score_breakdown"]["git_commit"] == 3.0
        assert item["base_score"] >= 6.0

    def test_candidate_beyond_200_recency(self, ec_db):
        """Old decision linked to a specific file must surface (no 200-row ceiling)."""
        old = create_decision(ec_db, title="Ancient decision")
        link_decision_to_file(ec_db, old["id"], "src/legacy/ancient.py")

        # Create 201 newer decisions to push `old` beyond old 200-row limit
        for i in range(201):
            create_decision(ec_db, title=f"Padding decision {i}")

        ranked = rank_related_decisions(ec_db, file_paths=["src/legacy/ancient.py"])
        ids = [r["id"] for r in ranked]
        assert old["id"] in ids

    def test_no_signals_returns_empty(self, ec_db):
        create_decision(ec_db, title="Some decision")
        ranked = rank_related_decisions(ec_db)
        # With no signals, only fallback candidates exist but all score 0 → filtered
        assert ranked == []

    # --- Observability ---

    def test_score_breakdown_keys_present(self, ec_db):
        d = create_decision(ec_db, title="Breakdown test")
        link_decision_to_file(ec_db, d["id"], "src/test.py")

        ranked = rank_related_decisions(ec_db, file_paths=["src/test.py"])
        item = next(r for r in ranked if r["id"] == d["id"])
        expected_keys = {
            "file_exact",
            "file_proximity",
            "assessment",
            "diff_relevance",
            "git_commit",
            "quality",
            "staleness_factor",
        }
        assert set(item["score_breakdown"].keys()) == expected_keys

    def test_score_breakdown_sums_correctly(self, ec_db):
        d = create_decision(ec_db, title="Sum test")
        link_decision_to_file(ec_db, d["id"], "src/sum.py")
        record_decision_outcome(ec_db, d["id"], "accepted")

        ranked = rank_related_decisions(ec_db, file_paths=["src/sum.py"])
        item = next(r for r in ranked if r["id"] == d["id"])
        bd = item["score_breakdown"]
        expected_base = (
            bd["file_exact"] + bd["file_proximity"] + bd["assessment"] + bd["diff_relevance"] + bd["git_commit"]
        )
        assert abs(item["base_score"] - round(expected_base, 3)) < 0.01
        expected_score = expected_base * bd["staleness_factor"] + bd["quality"]
        assert abs(item["score"] - round(expected_score, 3)) < 0.01

    # --- Backward compatibility ---

    def test_return_format_backward_compat(self, ec_db):
        d = create_decision(ec_db, title="Compat test")
        link_decision_to_file(ec_db, d["id"], "src/compat.py")

        ranked = rank_related_decisions(ec_db, file_paths=["src/compat.py"])
        item = ranked[0]
        for key in ("id", "title", "staleness_status", "updated_at", "base_score", "quality_score", "score"):
            assert key in item


# ---------------------------------------------------------------------------
# Issue #85 (v0.4.0 F3): ranking weight configuration
# ---------------------------------------------------------------------------


class TestRankingWeightsConfig:
    """[decisions.ranking] config → RankingWeights injection into rank_related_decisions."""

    _EXPECTED_BREAKDOWN_KEYS = frozenset(
        {
            "file_exact",
            "file_proximity",
            "assessment",
            "diff_relevance",
            "git_commit",
            "quality",
            "staleness_factor",
        }
    )

    def test_score_breakdown_keys_stable(self, ec_db):
        """score_breakdown keys are a stable additive-only contract (#85)."""
        d = create_decision(ec_db, title="Key stability decision")
        link_decision_to_file(ec_db, d["id"], "src/contract.py")

        ranked = rank_related_decisions(ec_db, file_paths=["src/contract.py"])
        item = next(r for r in ranked if r["id"] == d["id"])
        assert set(item["score_breakdown"].keys()) == set(self._EXPECTED_BREAKDOWN_KEYS), (
            "score_breakdown keys changed — MCP ec_decision_related callers rely on these exact names; "
            "rename is forbidden, add-only is allowed."
        )

    def test_rank_default_matches_legacy(self, ec_db):
        """ranking=None preserves legacy hardcoded constants (pre-F3 numbers)."""
        d_a = create_decision(ec_db, title="Fresh file decision")
        link_decision_to_file(ec_db, d_a["id"], "src/legacy.py")
        d_b = create_decision(ec_db, title="Commit decision")
        link_decision_to_commit(ec_db, d_b["id"], "abc1234")

        ranked_files = rank_related_decisions(ec_db, file_paths=["src/legacy.py"])
        item_a = next(r for r in ranked_files if r["id"] == d_a["id"])
        assert item_a["score_breakdown"]["file_exact"] == 3.0
        assert item_a["score_breakdown"]["staleness_factor"] == 1.0

        ranked_commits = rank_related_decisions(ec_db, commit_shas=["abc1234"])
        item_b = next(r for r in ranked_commits if r["id"] == d_b["id"])
        assert item_b["score_breakdown"]["git_commit"] == 3.0

        assert _DEFAULT_RANKING_WEIGHTS.staleness_factors == {
            "fresh": 1.0,
            "stale": 0.85,
            "superseded": 0.5,
            "contradicted": 0.25,
        }
        assert _DEFAULT_RANKING_WEIGHTS.assessment_relation_weights == {
            "supports": 4.0,
            "informed_by": 4.0,
            "contradicts": 5.0,
            "supersedes": 3.0,
        }
        assert _DEFAULT_RANKING_WEIGHTS.file_exact_weight == 3.0
        assert _DEFAULT_RANKING_WEIGHTS.git_commit_weight == 3.0
        assert _DEFAULT_RANKING_WEIGHTS.directory_proximity_cap_levels == 3

    def test_rank_uses_config_staleness_factors(self, ec_db):
        """A staleness_factors override in [decisions.ranking] reshapes the staleness demotion."""
        d = create_decision(ec_db, title="Stale-boost decision", staleness_status="stale")
        link_decision_to_file(ec_db, d["id"], "src/override.py")

        default_ranked = rank_related_decisions(ec_db, file_paths=["src/override.py"])
        default_item = next(r for r in default_ranked if r["id"] == d["id"])
        assert default_item["score_breakdown"]["staleness_factor"] == 0.85  # legacy "stale" default

        boosted = RankingWeights(
            staleness_factors={**_DEFAULT_RANKING_WEIGHTS.staleness_factors, "stale": 2.0},
        )
        override_ranked = rank_related_decisions(ec_db, file_paths=["src/override.py"], ranking=boosted)
        override_item = next(r for r in override_ranked if r["id"] == d["id"])
        assert override_item["score_breakdown"]["staleness_factor"] == 2.0
        assert override_item["score"] > default_item["score"]

    def test_load_ranking_weights_deep_merges_partial_override(self):
        """Partial [decisions.ranking] override keeps un-specified factors at legacy defaults."""
        weights = _load_ranking_weights(
            {
                "decisions": {
                    "ranking": {
                        "staleness_factors": {"fresh": 3.0},
                        "file_exact_weight": 5.0,
                    }
                }
            }
        )
        assert weights.staleness_factors["fresh"] == 3.0
        assert weights.staleness_factors["stale"] == 0.85  # legacy default preserved
        assert weights.file_exact_weight == 5.0
        assert weights.git_commit_weight == 3.0  # legacy default preserved
        assert weights.assessment_relation_weights == _DEFAULT_RANKING_WEIGHTS.assessment_relation_weights

    def test_load_ranking_weights_empty_config_returns_defaults_by_value(self):
        """Empty/missing config yields a fresh instance with default values (never the singleton)."""
        for empty in (None, {}, {"decisions": {}}, {"decisions": {"ranking": {}}}):
            weights = _load_ranking_weights(empty)
            assert weights.staleness_factors == _DEFAULT_RANKING_WEIGHTS.staleness_factors
            assert weights.assessment_relation_weights == _DEFAULT_RANKING_WEIGHTS.assessment_relation_weights
            assert weights.file_exact_weight == _DEFAULT_RANKING_WEIGHTS.file_exact_weight
            assert weights.git_commit_weight == _DEFAULT_RANKING_WEIGHTS.git_commit_weight
            assert weights.directory_proximity_cap_levels == _DEFAULT_RANKING_WEIGHTS.directory_proximity_cap_levels
            # Isolation: returned instance must never be the module-level singleton,
            # otherwise a caller mutating staleness_factors would contaminate defaults.
            assert weights is not _DEFAULT_RANKING_WEIGHTS
            assert weights.staleness_factors is not _DEFAULT_RANKING_WEIGHTS.staleness_factors

    def test_load_ranking_weights_mutation_does_not_contaminate_singleton(self):
        """Mutating an in-field dict on a returned instance must not leak into defaults."""
        poisoned = _load_ranking_weights(None)
        poisoned.staleness_factors["fresh"] = 999.0

        fresh = _load_ranking_weights(None)
        assert fresh.staleness_factors["fresh"] == 1.0
        assert _DEFAULT_RANKING_WEIGHTS.staleness_factors["fresh"] == 1.0

    def test_load_ranking_weights_rejects_non_numeric_with_field_name(self):
        """Coercion errors must name the offending config key."""
        with pytest.raises(ValueError, match=r"decisions\.ranking\.file_exact_weight"):
            _load_ranking_weights({"decisions": {"ranking": {"file_exact_weight": "not-a-number"}}})
        with pytest.raises(ValueError, match=r"decisions\.ranking\.directory_proximity_cap_levels"):
            _load_ranking_weights({"decisions": {"ranking": {"directory_proximity_cap_levels": "deep"}}})

    def test_load_ranking_weights_rejects_non_numeric_map_values(self):
        """Weight-map values are coerced to float at load time with a path-qualified error.

        PR #87 review comment #discussion_r3098094096: a quoted/wrong-type override like
        ``staleness_factors.stale = "not-numeric"`` used to slip through the
        ``{**default, **override}`` merge and only explode later inside scoring
        arithmetic. Values must now be validated eagerly at config load.
        """
        with pytest.raises(ValueError, match=r"decisions\.ranking\.staleness_factors\.stale"):
            _load_ranking_weights({"decisions": {"ranking": {"staleness_factors": {"stale": "not-numeric"}}}})
        with pytest.raises(
            ValueError,
            match=r"decisions\.ranking\.assessment_relation_weights\.supports",
        ):
            _load_ranking_weights(
                {"decisions": {"ranking": {"assessment_relation_weights": {"supports": ["list-not-scalar"]}}}}
            )
        # A valid numeric-string override still coerces cleanly; strict float()
        # is the contract, not strict type-identity.
        coerced = _load_ranking_weights({"decisions": {"ranking": {"staleness_factors": {"stale": "0.9"}}}})
        assert coerced.staleness_factors["stale"] == 0.9

    def test_rank_cap_levels_override_widens_candidate_gathering(self, ec_db):
        """Config cap_levels > 3 must widen _gather_candidates_by_files, not just the scorer.

        Setup: linked file is shallow ("src/a/file.py"); queried file is deep
        ("src/a/b/c/d/e/deep.py"). They share only "src/a" — a 4-hop ancestor of
        the queried file. Default cap=3 keeps the queried file's ancestor search
        shallow enough that it never generates "src/a" as an ancestor dir, so the
        linked file is not a candidate at all (and its proximity score would be
        zero anyway under depth_from_match=4 > cap=3). Raising cap to 4 widens
        both sides.
        """
        d_far = create_decision(ec_db, title="Four hops away")
        link_decision_to_file(ec_db, d_far["id"], "src/a/file.py")
        deep_path = ["src/a/b/c/d/e/deep.py"]

        default_ranked = rank_related_decisions(ec_db, file_paths=deep_path)
        assert not any(r["id"] == d_far["id"] for r in default_ranked)

        wide = _load_ranking_weights({"decisions": {"ranking": {"directory_proximity_cap_levels": 4}}})
        assert wide.directory_proximity_cap_levels == 4
        wide_ranked = rank_related_decisions(ec_db, file_paths=deep_path, ranking=wide)
        assert any(r["id"] == d_far["id"] for r in wide_ranked), (
            "directory_proximity_cap_levels=4 must widen candidate gathering, not just scoring."
        )


# ---------------------------------------------------------------------------
# Outcome recency decay
# ---------------------------------------------------------------------------


class TestDecisionQualityDecay:
    """calculate_decision_quality_score + _fetch_decayed_outcome_counts + QualityWeights."""

    def test_quality_score_legacy_signature_unchanged(self):
        """The 1-arg call must produce byte-identical output to the pre-F1 formula."""
        from entirecontext.core.decisions import calculate_decision_quality_score

        cases = [
            ({}, 0.0),
            ({"accepted": 2}, 2.0),
            ({"ignored": 4}, -2.0),
            ({"contradicted": 1}, -2.0),
            ({"accepted": 1, "ignored": 2, "contradicted": 1}, 1.0 - 1.0 - 2.0),
            # Clamps
            ({"accepted": 10}, 4.0),
            ({"contradicted": 10}, -4.0),
        ]
        for counts, expected in cases:
            assert calculate_decision_quality_score(counts) == expected, counts

    def test_quality_score_with_decay_applies_decayed_weights(self):
        """When decayed_counts is supplied, it drives the score (not counts)."""
        from entirecontext.core.decisions import calculate_decision_quality_score

        # 3 accepted across history, but decayed sum is 1.5 (recent-weighted).
        # Legacy answer would be 3.0; decayed answer must be 1.5.
        counts = {"accepted": 3}
        decayed = {"accepted": 1.5}
        score = calculate_decision_quality_score(counts, decayed_counts=decayed, min_volume=2)
        assert score == 1.5
        # With contradicted mixed in, sign still reflects decayed weight.
        counts = {"accepted": 2, "contradicted": 3}
        decayed = {"accepted": 0.4, "contradicted": 1.8}
        score = calculate_decision_quality_score(counts, decayed_counts=decayed, min_volume=2)
        expected = 0.4 - 2.0 * 1.8
        assert score == max(-4.0, min(4.0, expected))

    def test_quality_score_half_life_zero_disables_decay(self):
        """half_life<=0 → _fetch_decayed_outcome_counts returns empty → ranker uses legacy path.

        advisor-reviewed semantic: "decay disabled" is the implementable
        meaning. "latest only" as a math limit isn't what we ship.
        """
        from entirecontext.core.decisions import _fetch_decayed_outcome_counts

        class _StubConn:
            def execute(self, *_a, **_kw):  # pragma: no cover — must not be called
                raise AssertionError("decay must not query when half_life<=0")

        assert _fetch_decayed_outcome_counts(_StubConn(), ["d1"], 0) == {}
        assert _fetch_decayed_outcome_counts(_StubConn(), ["d1"], -7.5) == {}

    def test_quality_score_min_volume_smooths_single_outcome(self):
        """A single fresh outcome gets attenuated toward zero by min_volume."""
        from entirecontext.core.decisions import calculate_decision_quality_score

        counts = {"accepted": 1}
        decayed = {"accepted": 1.0}
        # total=1 < min_volume=2 → score scaled by 1/2
        score = calculate_decision_quality_score(counts, decayed_counts=decayed, min_volume=2)
        assert score == 0.5
        # At volume = min_volume, smoothing does not fire.
        score_full = calculate_decision_quality_score({"accepted": 2}, decayed_counts={"accepted": 2.0}, min_volume=2)
        assert score_full == 2.0

    def test_fetch_decayed_outcome_counts_empty_ids_returns_empty(self, ec_db):
        from entirecontext.core.decisions import _fetch_decayed_outcome_counts

        assert _fetch_decayed_outcome_counts(ec_db, [], 30) == {}

    def test_fetch_decayed_outcome_counts_handles_aware_and_naive_timestamps(self, ec_db):
        """Production INSERTs write aware ISO (_now_iso); legacy DEFAULT rows are
        naive — both must parse to aware UTC and produce finite decay weights."""
        import uuid
        from datetime import datetime, timedelta, timezone

        from entirecontext.core.decisions import _fetch_decayed_outcome_counts, create_decision

        d = create_decision(ec_db, title="Decay parse target")
        now = datetime.now(timezone.utc)
        aware_row = (now - timedelta(days=0)).isoformat()  # weight = 1.0
        naive_row = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")  # naive → treated UTC

        for row_time in (aware_row, naive_row):
            ec_db.execute(
                "INSERT INTO decision_outcomes (id, decision_id, outcome_type, created_at) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), d["id"], "accepted", row_time),
            )
        ec_db.commit()

        decayed = _fetch_decayed_outcome_counts(ec_db, [d["id"]], half_life_days=30.0, now=now)
        # aware (age=0) → 1.0; naive (age≈30d) → 0.5; sum → 1.5
        assert d["id"] in decayed
        total = decayed[d["id"]].get("accepted", 0.0)
        assert 1.49 <= total <= 1.51, total

    def test_rank_related_decisions_surfaces_recent_contradicted_over_old_accepted(self, ec_db):
        """End-to-end decay in ranker: a recent contradicted dominates older accepted runs."""
        import uuid
        from datetime import datetime, timedelta, timezone

        from entirecontext.core.decisions import (
            QualityWeights,
            create_decision,
            link_decision_to_file,
            rank_related_decisions,
        )

        d = create_decision(ec_db, title="Decay-weighted decision")
        link_decision_to_file(ec_db, d["id"], "src/decay.py")

        now = datetime.now(timezone.utc)
        outcomes = [
            ("accepted", now - timedelta(days=200)),
            ("accepted", now - timedelta(days=180)),
            ("accepted", now - timedelta(days=150)),
            ("contradicted", now - timedelta(days=2)),
            ("contradicted", now - timedelta(days=1)),
        ]
        for outcome_type, created in outcomes:
            ec_db.execute(
                "INSERT INTO decision_outcomes (id, decision_id, outcome_type, created_at) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), d["id"], outcome_type, created.isoformat()),
            )
        ec_db.commit()

        # Legacy (decay off) — uniform counts say 3 accepted vs 2 contradicted.
        # calculate_decision_quality_score legacy: 3 - 2*2 = -1 (still net negative
        # because contradicted weight is 2× accepted). So decay must push *more*
        # negative for the test to measurably separate from legacy.
        off = rank_related_decisions(
            ec_db, file_paths=["src/decay.py"], quality=QualityWeights(recency_half_life_days=0)
        )
        on = rank_related_decisions(
            ec_db, file_paths=["src/decay.py"], quality=QualityWeights(recency_half_life_days=30)
        )
        off_item = next(r for r in off if r["id"] == d["id"])
        on_item = next(r for r in on if r["id"] == d["id"])
        # With decay, the 3 accepted from >150d ago decay to ~0, leaving recent
        # contradicted dominant → quality score more negative than legacy path.
        assert on_item["quality_score"] < off_item["quality_score"], (
            f"decay should push quality more negative: off={off_item['quality_score']}, on={on_item['quality_score']}"
        )

    def test_load_quality_weights_rejects_non_numeric(self):
        from entirecontext.core.decisions import _load_quality_weights

        with pytest.raises(ValueError, match=r"decisions\.quality\.recency_half_life_days"):
            _load_quality_weights({"decisions": {"quality": {"recency_half_life_days": "not-a-number"}}})
        with pytest.raises(ValueError, match=r"decisions\.quality\.min_volume"):
            _load_quality_weights({"decisions": {"quality": {"min_volume": "two"}}})

    def test_load_quality_weights_returns_fresh_defaults(self):
        """Empty/missing config always yields a fresh instance (no singleton exposure)."""
        from entirecontext.core.decisions import _DEFAULT_QUALITY_WEIGHTS, _load_quality_weights

        for empty in (None, {}, {"decisions": {}}, {"decisions": {"quality": {}}}):
            loaded = _load_quality_weights(empty)
            assert loaded.recency_half_life_days == _DEFAULT_QUALITY_WEIGHTS.recency_half_life_days
            assert loaded.min_volume == _DEFAULT_QUALITY_WEIGHTS.min_volume

    # --- previously-uncovered branches ---

    def test_quality_score_explicit_none_decayed_counts_uses_legacy(self):
        """Passing decayed_counts=None explicitly must hit the legacy branch."""
        from entirecontext.core.decisions import calculate_decision_quality_score

        assert (
            calculate_decision_quality_score({"accepted": 3}, decayed_counts=None)
            == calculate_decision_quality_score({"accepted": 3})
            == 3.0
        )

    def test_quality_score_min_volume_zero_or_one_disables_smoothing(self):
        """min_volume<=1 short-circuits the smoother so single-outcome decay is not attenuated."""
        from entirecontext.core.decisions import calculate_decision_quality_score

        for mv in (0, 1):
            assert (
                calculate_decision_quality_score({"accepted": 1}, decayed_counts={"accepted": 1.0}, min_volume=mv)
                == 1.0
            )

    def test_fetch_decayed_outcome_counts_skips_future_stamped_rows(self, ec_db):
        """A row stamped in the future (clock skew / corrupt data) is excluded, not clamped to weight 1.0."""
        import uuid
        from datetime import datetime, timedelta, timezone

        from entirecontext.core.decisions import _fetch_decayed_outcome_counts, create_decision

        d = create_decision(ec_db, title="Future-stamp target")
        now = datetime.now(timezone.utc)
        future_row = (now + timedelta(days=30)).isoformat()
        past_row = (now - timedelta(days=10)).isoformat()
        ec_db.execute(
            "INSERT INTO decision_outcomes (id, decision_id, outcome_type, created_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), d["id"], "accepted", future_row),
        )
        ec_db.execute(
            "INSERT INTO decision_outcomes (id, decision_id, outcome_type, created_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), d["id"], "accepted", past_row),
        )
        ec_db.commit()

        decayed = _fetch_decayed_outcome_counts(ec_db, [d["id"]], half_life_days=30.0, now=now)
        # Only the past (10-day-old) row counts: 0.5 ** (10/30) ≈ 0.7937.
        # A clamp implementation would have added 1.0 for the future row, producing >= 1.79.
        accepted = decayed.get(d["id"], {}).get("accepted", 0.0)
        assert 0.75 <= accepted <= 0.82, accepted

    def test_rank_decay_on_outcome_free_decision_yields_zero(self, ec_db):
        """Decay enabled + zero outcomes → decay path with empty bucket → quality=0.

        After PR #88 review-round-1 fix (``.get(did)`` not ``.get(did) or None``),
        the empty bucket stays on the decay path rather than silently switching
        to legacy uniform counts. raw_score=0 + smoothing=0 → quality=0.
        """
        from entirecontext.core.decisions import (
            QualityWeights,
            create_decision,
            link_decision_to_file,
            rank_related_decisions,
        )

        d = create_decision(ec_db, title="No-outcome decision")
        link_decision_to_file(ec_db, d["id"], "src/no_outcome.py")

        ranked = rank_related_decisions(
            ec_db,
            file_paths=["src/no_outcome.py"],
            quality=QualityWeights(recency_half_life_days=30, min_volume=2),
        )
        item = next(r for r in ranked if r["id"] == d["id"])
        assert item["quality_score"] == 0.0
        assert item["score_breakdown"]["quality"] == 0.0

    def test_rank_decay_all_future_stamped_rows_stay_on_decay_path(self, ec_db):
        """Regression guard for PR #88 review round 1 (#discussion_r3098602944).

        If every outcome row is future-stamped (clock skew / corrupt), the
        decayed bucket ends up empty (``{did: {}}``) while the un-decayed
        ``outcome_counts_by_decision`` still contains those rows. The old
        ``.get(did) or None`` pattern treated the empty dict as falsy, routed
        the ranker back to legacy counts, and let the corrupt rows dominate
        quality — undoing the future-stamp skip safeguard. The fix pins the
        decay path on the empty bucket; quality_score collapses to 0 instead
        of mirroring legacy-count arithmetic over the bad rows.
        """
        import uuid
        from datetime import datetime, timedelta, timezone

        from entirecontext.core.decisions import (
            QualityWeights,
            create_decision,
            link_decision_to_file,
            rank_related_decisions,
        )

        d = create_decision(ec_db, title="All-future-stamped decision")
        link_decision_to_file(ec_db, d["id"], "src/corrupt.py")

        now = datetime.now(timezone.utc)
        for delta_days in (1, 3, 5, 10, 20):
            ec_db.execute(
                "INSERT INTO decision_outcomes (id, decision_id, outcome_type, created_at) VALUES (?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    d["id"],
                    "contradicted",
                    (now + timedelta(days=delta_days)).isoformat(),
                ),
            )
        ec_db.commit()

        ranked = rank_related_decisions(
            ec_db,
            file_paths=["src/corrupt.py"],
            quality=QualityWeights(recency_half_life_days=30, min_volume=2),
        )
        item = next(r for r in ranked if r["id"] == d["id"])
        # Legacy path over 5 contradicted rows → -2.0*5 = -10 clamped to -4.
        # Decay path over the empty bucket gives 0.0 (raw_score=0).
        assert item["quality_score"] == 0.0, (
            f"future-stamped rows leaked into legacy path: quality={item['quality_score']}"
        )

    def test_quality_score_refined_replaced_carry_zero_weight(self):
        """refined/replaced rows do not affect the quality score (weight = 0)."""
        from entirecontext.core.decisions import calculate_decision_quality_score

        base = calculate_decision_quality_score({"accepted": 2, "ignored": 1, "contradicted": 1})
        with_new = calculate_decision_quality_score(
            {"accepted": 2, "ignored": 1, "contradicted": 1, "refined": 5, "replaced": 3}
        )
        assert base == with_new

    def test_volume_smoother_ignores_refined_replaced(self):
        """Regression: refined/replaced must NOT count toward the volume smoother total.

        If they did, a single 'accepted' + many 'replaced' rows could push total
        above min_volume and suppress the smoother, yielding a higher score than a
        decision with 1 accepted alone. Score must be identical whether or not
        refined/replaced rows are present.
        """
        from entirecontext.core.decisions import calculate_decision_quality_score

        # 1 accepted, min_volume=2 → smoother applies: raw_score=1.0 * (1/2) = 0.5
        score_without = calculate_decision_quality_score(
            {"accepted": 1},
            decayed_counts={"accepted": 1.0},
            min_volume=2,
        )
        # 1 accepted + 1 replaced → if replaced counted in total, smoother is skipped → 1.0 (wrong)
        score_with_replaced = calculate_decision_quality_score(
            {"accepted": 1, "replaced": 1},
            decayed_counts={"accepted": 1.0, "replaced": 1.0},
            min_volume=2,
        )
        # 1 accepted + 3 refined → same expectation
        score_with_refined = calculate_decision_quality_score(
            {"accepted": 1, "refined": 3},
            decayed_counts={"accepted": 1.0, "refined": 3.0},
            min_volume=2,
        )
        assert score_without == score_with_replaced == score_with_refined

    def test_quality_score_accepted_weight_is_one(self):
        """Verifies the F5b 'existing weight is sufficient' claim: accepted × 1.0."""
        from entirecontext.core.decisions import calculate_decision_quality_score

        assert calculate_decision_quality_score({"accepted": 1}) == 1.0
        assert calculate_decision_quality_score({"accepted": 3}) == 3.0

    def test_quality_score_decayed_refined_replaced_zero_weight(self):
        """Both legacy and decayed branches must ignore refined/replaced rows."""
        from entirecontext.core.decisions import calculate_decision_quality_score

        counts = {"accepted": 2, "ignored": 0, "contradicted": 0, "refined": 4, "replaced": 2}
        decayed = {"accepted": 2.0, "ignored": 0.0, "contradicted": 0.0, "refined": 4.0, "replaced": 2.0}

        score_legacy = calculate_decision_quality_score(counts)
        score_decayed = calculate_decision_quality_score(counts, decayed_counts=decayed, min_volume=2)

        assert score_legacy == 2.0
        assert score_decayed == 2.0

    def test_get_decision_quality_summary_includes_refined_replaced_keys(self, ec_db):
        """quality_summary.counts always has all 5 keys; refined/replaced start at 0."""
        import uuid

        d = create_decision(ec_db, title="Summary key test")
        ec_db.execute(
            "INSERT INTO decision_outcomes (id, decision_id, outcome_type) VALUES (?, ?, 'accepted')",
            (str(uuid.uuid4()), d["id"]),
        )
        ec_db.execute(
            "INSERT INTO decision_outcomes (id, decision_id, outcome_type) VALUES (?, ?, 'refined')",
            (str(uuid.uuid4()), d["id"]),
        )
        ec_db.commit()

        summary = get_decision_quality_summary(ec_db, d["id"])
        counts = summary["counts"]
        assert "refined" in counts
        assert "replaced" in counts
        assert counts["refined"] == 1
        assert counts["replaced"] == 0
        assert counts["accepted"] == 1
        assert summary["quality_score"] == 1.0  # refined has no effect


# ---------------------------------------------------------------------------
# Issue #39: staleness/contradiction hardening regression tests
# ---------------------------------------------------------------------------


class TestStalenessHardening:
    def test_rank_related_excludes_superseded_by_default(self, ec_db):
        """A→B chain: ranking surfaces B, hides A."""
        a = create_decision(ec_db, title="Original")
        b = create_decision(ec_db, title="Replacement")
        link_decision_to_file(ec_db, a["id"], "src/auth.py")
        link_decision_to_file(ec_db, b["id"], "src/auth.py")
        supersede_decision(ec_db, a["id"], b["id"])

        ranked = rank_related_decisions(ec_db, file_paths=["src/auth.py"])
        ids = [r["id"] for r in ranked]
        assert b["id"] in ids
        assert a["id"] not in ids

    def test_rank_related_excludes_contradicted_by_default(self, ec_db):
        fresh = create_decision(ec_db, title="Fresh")
        contradicted = create_decision(ec_db, title="Contradicted")
        link_decision_to_file(ec_db, fresh["id"], "src/api.py")
        link_decision_to_file(ec_db, contradicted["id"], "src/api.py")
        update_decision_staleness(ec_db, contradicted["id"], "contradicted")

        ranked = rank_related_decisions(ec_db, file_paths=["src/api.py"])
        ids = [r["id"] for r in ranked]
        assert fresh["id"] in ids
        assert contradicted["id"] not in ids

    def test_rank_related_fallback_padding_respects_filter(self, ec_db):
        """Padding path (line 833-838) must not smuggle in superseded decisions."""
        # Create a single fresh candidate via file link; no signal-matched others.
        signal = create_decision(ec_db, title="Signal match")
        link_decision_to_file(ec_db, signal["id"], "src/only.py")
        # Create many superseded decisions that would be recent but should be filtered
        # out by the padding fallback path.
        for i in range(10):
            sup = create_decision(ec_db, title=f"Superseded {i}")
            update_decision_staleness(ec_db, sup["id"], "superseded")

        ranked = rank_related_decisions(ec_db, file_paths=["src/only.py"])
        for r in ranked:
            assert r.get("staleness_status") != "superseded"

    def test_chain_collapse_substitutes_terminal(self, ec_db):
        """A→B→C: ranking A's signal surfaces C (terminal)."""
        a = create_decision(ec_db, title="Gen 1")
        b = create_decision(ec_db, title="Gen 2")
        c = create_decision(ec_db, title="Gen 3")
        link_decision_to_file(ec_db, a["id"], "src/model.py")
        link_decision_to_file(ec_db, b["id"], "src/model.py")
        link_decision_to_file(ec_db, c["id"], "src/model.py")
        supersede_decision(ec_db, a["id"], b["id"])
        supersede_decision(ec_db, b["id"], c["id"])

        ranked = rank_related_decisions(ec_db, file_paths=["src/model.py"])
        ids = [r["id"] for r in ranked]
        assert c["id"] in ids
        assert a["id"] not in ids
        assert b["id"] not in ids

    def test_chain_collapse_inherits_signals_from_ancestor(self, ec_db):
        """Review P1 regression: A matches by file, B has no file link yet.

        Expected behavior: B (terminal) appears in results by inheriting A's file
        signal. Previously, B would get base_score=0 and be dropped entirely.
        """
        a = create_decision(ec_db, title="Original with file link")
        b = create_decision(ec_db, title="Replacement without file link yet")
        link_decision_to_file(ec_db, a["id"], "src/migration.py")
        # NOTE: intentionally not linking B to the file — common migration state.
        supersede_decision(ec_db, a["id"], b["id"])

        ranked = rank_related_decisions(ec_db, file_paths=["src/migration.py"])
        ids = [r["id"] for r in ranked]
        assert b["id"] in ids
        assert a["id"] not in ids
        b_item = next(r for r in ranked if r["id"] == b["id"])
        assert b_item["base_score"] >= 3.0  # file_exact contributes 3.0

    def test_chain_collapse_drops_when_terminal_contradicted(self, ec_db):
        """A→B, B contradicted: empty result + stats reason."""
        a = create_decision(ec_db, title="Original")
        b = create_decision(ec_db, title="Broken replacement")
        link_decision_to_file(ec_db, a["id"], "src/payment.py")
        link_decision_to_file(ec_db, b["id"], "src/payment.py")
        supersede_decision(ec_db, a["id"], b["id"])
        update_decision_staleness(ec_db, b["id"], "contradicted")

        ranked, stats = rank_related_decisions(ec_db, file_paths=["src/payment.py"], _return_stats=True)
        ids = [r["id"] for r in ranked]
        assert a["id"] not in ids
        assert b["id"] not in ids
        assert stats["filtered_count"] >= 1
        assert "chain_terminal_contradicted" in stats["by_reason"] or "contradicted" in stats["by_reason"]

    def test_resolve_successor_chain_depth_cap(self, ec_db):
        """A self-referential pointer must not loop forever."""
        from entirecontext.core.decisions import resolve_successor_chain

        a = create_decision(ec_db, title="Loop candidate")
        # Construct a chain of 3: A→B→C (no cycle), verify terminal is C
        b = create_decision(ec_db, title="B")
        c = create_decision(ec_db, title="C")
        supersede_decision(ec_db, a["id"], b["id"])
        supersede_decision(ec_db, b["id"], c["id"])

        terminal_id, status = resolve_successor_chain(ec_db, a["id"])
        assert terminal_id == c["id"]
        assert status == "fresh"

    def test_supersede_detects_cycle(self, ec_db):
        """supersede(B, A) after supersede(A, B) must raise."""
        a = create_decision(ec_db, title="A")
        b = create_decision(ec_db, title="B")
        supersede_decision(ec_db, a["id"], b["id"])

        with pytest.raises(ValueError, match="cycle"):
            supersede_decision(ec_db, b["id"], a["id"])

    def test_supersede_detects_cycle_deeper_than_depth_cap(self, ec_db):
        """PR #55 Codex review: cycle detection must work beyond the nominal
        depth cap. Build a chain of 2*cap+2 nodes (far deeper than +1) and
        verify that closing it into a cycle is rejected — independent of cap.
        """
        from entirecontext.core.decisions import _SUCCESSOR_CHAIN_DEPTH_CAP

        chain_len = _SUCCESSOR_CHAIN_DEPTH_CAP * 2 + 2  # well beyond the old +1 limit
        nodes = [create_decision(ec_db, title=f"deep-{i}") for i in range(chain_len)]
        for i in range(chain_len - 1):
            supersede_decision(ec_db, nodes[i]["id"], nodes[i + 1]["id"])

        # The tail is the current terminal (fresh). Attempting tail → head must
        # be detected as a cycle even though head sits at depth chain_len - 1,
        # which is far deeper than _SUCCESSOR_CHAIN_DEPTH_CAP.
        with pytest.raises(ValueError, match="cycle"):
            supersede_decision(ec_db, nodes[-1]["id"], nodes[0]["id"])

    def test_supersede_detects_cycle_at_depth_cap(self, ec_db):
        """PR #55 review: off-by-one regression — build a chain of length
        _SUCCESSOR_CHAIN_DEPTH_CAP + 1 (11 nodes, 10 hops) then attempt a
        supersede that would close it into a cycle of the same depth.
        The cycle-check loop must walk the full chain, not exit one hop early.
        """
        from entirecontext.core.decisions import _SUCCESSOR_CHAIN_DEPTH_CAP

        cap_plus_one = _SUCCESSOR_CHAIN_DEPTH_CAP + 1
        nodes = [create_decision(ec_db, title=f"node-{i}") for i in range(cap_plus_one)]
        # Build chain: nodes[0] → nodes[1] → ... → nodes[cap]  (cap hops, cap+1 nodes)
        for i in range(cap_plus_one - 1):
            supersede_decision(ec_db, nodes[i]["id"], nodes[i + 1]["id"])

        # Now the chain looks like: nodes[0] .. nodes[-1] (terminal, fresh).
        # Attempting to make nodes[-1] → nodes[0] must be detected as a cycle.
        # Without the +1 fix, probe walker exits before reaching nodes[0] and
        # the UPDATE would silently create a cycle.
        with pytest.raises(ValueError, match="cycle"):
            supersede_decision(ec_db, nodes[-1]["id"], nodes[0]["id"])

    def test_resolve_successor_chain_reaches_depth_cap_terminal(self, ec_db):
        """PR #55 review: build the longest chain the walker is supposed to
        resolve (cap + 1 nodes, cap hops) and verify the terminal is returned
        correctly rather than dropped one hop early with 'superseded' status.
        """
        from entirecontext.core.decisions import _SUCCESSOR_CHAIN_DEPTH_CAP, resolve_successor_chain

        cap_plus_one = _SUCCESSOR_CHAIN_DEPTH_CAP + 1
        nodes = [create_decision(ec_db, title=f"chain-{i}") for i in range(cap_plus_one)]
        for i in range(cap_plus_one - 1):
            supersede_decision(ec_db, nodes[i]["id"], nodes[i + 1]["id"])

        terminal_id, status = resolve_successor_chain(ec_db, nodes[0]["id"])
        assert terminal_id == nodes[-1]["id"]
        assert status == "fresh"

    def test_fts_search_default_excludes_superseded(self, ec_db):
        fresh = create_decision(ec_db, title="freshkeywordalpha")
        sup = create_decision(ec_db, title="freshkeywordalpha also")
        update_decision_staleness(ec_db, sup["id"], "superseded")

        results = fts_search_decisions(ec_db, "freshkeywordalpha")
        ids = [r["id"] for r in results]
        assert fresh["id"] in ids
        assert sup["id"] not in ids

    def test_fts_search_include_superseded_flag(self, ec_db):
        fresh = create_decision(ec_db, title="keywordzulu")
        sup = create_decision(ec_db, title="keywordzulu alternate")
        update_decision_staleness(ec_db, sup["id"], "superseded")

        results = fts_search_decisions(ec_db, "keywordzulu", include_superseded=True)
        ids = [r["id"] for r in results]
        assert fresh["id"] in ids
        assert sup["id"] in ids

    def test_fts_search_include_contradicted_default_and_opt_in(self, ec_db):
        c = create_decision(ec_db, title="keywordbravo")
        update_decision_staleness(ec_db, c["id"], "contradicted")

        # Default: include_contradicted=False — contradicted excluded.
        default_results = fts_search_decisions(ec_db, "keywordbravo")
        assert not any(r["id"] == c["id"] for r in default_results)

        # Explicit opt-in: include_contradicted=True — contradicted included.
        inclusive_results = fts_search_decisions(ec_db, "keywordbravo", include_contradicted=True)
        assert any(r["id"] == c["id"] for r in inclusive_results)

    def test_hybrid_search_inherits_filter(self, ec_db):
        fresh = create_decision(ec_db, title="keywordindia")
        sup = create_decision(ec_db, title="keywordindia replaced")
        update_decision_staleness(ec_db, sup["id"], "superseded")

        results = hybrid_search_decisions(ec_db, "keywordindia")
        ids = [r["id"] for r in results]
        assert fresh["id"] in ids
        assert sup["id"] not in ids

    def test_get_decision_successor_field(self, ec_db):
        a = create_decision(ec_db, title="Old")
        b = create_decision(ec_db, title="New")
        supersede_decision(ec_db, a["id"], b["id"])

        full = get_decision(ec_db, a["id"])
        assert full is not None
        assert full.get("successor") == {"id": b["id"], "title": "New"}

    def test_get_decision_no_successor_field_when_fresh(self, ec_db):
        d = create_decision(ec_db, title="Still fresh")
        full = get_decision(ec_db, d["id"])
        assert full is not None
        assert "successor" not in full

    def test_auto_promotion_crosses_threshold(self, ec_db):
        d = create_decision(ec_db, title="Will be auto-promoted")
        assert d["staleness_status"] == "fresh"

        record_decision_outcome(ec_db, d["id"], "contradicted")
        # After 1 contradicted: still below threshold (default = 2)
        row = ec_db.execute("SELECT staleness_status FROM decisions WHERE id = ?", (d["id"],)).fetchone()
        assert row["staleness_status"] == "fresh"

        record_decision_outcome(ec_db, d["id"], "contradicted")
        # After 2 contradicted: meets threshold AND > accepted (0) → auto-promoted
        row = ec_db.execute("SELECT staleness_status FROM decisions WHERE id = ?", (d["id"],)).fetchone()
        assert row["staleness_status"] == "contradicted"

    def test_auto_promotion_respects_accepted_majority(self, ec_db):
        d = create_decision(ec_db, title="Mostly accepted")
        record_decision_outcome(ec_db, d["id"], "accepted")
        record_decision_outcome(ec_db, d["id"], "accepted")
        record_decision_outcome(ec_db, d["id"], "accepted")
        record_decision_outcome(ec_db, d["id"], "contradicted")
        record_decision_outcome(ec_db, d["id"], "contradicted")

        # 2 contradicted vs 3 accepted: accepted still wins → no promotion
        row = ec_db.execute("SELECT staleness_status FROM decisions WHERE id = ?", (d["id"],)).fetchone()
        assert row["staleness_status"] == "fresh"

    def test_auto_promotion_is_one_way_ratchet(self, ec_db):
        d = create_decision(ec_db, title="Promote and revert?")
        record_decision_outcome(ec_db, d["id"], "contradicted")
        record_decision_outcome(ec_db, d["id"], "contradicted")

        # Promoted after 2 contradicted
        row = ec_db.execute("SELECT staleness_status FROM decisions WHERE id = ?", (d["id"],)).fetchone()
        assert row["staleness_status"] == "contradicted"

        # Adding many accepts does NOT revert
        for _ in range(10):
            record_decision_outcome(ec_db, d["id"], "accepted")

        row = ec_db.execute("SELECT staleness_status FROM decisions WHERE id = ?", (d["id"],)).fetchone()
        assert row["staleness_status"] == "contradicted"

    def test_auto_promotion_skips_already_superseded(self, ec_db):
        a = create_decision(ec_db, title="Superseded original")
        b = create_decision(ec_db, title="Replacement")
        supersede_decision(ec_db, a["id"], b["id"])
        # A is now 'superseded'
        record_decision_outcome(ec_db, a["id"], "contradicted")
        record_decision_outcome(ec_db, a["id"], "contradicted")

        row = ec_db.execute("SELECT staleness_status FROM decisions WHERE id = ?", (a["id"],)).fetchone()
        assert row["staleness_status"] == "superseded"

    def test_manual_fresh_reset_restarts_auto_promotion_window(self, ec_db):
        d = create_decision(ec_db, title="Recoverable contradiction")
        record_decision_outcome(ec_db, d["id"], "contradicted")
        record_decision_outcome(ec_db, d["id"], "contradicted")

        row = ec_db.execute(
            "SELECT staleness_status, auto_promotion_reset_at FROM decisions WHERE id = ?",
            (d["id"],),
        ).fetchone()
        assert row["staleness_status"] == "contradicted"
        assert row["auto_promotion_reset_at"] is None

        update_decision_staleness(ec_db, d["id"], "fresh")

        row = ec_db.execute(
            "SELECT staleness_status, auto_promotion_reset_at FROM decisions WHERE id = ?",
            (d["id"],),
        ).fetchone()
        assert row["staleness_status"] == "fresh"
        assert row["auto_promotion_reset_at"] is not None

        record_decision_outcome(ec_db, d["id"], "contradicted")
        row = ec_db.execute("SELECT staleness_status FROM decisions WHERE id = ?", (d["id"],)).fetchone()
        assert row["staleness_status"] == "fresh"

        record_decision_outcome(ec_db, d["id"], "contradicted")
        row = ec_db.execute("SELECT staleness_status FROM decisions WHERE id = ?", (d["id"],)).fetchone()
        assert row["staleness_status"] == "contradicted"

    def test_data_integrity_superseded_requires_status(self, ec_db):
        """Invariant: superseded_by_id set implies staleness_status='superseded'."""
        a = create_decision(ec_db, title="A")
        b = create_decision(ec_db, title="B")
        supersede_decision(ec_db, a["id"], b["id"])

        row = ec_db.execute(
            "SELECT COUNT(*) AS n FROM decisions "
            "WHERE superseded_by_id IS NOT NULL AND staleness_status != 'superseded'"
        ).fetchone()
        assert row["n"] == 0

    def test_record_outcome_respects_outer_transaction(self, ec_db):
        """PR #55 review: when the caller already owns a transaction,
        record_decision_outcome must NOT commit on its own. The outer
        scope decides the atomic boundary, and a caller rollback must
        still be able to undo the nested write.
        """
        d = create_decision(ec_db, title="Outer tx target")

        # Caller opens an outer transaction, calls record_decision_outcome
        # (which must detect the nested case and skip its own commit),
        # then rolls back the outer scope. The nested INSERT must also
        # disappear — proving no implicit commit happened inside.
        # Coordinate the manual BEGIN IMMEDIATE with the helper's depth
        # counter so the nested transaction() call inside record_decision_outcome
        # sees depth>0 and defers to this outer owner. Also use SQL ROLLBACK
        # since conn.rollback() is a no-op under autocommit.
        ec_db.execute("BEGIN IMMEDIATE")
        ec_db._ec_tx_depth = 1
        try:
            result = record_decision_outcome(ec_db, d["id"], "accepted")
            assert result["decision_id"] == d["id"]
            assert getattr(ec_db, "_ec_tx_depth", 0) >= 1  # outer tx still owns the boundary
        finally:
            ec_db._ec_tx_depth = 0
            ec_db.execute("ROLLBACK")

        row = ec_db.execute(
            "SELECT COUNT(*) AS n FROM decision_outcomes WHERE decision_id = ?",
            (d["id"],),
        ).fetchone()
        assert row["n"] == 0

    def test_record_outcome_rolls_back_on_dml_failure(self, ec_db, monkeypatch):
        """PR #55 review: when DML inside the BEGIN IMMEDIATE block fails, the
        transaction must be explicitly rolled back so subsequent calls on the
        same connection are not blocked by a stale open write transaction.
        """
        d = create_decision(ec_db, title="Outcome rollback target")

        # Force a failure mid-transaction by patching the auto-promotion helper
        # to raise. This simulates any exception happening between BEGIN IMMEDIATE
        # and commit (e.g. FK violation, OperationalError, unexpected runtime error).
        def boom(_conn, _decision_id, _now):
            raise RuntimeError("simulated auto-promotion failure")

        monkeypatch.setattr(
            "entirecontext.core.decisions._maybe_auto_promote_contradicted",
            boom,
        )

        # outcome_type="contradicted" is required to route through the patched helper.
        with pytest.raises(RuntimeError, match="simulated auto-promotion failure"):
            record_decision_outcome(ec_db, d["id"], "contradicted")

        # Undo the patch so the follow-up call uses the real implementation.
        monkeypatch.undo()

        # If rollback worked, the same connection must still be usable —
        # proving the write transaction was rolled back instead of left open.
        follow_up = record_decision_outcome(ec_db, d["id"], "accepted")
        assert follow_up["decision_id"] == d["id"]

        # The failed contradicted outcome must not have persisted.
        row = ec_db.execute(
            "SELECT COUNT(*) AS n FROM decision_outcomes WHERE decision_id = ?",
            (d["id"],),
        ).fetchone()
        assert row["n"] == 1  # only the successful `accepted` outcome
