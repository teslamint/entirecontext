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
from entirecontext.core.decisions import rank_related_decisions
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
        record_decision_outcome(ec_db, demoted["id"], "contradicted")

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
        with pytest.raises(ValueError, match="Invalid FTS5 query syntax"):
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

        ranked = rank_related_decisions(ec_db, file_paths=["src/core.py"])
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
