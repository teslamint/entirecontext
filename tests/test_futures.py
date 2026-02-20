"""Tests for futures assessment module."""

from __future__ import annotations

import pytest

from entirecontext.core.futures import (
    add_feedback,
    create_assessment,
    distill_lessons,
    get_assessment,
    get_lessons,
    list_assessments,
)


def test_create_assessment(ec_db):
    """Test creating and retrieving an assessment."""
    result = create_assessment(
        ec_db,
        verdict="expand",
        impact_summary="Adds new API surface",
        roadmap_alignment="Aligned with Q1 goals",
        tidy_suggestion="Consider extracting interface",
    )
    assert result["verdict"] == "expand"
    assert result["id"]

    fetched = get_assessment(ec_db, result["id"])
    assert fetched is not None
    assert fetched["verdict"] == "expand"
    assert fetched["impact_summary"] == "Adds new API surface"


def test_list_assessments_filter(ec_db):
    """Test listing assessments with verdict filter."""
    create_assessment(ec_db, verdict="expand", impact_summary="A")
    create_assessment(ec_db, verdict="narrow", impact_summary="B")
    create_assessment(ec_db, verdict="expand", impact_summary="C")

    all_items = list_assessments(ec_db)
    assert len(all_items) == 3

    expand_only = list_assessments(ec_db, verdict="expand")
    assert len(expand_only) == 2
    assert all(a["verdict"] == "expand" for a in expand_only)

    narrow_only = list_assessments(ec_db, verdict="narrow")
    assert len(narrow_only) == 1


def test_add_feedback(ec_db):
    """Test adding feedback to an assessment."""
    result = create_assessment(ec_db, verdict="neutral", impact_summary="Test")
    add_feedback(ec_db, result["id"], "agree", feedback_reason="Looks correct")

    fetched = get_assessment(ec_db, result["id"])
    assert fetched["feedback"] == "agree"
    assert fetched["feedback_reason"] == "Looks correct"

    lessons = get_lessons(ec_db)
    assert len(lessons) == 1
    assert lessons[0]["id"] == result["id"]


def test_invalid_verdict(ec_db):
    """Test that invalid verdict raises ValueError."""
    with pytest.raises(ValueError, match="Invalid verdict"):
        create_assessment(ec_db, verdict="invalid")


def test_invalid_feedback(ec_db):
    """Test that invalid feedback raises ValueError."""
    result = create_assessment(ec_db, verdict="expand", impact_summary="Test")
    with pytest.raises(ValueError, match="Invalid feedback"):
        add_feedback(ec_db, result["id"], "maybe")


def test_distill_lessons():
    """Test lessons formatting."""
    assessments = [
        {
            "id": "aaaa-bbbb-cccc",
            "verdict": "expand",
            "impact_summary": "Good change",
            "roadmap_alignment": "Aligned",
            "tidy_suggestion": "Keep it",
            "feedback": "agree",
            "feedback_reason": "Correct",
            "created_at": "2025-01-01T00:00:00",
        },
    ]
    text = distill_lessons(assessments)
    assert "# Lessons Learned" in text
    assert "Good change" in text
    assert "Aligned" in text


def test_distill_lessons_empty():
    """Test empty lessons formatting."""
    text = distill_lessons([])
    assert "No lessons recorded yet" in text


def test_get_assessment_prefix_match(ec_db):
    """Test that get_assessment supports prefix matching (regression: dd6184a2-c16 not found)."""
    result = create_assessment(ec_db, verdict="expand", impact_summary="Prefix test")
    full_id = result["id"]

    # Full ID should work
    assert get_assessment(ec_db, full_id) is not None

    # Prefix (first 12 chars, as displayed in CLI) should also work
    prefix = full_id[:12]
    fetched = get_assessment(ec_db, prefix)
    assert fetched is not None
    assert fetched["id"] == full_id
    assert fetched["impact_summary"] == "Prefix test"

    # Short prefix should also work
    short = full_id[:8]
    fetched2 = get_assessment(ec_db, short)
    assert fetched2 is not None
    assert fetched2["id"] == full_id


def test_feedback_with_prefix(ec_db):
    """Test that feedback works with prefix ID (regression)."""
    result = create_assessment(ec_db, verdict="narrow", impact_summary="Feedback prefix test")
    prefix = result["id"][:12]

    # Should not raise
    add_feedback(ec_db, prefix, "disagree", feedback_reason="Testing prefix")

    fetched = get_assessment(ec_db, result["id"])
    assert fetched["feedback"] == "disagree"
