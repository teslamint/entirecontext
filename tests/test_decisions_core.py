"""Tests for decision domain core APIs."""

from __future__ import annotations

import pytest

from entirecontext.core.decisions import (
    create_decision,
    get_decision,
    link_decision_to_assessment,
    link_decision_to_checkpoint,
    link_decision_to_commit,
    link_decision_to_file,
    list_decisions,
    update_decision_staleness,
)
from entirecontext.core.futures import create_assessment, list_assessments
from entirecontext.core.project import get_project
from entirecontext.core.search import rank_related_decisions
from entirecontext.core.session import create_session


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
