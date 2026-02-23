"""TDD tests for typed assessment relationships (causes/fixes/contradicts)."""

from __future__ import annotations

import pytest

from entirecontext.core.futures import (
    add_assessment_relationship,
    create_assessment,
    get_assessment_relationships,
    remove_assessment_relationship,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_assessment(conn, verdict="expand", impact="test impact"):
    return create_assessment(conn, verdict=verdict, impact_summary=impact)


# ---------------------------------------------------------------------------
# add_assessment_relationship tests
# ---------------------------------------------------------------------------


class TestAddAssessmentRelationship:
    def test_add_causes_relationship(self, ec_db):
        a1 = _make_assessment(ec_db, impact="Introduced tight coupling")
        a2 = _make_assessment(ec_db, impact="Hard to extend later")
        rel = add_assessment_relationship(ec_db, a1["id"], a2["id"], "causes")
        assert rel["source_id"] == a1["id"]
        assert rel["target_id"] == a2["id"]
        assert rel["relationship_type"] == "causes"

    def test_add_fixes_relationship(self, ec_db):
        a1 = _make_assessment(ec_db, impact="Refactored tight coupling")
        a2 = _make_assessment(ec_db, impact="Hard to extend later")
        rel = add_assessment_relationship(ec_db, a1["id"], a2["id"], "fixes")
        assert rel["relationship_type"] == "fixes"

    def test_add_contradicts_relationship(self, ec_db):
        a1 = _make_assessment(ec_db, verdict="expand", impact="This expands options")
        a2 = _make_assessment(ec_db, verdict="narrow", impact="This narrows options")
        rel = add_assessment_relationship(ec_db, a1["id"], a2["id"], "contradicts")
        assert rel["relationship_type"] == "contradicts"

    def test_relationship_has_required_fields(self, ec_db):
        a1 = _make_assessment(ec_db)
        a2 = _make_assessment(ec_db)
        rel = add_assessment_relationship(ec_db, a1["id"], a2["id"], "causes")
        assert "id" in rel
        assert "source_id" in rel
        assert "target_id" in rel
        assert "relationship_type" in rel
        assert "created_at" in rel
        assert rel["note"] is None  # default

    def test_relationship_with_note(self, ec_db):
        a1 = _make_assessment(ec_db)
        a2 = _make_assessment(ec_db)
        rel = add_assessment_relationship(ec_db, a1["id"], a2["id"], "fixes", note="Refactoring resolved this")
        assert rel["note"] == "Refactoring resolved this"

    def test_invalid_relationship_type_raises(self, ec_db):
        a1 = _make_assessment(ec_db)
        a2 = _make_assessment(ec_db)
        with pytest.raises(ValueError, match="Invalid relationship_type"):
            add_assessment_relationship(ec_db, a1["id"], a2["id"], "invalidtype")

    def test_nonexistent_source_raises(self, ec_db):
        a2 = _make_assessment(ec_db)
        with pytest.raises(ValueError, match="not found"):
            add_assessment_relationship(ec_db, "nonexistent-id", a2["id"], "causes")

    def test_nonexistent_target_raises(self, ec_db):
        a1 = _make_assessment(ec_db)
        with pytest.raises(ValueError, match="not found"):
            add_assessment_relationship(ec_db, a1["id"], "nonexistent-id", "causes")

    def test_duplicate_relationship_raises(self, ec_db):
        a1 = _make_assessment(ec_db)
        a2 = _make_assessment(ec_db)
        add_assessment_relationship(ec_db, a1["id"], a2["id"], "causes")
        with pytest.raises(ValueError, match="already exists"):
            add_assessment_relationship(ec_db, a1["id"], a2["id"], "causes")

    def test_different_types_between_same_pair_allowed(self, ec_db):
        a1 = _make_assessment(ec_db)
        a2 = _make_assessment(ec_db)
        add_assessment_relationship(ec_db, a1["id"], a2["id"], "causes")
        rel2 = add_assessment_relationship(ec_db, a1["id"], a2["id"], "contradicts")
        assert rel2["relationship_type"] == "contradicts"

    def test_prefix_id_support(self, ec_db):
        a1 = _make_assessment(ec_db)
        a2 = _make_assessment(ec_db)
        # Use prefix IDs (first 12 chars like the CLI)
        rel = add_assessment_relationship(ec_db, a1["id"][:12], a2["id"][:12], "fixes")
        assert rel["source_id"] == a1["id"]
        assert rel["target_id"] == a2["id"]

    def test_self_referential_relationship_raises(self, ec_db):
        a1 = _make_assessment(ec_db)
        with pytest.raises(ValueError, match="cannot relate to itself"):
            add_assessment_relationship(ec_db, a1["id"], a1["id"], "causes")


# ---------------------------------------------------------------------------
# get_assessment_relationships tests
# ---------------------------------------------------------------------------


class TestGetAssessmentRelationships:
    def test_get_outgoing_relationships(self, ec_db):
        a1 = _make_assessment(ec_db, impact="Source")
        a2 = _make_assessment(ec_db, impact="Target A")
        a3 = _make_assessment(ec_db, impact="Target B")
        add_assessment_relationship(ec_db, a1["id"], a2["id"], "causes")
        add_assessment_relationship(ec_db, a1["id"], a3["id"], "fixes")

        rels = get_assessment_relationships(ec_db, a1["id"], direction="outgoing")
        assert len(rels) == 2
        assert all(r["source_id"] == a1["id"] for r in rels)

    def test_get_incoming_relationships(self, ec_db):
        a1 = _make_assessment(ec_db, impact="Source A")
        a2 = _make_assessment(ec_db, impact="Source B")
        a3 = _make_assessment(ec_db, impact="Target")
        add_assessment_relationship(ec_db, a1["id"], a3["id"], "causes")
        add_assessment_relationship(ec_db, a2["id"], a3["id"], "fixes")

        rels = get_assessment_relationships(ec_db, a3["id"], direction="incoming")
        assert len(rels) == 2
        assert all(r["target_id"] == a3["id"] for r in rels)

    def test_get_both_directions_default(self, ec_db):
        a1 = _make_assessment(ec_db, impact="Middle")
        a2 = _make_assessment(ec_db, impact="Source of middle")
        a3 = _make_assessment(ec_db, impact="Target of middle")
        add_assessment_relationship(ec_db, a2["id"], a1["id"], "causes")
        add_assessment_relationship(ec_db, a1["id"], a3["id"], "fixes")

        rels = get_assessment_relationships(ec_db, a1["id"])  # default direction="both"
        assert len(rels) == 2

    def test_returns_empty_when_no_relationships(self, ec_db):
        a1 = _make_assessment(ec_db)
        rels = get_assessment_relationships(ec_db, a1["id"])
        assert rels == []

    def test_nonexistent_assessment_returns_empty(self, ec_db):
        rels = get_assessment_relationships(ec_db, "nonexistent-id")
        assert rels == []

    def test_relationship_includes_counterpart_summary(self, ec_db):
        """Related assessment's impact_summary should be included for display context."""
        a1 = _make_assessment(ec_db, impact="Root cause assessment")
        a2 = _make_assessment(ec_db, impact="Downstream effect")
        add_assessment_relationship(ec_db, a1["id"], a2["id"], "causes")

        rels = get_assessment_relationships(ec_db, a1["id"], direction="outgoing")
        assert len(rels) == 1
        # Should include target's summary for display
        assert rels[0].get("target_impact_summary") == "Downstream effect"

    def test_direction_field_in_results(self, ec_db):
        """Each result should include a 'direction' field for CLI rendering."""
        a1 = _make_assessment(ec_db, impact="Source")
        a2 = _make_assessment(ec_db, impact="Target")
        a3 = _make_assessment(ec_db, impact="Another source")
        add_assessment_relationship(ec_db, a1["id"], a2["id"], "causes")
        add_assessment_relationship(ec_db, a3["id"], a1["id"], "fixes")

        rels = get_assessment_relationships(ec_db, a1["id"], direction="both")
        assert len(rels) == 2
        directions = {r["direction"] for r in rels}
        assert "outgoing" in directions
        assert "incoming" in directions

    def test_prefix_id_support(self, ec_db):
        a1 = _make_assessment(ec_db)
        a2 = _make_assessment(ec_db)
        add_assessment_relationship(ec_db, a1["id"], a2["id"], "contradicts")

        rels = get_assessment_relationships(ec_db, a1["id"][:12], direction="outgoing")
        assert len(rels) == 1


# ---------------------------------------------------------------------------
# remove_assessment_relationship tests
# ---------------------------------------------------------------------------


class TestRemoveAssessmentRelationship:
    def test_remove_existing_relationship(self, ec_db):
        a1 = _make_assessment(ec_db)
        a2 = _make_assessment(ec_db)
        add_assessment_relationship(ec_db, a1["id"], a2["id"], "causes")

        removed = remove_assessment_relationship(ec_db, a1["id"], a2["id"], "causes")
        assert removed is True

        rels = get_assessment_relationships(ec_db, a1["id"])
        assert rels == []

    def test_remove_nonexistent_returns_false(self, ec_db):
        a1 = _make_assessment(ec_db)
        a2 = _make_assessment(ec_db)
        removed = remove_assessment_relationship(ec_db, a1["id"], a2["id"], "causes")
        assert removed is False

    def test_remove_only_specified_type(self, ec_db):
        a1 = _make_assessment(ec_db)
        a2 = _make_assessment(ec_db)
        add_assessment_relationship(ec_db, a1["id"], a2["id"], "causes")
        add_assessment_relationship(ec_db, a1["id"], a2["id"], "contradicts")

        removed = remove_assessment_relationship(ec_db, a1["id"], a2["id"], "causes")
        assert removed is True

        rels = get_assessment_relationships(ec_db, a1["id"])
        assert len(rels) == 1
        assert rels[0]["relationship_type"] == "contradicts"

    def test_prefix_id_support(self, ec_db):
        a1 = _make_assessment(ec_db)
        a2 = _make_assessment(ec_db)
        add_assessment_relationship(ec_db, a1["id"], a2["id"], "fixes")
        removed = remove_assessment_relationship(ec_db, a1["id"][:12], a2["id"][:12], "fixes")
        assert removed is True
