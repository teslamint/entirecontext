"""Tests for futures assessment module."""

from __future__ import annotations

import pytest

from entirecontext.core.futures import (
    add_feedback,
    auto_distill_lessons,
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


def test_distill_lessons_has_no_trailing_whitespace():
    """Test that no emitted line ends with whitespace (regression: assessment line had a trailing space)."""
    assessments = [
        {
            "id": "aaaa-bbbb-cccc",
            "verdict": "expand",
            "impact_summary": "Full change",
            "roadmap_alignment": "Aligned",
            "tidy_suggestion": "Keep it",
            "feedback": "agree",
            "feedback_reason": "Correct",
            "created_at": "2025-01-01T00:00:00",
        },
        {
            "id": "dddd-eeee-ffff",
            "verdict": "narrow",
            "impact_summary": "Minimal change",
            "feedback": "disagree",
            "created_at": "2025-01-02T00:00:00",
        },
        {
            "id": "1111-2222-3333",
            "verdict": "neutral",
            "impact_summary": "Neutral change",
            "feedback": "agree",
            "feedback_reason": "Fine",
            "created_at": "",
        },
    ]
    text = distill_lessons(assessments)
    offenders = [line for line in text.split("\n") if line != line.rstrip()]
    assert offenders == []


def test_distill_lessons_headings_are_unique_per_assessment():
    """Identical impact_summary values must not collide into one heading (MD024).

    Every heading came from impact_summary alone, so repeated summaries — auto-assessed
    checkpoints, identical dependency bumps — produced duplicate headings and, with them,
    duplicate anchors that make all but the first entry unreachable by link.
    """
    assessments = [
        {
            "id": f"{i}aaaaaaa-bbbb-cccc",
            "verdict": "neutral",
            "impact_summary": "Auto-assessed checkpoint",
            "feedback": "disagree",
            "created_at": "",
        }
        for i in range(3)
    ]
    headings = [line for line in distill_lessons(assessments).split("\n") if line.startswith("### ")]
    assert len(headings) == 3
    assert len(set(headings)) == 3


def _seed_lesson(conn, verdict: str, created_at: str, feedback: str = "agree") -> str:
    from uuid import uuid4

    lesson_id = str(uuid4())
    conn.execute(
        """INSERT INTO assessments (id, verdict, impact_summary, feedback, created_at)
        VALUES (?, ?, ?, ?, ?)""",
        (lesson_id, verdict, f"{verdict} at {created_at}", feedback, created_at),
    )
    return lesson_id


def test_get_lessons_reserves_floor_for_minority_verdict(ec_db):
    """A neutral flood must not evict every expand lesson (S1)."""
    for i in range(60):
        _seed_lesson(ec_db, "neutral", f"2026-08-14T{i // 60:02d}:{i % 60:02d}:00+00:00")
    for i in range(8):
        _seed_lesson(ec_db, "expand", f"2026-08-01T00:{i:02d}:00+00:00")

    lessons = get_lessons(ec_db, limit=50, min_per_verdict=5)

    assert len(lessons) == 50
    assert len([item for item in lessons if item["verdict"] == "expand"]) >= 5


def test_get_lessons_applies_since_before_verdict_floors(ec_db):
    """Old reserved rows must not displace eligible recent lessons."""
    for i in range(60):
        _seed_lesson(ec_db, "neutral", f"2026-08-14T00:{i:02d}:00+00:00")
    for i in range(5):
        _seed_lesson(ec_db, "expand", f"2026-07-01T00:{i:02d}:00+00:00")

    lessons = get_lessons(
        ec_db,
        limit=50,
        min_per_verdict=5,
        since="2026-08-01",
    )

    assert len(lessons) == 50
    assert all(lesson["created_at"] >= "2026-08-01" for lesson in lessons)


def test_get_lessons_never_exceeds_limit(ec_db):
    """limit stays a total cap across all verdicts (S2)."""
    for verdict in ("expand", "narrow", "neutral"):
        for i in range(10):
            _seed_lesson(ec_db, verdict, f"2026-08-1{i}T00:00:00+00:00")

    assert len(get_lessons(ec_db, limit=9, min_per_verdict=5)) == 9
    assert get_lessons(ec_db, limit=0, min_per_verdict=5) == []


def test_get_lessons_absent_verdict_forfeits_floor(ec_db):
    """A verdict with no rows must not shrink the result (S3)."""
    for i in range(12):
        _seed_lesson(ec_db, "neutral", f"2026-08-10T00:{i:02d}:00+00:00")

    lessons = get_lessons(ec_db, limit=10, min_per_verdict=5)

    assert len(lessons) == 10
    assert {item["verdict"] for item in lessons} == {"neutral"}


def test_get_lessons_fills_remaining_slots_by_global_recency(ec_db):
    """Non-reserved slots take the globally newest rows, in deterministic order (S4).

    Guards the overflow.sort that makes the fill global rather than
    per-verdict — every other test here passes without it.
    """
    for i in range(6):
        _seed_lesson(ec_db, "expand", f"2026-08-02T00:{i:02d}:00+00:00")
    for i in range(6):
        _seed_lesson(ec_db, "neutral", f"2026-08-03T00:{i:02d}:00+00:00")
    for i in range(6):
        _seed_lesson(ec_db, "narrow", f"2026-08-04T00:{i:02d}:00+00:00")

    lessons = get_lessons(ec_db, limit=12, min_per_verdict=1)

    assert len(lessons) == 12
    stamps = [item["created_at"] for item in lessons]
    assert stamps == sorted(stamps, reverse=True)
    # narrow is newest, so after the 1-per-verdict floors the fill is
    # narrow-then-neutral; no expand row beyond its floor can appear.
    assert len([item for item in lessons if item["verdict"] == "expand"]) == 1


def test_get_lessons_small_limit_caps_floor_budget(ec_db):
    """A small limit stays recency-ordered, not a per-verdict sampler (S5)."""
    for i in range(4):
        _seed_lesson(ec_db, "expand", f"2026-08-01T00:{i:02d}:00+00:00")
    for i in range(4):
        _seed_lesson(ec_db, "neutral", f"2026-08-09T00:{i:02d}:00+00:00")

    lessons = get_lessons(ec_db, limit=3, min_per_verdict=5)

    assert len(lessons) == 3
    # floor budget is limit // 2 == 1, so at most one slot is reserved and
    # the newest rows (neutral) take the rest.
    assert len([item for item in lessons if item["verdict"] == "neutral"]) >= 2


def test_get_lessons_min_per_verdict_zero_is_pure_recency(ec_db):
    """min_per_verdict=0 restores the pre-fix ordering exactly (S6)."""
    for i in range(4):
        _seed_lesson(ec_db, "expand", f"2026-08-01T00:{i:02d}:00+00:00")
    for i in range(4):
        _seed_lesson(ec_db, "neutral", f"2026-08-09T00:{i:02d}:00+00:00")

    lessons = get_lessons(ec_db, limit=4, min_per_verdict=0)

    assert [item["verdict"] for item in lessons] == ["neutral"] * 4


def test_get_lessons_ties_are_ordered_by_id(ec_db):
    """Equal timestamps use the stable id tiebreak (S4)."""
    timestamp = "2026-08-10T00:00:00+00:00"
    for lesson_id in ("lesson-a", "lesson-z"):
        ec_db.execute(
            """INSERT INTO assessments (id, verdict, impact_summary, feedback, created_at)
            VALUES (?, 'neutral', ?, 'agree', ?)""",
            (lesson_id, lesson_id, timestamp),
        )

    lessons = get_lessons(ec_db, limit=2, min_per_verdict=0)

    assert [lesson["id"] for lesson in lessons] == ["lesson-z", "lesson-a"]


def test_get_lessons_keeps_verdict_with_fewer_rows_than_floor(ec_db):
    """A positive shortfall keeps its rows and forfeits unused floor slots (S3)."""
    for i in range(12):
        _seed_lesson(ec_db, "neutral", f"2026-08-10T00:{i:02d}:00+00:00")
    expand_id = _seed_lesson(ec_db, "expand", "2026-08-01T00:00:00+00:00")

    lessons = get_lessons(ec_db, limit=10, min_per_verdict=5)

    assert len(lessons) == 10
    assert expand_id in {lesson["id"] for lesson in lessons}


@pytest.mark.parametrize(("limit", "expected_verdict"), [(1, "neutral"), (2, "neutral")])
def test_get_lessons_limits_below_verdict_count_follow_recency(ec_db, limit, expected_verdict):
    """Limits below the verdict count keep the floor budget bounded (S5)."""
    _seed_lesson(ec_db, "expand", "2026-08-01T00:00:00+00:00")
    _seed_lesson(ec_db, "neutral", "2026-08-10T00:00:00+00:00")

    lessons = get_lessons(ec_db, limit=limit, min_per_verdict=5)

    assert len(lessons) == limit
    assert lessons[0]["verdict"] == expected_verdict


def test_get_lessons_reads_candidates_in_one_statement(ec_db):
    """All verdict partitions share one SQLite snapshot."""
    _seed_lesson(ec_db, "neutral", "2026-08-10T00:00:00+00:00")

    class _CountingConnection:
        def __init__(self, conn):
            self._conn = conn
            self.select_count = 0

        def execute(self, sql, parameters=()):
            if "SELECT * FROM assessments" in sql:
                self.select_count += 1
            return self._conn.execute(sql, parameters)

    counting = _CountingConnection(ec_db)
    get_lessons(counting)

    assert counting.select_count == 1


def test_get_lessons_uses_one_snapshot_across_verdict_partitions(ec_repo):
    """Concurrent enrichment must not duplicate a lesson across verdicts."""
    from entirecontext.db import get_db

    reader = get_db(str(ec_repo))
    writer = get_db(str(ec_repo))
    lesson_id = _seed_lesson(reader, "expand", "2026-08-10T00:00:00+00:00")

    class _InterleavingCursor:
        def __init__(self, cursor):
            self._cursor = cursor

        def fetchall(self):
            rows = self._cursor.fetchall()
            writer.execute(
                "UPDATE assessments SET verdict = 'narrow' WHERE id = ?",
                (lesson_id,),
            )
            return rows

    class _InterleavingConnection:
        def __init__(self, conn):
            self._conn = conn
            self._interleaved = False

        def execute(self, sql, parameters=()):
            cursor = self._conn.execute(sql, parameters)
            if not self._interleaved and "verdict = ?" in sql and parameters and parameters[0] == "expand":
                self._interleaved = True
                return _InterleavingCursor(cursor)
            return cursor

    try:
        lessons = get_lessons(
            _InterleavingConnection(reader),
            limit=10,
            min_per_verdict=5,
        )
    finally:
        writer.close()
        reader.close()

    ids = [lesson["id"] for lesson in lessons]
    assert ids.count(lesson_id) == 1


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


def test_auto_distill_lessons_enabled(ec_repo, monkeypatch):
    """Test that auto_distill=True writes LESSONS.md."""
    from entirecontext.core.config import load_config
    from entirecontext.db import get_db

    monkeypatch.setattr(
        "entirecontext.core.config.load_config",
        lambda repo_path=None: {
            **load_config(repo_path),
            "futures": {"auto_distill": True, "lessons_output": "LESSONS.md"},
        },
    )

    conn = get_db(str(ec_repo))
    a = create_assessment(conn, verdict="expand", impact_summary="Auto distill test")
    add_feedback(conn, a["id"], "agree", feedback_reason="Good")
    conn.close()

    result = auto_distill_lessons(str(ec_repo))
    assert result is True
    output = ec_repo / "LESSONS.md"
    assert output.exists()
    assert "Auto distill test" in output.read_text(encoding="utf-8")


def test_auto_distill_lessons_passes_configured_floor(ec_repo, monkeypatch):
    """Hook-driven distillation must honor the repository floor (S6)."""
    from entirecontext.core.config import load_config

    seen: dict[str, int] = {}

    monkeypatch.setattr(
        "entirecontext.core.config.load_config",
        lambda repo_path=None: {
            **load_config(repo_path),
            "futures": {
                "auto_distill": True,
                "lessons_output": "LESSONS.md",
                "lessons_min_per_verdict": 7,
            },
        },
    )

    def fake_get_lessons(conn, limit=50, *, min_per_verdict=5):
        seen["min_per_verdict"] = min_per_verdict
        return []

    monkeypatch.setattr(
        "entirecontext.core.futures.get_lessons",
        fake_get_lessons,
    )

    assert auto_distill_lessons(str(ec_repo)) is True
    assert seen == {"min_per_verdict": 7}


def test_auto_distill_lessons_disabled(ec_repo, monkeypatch):
    """Test that auto_distill=False does not write LESSONS.md."""
    from entirecontext.core.config import load_config

    monkeypatch.setattr(
        "entirecontext.core.config.load_config",
        lambda repo_path=None: {
            **load_config(repo_path),
            "futures": {"auto_distill": False, "lessons_output": "LESSONS.md"},
        },
    )

    result = auto_distill_lessons(str(ec_repo))
    assert result is False
    assert not (ec_repo / "LESSONS.md").exists()


def test_auto_distill_custom_output(ec_repo, monkeypatch):
    """Test that lessons_output config controls the output path."""
    from entirecontext.core.config import load_config
    from entirecontext.db import get_db

    custom_path = "docs/custom-lessons.md"
    monkeypatch.setattr(
        "entirecontext.core.config.load_config",
        lambda repo_path=None: {
            **load_config(repo_path),
            "futures": {"auto_distill": True, "lessons_output": custom_path},
        },
    )

    conn = get_db(str(ec_repo))
    a = create_assessment(conn, verdict="neutral", impact_summary="Custom output test")
    add_feedback(conn, a["id"], "disagree")
    conn.close()

    (ec_repo / "docs").mkdir(exist_ok=True)
    result = auto_distill_lessons(str(ec_repo))
    assert result is True
    output = ec_repo / custom_path
    assert output.exists()
    assert "Custom output test" in output.read_text(encoding="utf-8")
