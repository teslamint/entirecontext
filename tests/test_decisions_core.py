"""Tests for decision domain core APIs."""

from __future__ import annotations

import pytest

from entirecontext.core.decisions import (
    add_decision_relationship,
    check_staleness,
    create_decision,
    detect_contradictions,
    get_decision,
    get_decision_quality_summary,
    get_decision_relationships,
    link_decision_to_assessment,
    link_decision_to_checkpoint,
    link_decision_to_commit,
    link_decision_to_file,
    list_decision_outcomes,
    list_decisions,
    record_decision_outcome,
    remove_decision_relationship,
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
from entirecontext.core.search import rank_related_decisions
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
        assert ranked[0]["base_score"] == ranked[1]["base_score"] == 2.0


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


class TestDecisionRelationships:
    def test_add_and_get_relationship(self, ec_db):
        a = create_decision(ec_db, title="Decision A")
        b = create_decision(ec_db, title="Decision B")
        rel = add_decision_relationship(ec_db, a["id"], b["id"], "contradicts", note="scope conflict")
        assert rel["source_id"] == a["id"]
        assert rel["target_id"] == b["id"]
        assert rel["relationship_type"] == "contradicts"
        assert rel["note"] == "scope conflict"

        rels = get_decision_relationships(ec_db, a["id"])
        assert len(rels) == 1
        assert rels[0]["direction"] == "outgoing"
        assert rels[0]["target_title"] == "Decision B"

        rels_b = get_decision_relationships(ec_db, b["id"])
        assert len(rels_b) == 1
        assert rels_b[0]["direction"] == "incoming"
        assert rels_b[0]["source_title"] == "Decision A"

    def test_direction_filtering(self, ec_db):
        a = create_decision(ec_db, title="Source")
        b = create_decision(ec_db, title="Target")
        add_decision_relationship(ec_db, a["id"], b["id"], "related_to")

        assert len(get_decision_relationships(ec_db, a["id"], direction="outgoing")) == 1
        assert len(get_decision_relationships(ec_db, a["id"], direction="incoming")) == 0
        assert len(get_decision_relationships(ec_db, b["id"], direction="incoming")) == 1
        assert len(get_decision_relationships(ec_db, b["id"], direction="outgoing")) == 0

    def test_duplicate_relationship_raises(self, ec_db):
        a = create_decision(ec_db, title="A")
        b = create_decision(ec_db, title="B")
        add_decision_relationship(ec_db, a["id"], b["id"], "contradicts")
        with pytest.raises(Exception):
            add_decision_relationship(ec_db, a["id"], b["id"], "contradicts")

    def test_self_relationship_raises(self, ec_db):
        a = create_decision(ec_db, title="Self")
        with pytest.raises(ValueError, match="cannot have a relationship with itself"):
            add_decision_relationship(ec_db, a["id"], a["id"], "contradicts")

    def test_invalid_type_raises(self, ec_db):
        a = create_decision(ec_db, title="A")
        b = create_decision(ec_db, title="B")
        with pytest.raises(ValueError, match="Invalid relationship_type"):
            add_decision_relationship(ec_db, a["id"], b["id"], "invalid_type")

    def test_remove_relationship(self, ec_db):
        a = create_decision(ec_db, title="A")
        b = create_decision(ec_db, title="B")
        add_decision_relationship(ec_db, a["id"], b["id"], "related_to")
        assert remove_decision_relationship(ec_db, a["id"], b["id"], "related_to") is True
        assert len(get_decision_relationships(ec_db, a["id"])) == 0

    def test_remove_nonexistent_returns_false(self, ec_db):
        a = create_decision(ec_db, title="A")
        b = create_decision(ec_db, title="B")
        assert remove_decision_relationship(ec_db, a["id"], b["id"], "contradicts") is False

    def test_get_decision_includes_relationships(self, ec_db):
        a = create_decision(ec_db, title="A")
        b = create_decision(ec_db, title="B")
        add_decision_relationship(ec_db, a["id"], b["id"], "supersedes")
        fetched = get_decision(ec_db, a["id"])
        assert "relationships" in fetched
        assert len(fetched["relationships"]) == 1
        assert fetched["relationships"][0]["relationship_type"] == "supersedes"

    def test_supersede_creates_relationship(self, ec_db):
        old = create_decision(ec_db, title="Old")
        new = create_decision(ec_db, title="New")
        supersede_decision(ec_db, old["id"], new["id"])
        rels = get_decision_relationships(ec_db, new["id"], direction="outgoing")
        assert len(rels) == 1
        assert rels[0]["relationship_type"] == "supersedes"
        assert rels[0]["target_id"] == old["id"]

    def test_confidence_stored(self, ec_db):
        a = create_decision(ec_db, title="A")
        b = create_decision(ec_db, title="B")
        rel = add_decision_relationship(ec_db, a["id"], b["id"], "contradicts", confidence=0.5)
        assert rel["confidence"] == 0.5


class TestDetectContradictions:
    def test_detects_file_overlap(self, ec_db):
        a = create_decision(ec_db, title="Use caching")
        b = create_decision(ec_db, title="Avoid caching")
        link_decision_to_file(ec_db, a["id"], "src/cache.py")
        link_decision_to_file(ec_db, b["id"], "src/cache.py")

        results = detect_contradictions(ec_db)
        assert len(results) == 1
        ids = {results[0]["source_id"], results[0]["target_id"]}
        assert ids == {a["id"], b["id"]}
        assert "src/cache.py" in results[0]["shared_files"]

    def test_scope_overlap_boosts_score(self, ec_db):
        a = create_decision(ec_db, title="A", scope="auth")
        b = create_decision(ec_db, title="B", scope="auth")
        c = create_decision(ec_db, title="C", scope="other")
        link_decision_to_file(ec_db, a["id"], "src/auth.py")
        link_decision_to_file(ec_db, b["id"], "src/auth.py")
        link_decision_to_file(ec_db, c["id"], "src/auth.py")

        results = detect_contradictions(ec_db)
        ab_pair = [r for r in results if {r["source_id"], r["target_id"]} == {a["id"], b["id"]}]
        ac_pair = [r for r in results if {r["source_id"], r["target_id"]} == {a["id"], c["id"]}]
        assert ab_pair[0]["score"] > ac_pair[0]["score"]
        assert ab_pair[0]["shared_scope"] == "auth"

    def test_ignores_stale_decisions(self, ec_db):
        a = create_decision(ec_db, title="Fresh", staleness_status="fresh")
        b = create_decision(ec_db, title="Stale", staleness_status="stale")
        link_decision_to_file(ec_db, a["id"], "src/x.py")
        link_decision_to_file(ec_db, b["id"], "src/x.py")

        results = detect_contradictions(ec_db)
        assert len(results) == 0

    def test_excludes_already_linked_contradictions(self, ec_db):
        a = create_decision(ec_db, title="A")
        b = create_decision(ec_db, title="B")
        link_decision_to_file(ec_db, a["id"], "src/x.py")
        link_decision_to_file(ec_db, b["id"], "src/x.py")
        add_decision_relationship(ec_db, a["id"], b["id"], "contradicts")

        results = detect_contradictions(ec_db)
        assert len(results) == 0

    def test_empty_when_no_overlap(self, ec_db):
        a = create_decision(ec_db, title="A")
        b = create_decision(ec_db, title="B")
        link_decision_to_file(ec_db, a["id"], "src/a.py")
        link_decision_to_file(ec_db, b["id"], "src/b.py")

        results = detect_contradictions(ec_db)
        assert len(results) == 0

    def test_min_file_overlap_filter(self, ec_db):
        a = create_decision(ec_db, title="A")
        b = create_decision(ec_db, title="B")
        link_decision_to_file(ec_db, a["id"], "src/x.py")
        link_decision_to_file(ec_db, b["id"], "src/x.py")

        assert len(detect_contradictions(ec_db, min_file_overlap=1)) == 1
        assert len(detect_contradictions(ec_db, min_file_overlap=2)) == 0

    def test_scope_filter(self, ec_db):
        a = create_decision(ec_db, title="A", scope="auth")
        b = create_decision(ec_db, title="B", scope="auth")
        c = create_decision(ec_db, title="C", scope="db")
        link_decision_to_file(ec_db, a["id"], "src/x.py")
        link_decision_to_file(ec_db, b["id"], "src/x.py")
        link_decision_to_file(ec_db, c["id"], "src/x.py")

        results = detect_contradictions(ec_db, scope_filter="auth")
        assert len(results) == 1


class TestStalenessAwareRanking:
    def test_stale_decision_ranked_lower(self, ec_db):
        fresh = create_decision(ec_db, title="Fresh decision")
        stale = create_decision(ec_db, title="Stale decision", staleness_status="stale")
        link_decision_to_file(ec_db, fresh["id"], "src/x.py")
        link_decision_to_file(ec_db, stale["id"], "src/x.py")

        ranked = rank_related_decisions(ec_db, file_paths=["src/x.py"], limit=10)
        assert ranked[0]["id"] == fresh["id"]
        assert ranked[1]["id"] == stale["id"]
        assert ranked[0]["staleness_penalty"] == 0.0
        assert ranked[1]["staleness_penalty"] == -2.0

    def test_superseded_decision_ranked_lowest(self, ec_db):
        fresh = create_decision(ec_db, title="Fresh")
        stale = create_decision(ec_db, title="Stale", staleness_status="stale")
        superseded = create_decision(ec_db, title="Superseded", staleness_status="superseded")
        for d in [fresh, stale, superseded]:
            link_decision_to_file(ec_db, d["id"], "src/x.py")

        ranked = rank_related_decisions(ec_db, file_paths=["src/x.py"], limit=10)
        assert ranked[0]["id"] == fresh["id"]
        assert ranked[-1]["id"] == superseded["id"]
        assert ranked[-1]["staleness_penalty"] == -4.0

    def test_fresh_unaffected(self, ec_db):
        d = create_decision(ec_db, title="Fresh one")
        link_decision_to_file(ec_db, d["id"], "src/x.py")

        ranked = rank_related_decisions(ec_db, file_paths=["src/x.py"], limit=10)
        assert len(ranked) == 1
        assert ranked[0]["staleness_penalty"] == 0.0
        assert ranked[0]["score"] == ranked[0]["base_score"] + ranked[0]["quality_score"]

    def test_contradicted_penalty(self, ec_db):
        d = create_decision(ec_db, title="Contradicted", staleness_status="contradicted")
        link_decision_to_file(ec_db, d["id"], "src/x.py")

        ranked = rank_related_decisions(ec_db, file_paths=["src/x.py"], limit=10)
        assert ranked[0]["staleness_penalty"] == -3.0
