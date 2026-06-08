"""Tests for team dashboard — session/checkpoint/assessment stats."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.dashboard import get_dashboard_stats

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _seed_db(ec_repo, ec_db):
    """Seed 2 sessions, 3 checkpoints, 4 assessments."""
    from entirecontext.core.project import get_project
    from entirecontext.core.session import create_session

    project = get_project(str(ec_repo))

    # 2 sessions — one active, one ended
    s1 = create_session(ec_db, project["id"], session_id="dash-s1")
    s2 = create_session(ec_db, project["id"], session_id="dash-s2")
    ec_db.execute("UPDATE sessions SET ended_at = datetime('now') WHERE id = ?", (s2["id"],))
    ec_db.commit()

    # 3 checkpoints
    ec_db.execute(
        """INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch, created_at)
           VALUES ('ckp-1', ?, 'abc123', 'main', datetime('now'))""",
        (s1["id"],),
    )
    ec_db.execute(
        """INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch, created_at)
           VALUES ('ckp-2', ?, 'def456', 'main', datetime('now'))""",
        (s1["id"],),
    )
    ec_db.execute(
        """INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch, created_at)
           VALUES ('ckp-3', ?, 'ghi789', 'feat/x', datetime('now'))""",
        (s2["id"],),
    )
    ec_db.commit()

    # 4 assessments: expand×2, narrow×1, neutral×1; 2 have feedback
    ec_db.execute(
        """INSERT INTO assessments (id, verdict, impact_summary, feedback, created_at)
           VALUES ('asmt-1', 'expand', 'Adds flexibility', 'agree', datetime('now'))"""
    )
    ec_db.execute(
        """INSERT INTO assessments (id, verdict, impact_summary, feedback, created_at)
           VALUES ('asmt-2', 'expand', 'Widens scope', 'disagree', datetime('now'))"""
    )
    ec_db.execute(
        """INSERT INTO assessments (id, verdict, impact_summary, feedback, created_at)
           VALUES ('asmt-3', 'narrow', 'Reduces coupling', NULL, datetime('now'))"""
    )
    ec_db.execute(
        """INSERT INTO assessments (id, verdict, impact_summary, feedback, created_at)
           VALUES ('asmt-4', 'neutral', 'No change', NULL, datetime('now'))"""
    )
    ec_db.commit()

    return {"s1": s1["id"], "s2": s2["id"]}


def _seed_telemetry(ec_db):
    ec_db.execute(
        """INSERT INTO retrieval_events (id, session_id, turn_id, source, search_type, target, query, result_count, latency_ms, created_at)
           VALUES ('re-1', 'dash-s1', NULL, 'cli', 'regex', 'turn', 'auth', 2, 5, datetime('now'))"""
    )
    ec_db.execute(
        """INSERT INTO retrieval_selections (id, retrieval_event_id, session_id, turn_id, result_type, result_id, rank, created_at)
           VALUES ('rs-1', 're-1', 'dash-s1', NULL, 'assessment', 'asmt-1', 1, datetime('now'))"""
    )
    ec_db.execute(
        """INSERT INTO context_applications (id, session_id, turn_id, retrieval_selection_id, source_type, source_id, application_type, created_at)
           VALUES ('ca-1', 'dash-s1', NULL, 'rs-1', 'assessment', 'asmt-1', 'lesson_applied', datetime('now'))"""
    )
    ec_db.commit()


# ---------------------------------------------------------------------------
# TestGetDashboardStats
# ---------------------------------------------------------------------------


class TestGetDashboardStats:
    def test_returns_dict_with_required_keys(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        stats = get_dashboard_stats(ec_db)
        for key in (
            "sessions",
            "checkpoints",
            "assessments",
            "telemetry",
            "maturity_score",
            "maturity_grade",
            "since",
            "limit",
        ):
            assert key in stats

    def test_sessions_total_count(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        stats = get_dashboard_stats(ec_db)
        assert stats["sessions"]["total"] == 2

    def test_sessions_active_ended_counts(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        stats = get_dashboard_stats(ec_db)
        assert stats["sessions"]["active"] == 1
        assert stats["sessions"]["ended"] == 1

    def test_sessions_recent_list_respects_limit(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        stats = get_dashboard_stats(ec_db, limit=1)
        assert len(stats["sessions"]["recent"]) <= 1

    def test_sessions_recent_has_expected_fields(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        stats = get_dashboard_stats(ec_db)
        for s in stats["sessions"]["recent"]:
            for field in ("id", "started_at", "last_activity_at"):
                assert field in s

    def test_checkpoints_total_count(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        stats = get_dashboard_stats(ec_db)
        assert stats["checkpoints"]["total"] == 3

    def test_checkpoints_recent_list_respects_limit(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        stats = get_dashboard_stats(ec_db, limit=2)
        assert len(stats["checkpoints"]["recent"]) <= 2

    def test_checkpoints_recent_has_expected_fields(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        stats = get_dashboard_stats(ec_db)
        for c in stats["checkpoints"]["recent"]:
            for field in ("id", "session_id", "git_commit_hash", "created_at"):
                assert field in c

    def test_assessments_total_count(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        stats = get_dashboard_stats(ec_db)
        assert stats["assessments"]["total"] == 4

    def test_assessments_by_verdict_distribution(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        stats = get_dashboard_stats(ec_db)
        bv = stats["assessments"]["by_verdict"]
        assert bv["expand"] == 2
        assert bv["narrow"] == 1
        assert bv["neutral"] == 1

    def test_assessments_with_feedback_count(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        stats = get_dashboard_stats(ec_db)
        assert stats["assessments"]["with_feedback"] == 2

    def test_assessments_feedback_rate(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        stats = get_dashboard_stats(ec_db)
        assert stats["assessments"]["feedback_rate"] == 0.5

    def test_assessments_feedback_rate_zero_when_empty(self, ec_repo, ec_db):
        # empty DB — no ZeroDivisionError
        stats = get_dashboard_stats(ec_db)
        assert stats["assessments"]["feedback_rate"] == 0.0

    def test_since_filter_excludes_old_sessions(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        # Backdate one session so it falls before the filter
        ec_db.execute(
            "UPDATE sessions SET started_at = '2020-01-01 00:00:00', last_activity_at = '2020-01-01 00:00:00' WHERE id = 'dash-s1'"
        )
        ec_db.commit()
        stats = get_dashboard_stats(ec_db, since="2024-01-01")
        assert stats["sessions"]["total"] == 1

    def test_since_filter_excludes_old_checkpoints(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        ec_db.execute("UPDATE checkpoints SET created_at = '2020-01-01 00:00:00' WHERE id = 'ckp-1'")
        ec_db.commit()
        stats = get_dashboard_stats(ec_db, since="2024-01-01")
        assert stats["checkpoints"]["total"] == 2

    def test_since_filter_excludes_old_assessments(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        ec_db.execute("UPDATE assessments SET created_at = '2020-01-01 00:00:00' WHERE id = 'asmt-1'")
        ec_db.commit()
        stats = get_dashboard_stats(ec_db, since="2024-01-01")
        assert stats["assessments"]["total"] == 3

    def test_empty_db_returns_zero_counts(self, ec_repo, ec_db):
        stats = get_dashboard_stats(ec_db)
        assert stats["sessions"]["total"] == 0
        assert stats["checkpoints"]["total"] == 0
        assert stats["assessments"]["total"] == 0
        assert stats["sessions"]["recent"] == []
        assert stats["checkpoints"]["recent"] == []
        assert stats["assessments"]["recent"] == []

    def test_since_and_limit_echoed_in_result(self, ec_repo, ec_db):
        stats = get_dashboard_stats(ec_db, since="2025-01-01", limit=5)
        assert stats["since"] == "2025-01-01"
        assert stats["limit"] == 5

    def test_enriched_rate(self, ec_repo, ec_db):
        import pytest

        ec_db.execute(
            "INSERT INTO assessments (id, verdict, model_name, created_at) VALUES ('er-1', 'neutral', 'rule-based', datetime('now'))"
        )
        ec_db.execute(
            "INSERT INTO assessments (id, verdict, model_name, created_at) VALUES ('er-2', 'expand', 'gpt-4o-mini', datetime('now'))"
        )
        ec_db.execute(
            "INSERT INTO assessments (id, verdict, model_name, created_at) VALUES ('er-3', 'neutral', 'claude-cli', datetime('now'))"
        )
        ec_db.commit()
        stats = get_dashboard_stats(ec_db)
        assert stats["assessments"]["enriched_count"] == 2
        assert stats["assessments"]["enriched_rate"] == pytest.approx(2 / 3)

    def test_by_verdict_always_has_all_three_keys(self, ec_repo, ec_db):
        # Only expand assessments
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session

        project = get_project(str(ec_repo))
        create_session(ec_db, project["id"], session_id="v-only-sess")
        ec_db.execute(
            "INSERT INTO assessments (id, verdict, impact_summary, created_at) "
            "VALUES ('v-only-1', 'expand', 'test', datetime('now'))"
        )
        ec_db.commit()
        stats = get_dashboard_stats(ec_db)
        bv = stats["assessments"]["by_verdict"]
        assert "expand" in bv
        assert "narrow" in bv
        assert "neutral" in bv
        assert bv["narrow"] == 0
        assert bv["neutral"] == 0

    def test_telemetry_rates(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        _seed_telemetry(ec_db)
        stats = get_dashboard_stats(ec_db)
        assert stats["telemetry"]["retrieval_events"]["total"] == 1
        assert stats["telemetry"]["retrieval_selections"]["total"] == 1
        assert stats["telemetry"]["context_applications"]["with_selection"] == 1
        assert stats["telemetry"]["rates"]["search_to_selection_rate"] == 1.0
        assert stats["telemetry"]["rates"]["applied_context_rate"] == 1.0
        assert stats["telemetry"]["rates"]["lesson_reuse_rate"] == 1.0

    def test_maturity_grade_empty_db(self, ec_repo, ec_db):
        stats = get_dashboard_stats(ec_db)
        assert stats["maturity_score"] == 0
        assert stats["maturity_grade"] == "Absent"

    def test_maturity_grade_partial(self, ec_repo, ec_db):
        _seed_db(ec_repo, ec_db)
        stats = get_dashboard_stats(ec_db)
        assert stats["maturity_score"] >= 25
        assert stats["maturity_grade"] == "Partial"

    def test_retrieval_rate_excludes_active_sessions(self, ec_repo, ec_db):
        from uuid import uuid4

        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session

        project = get_project(str(ec_repo))

        s1 = create_session(ec_db, project["id"], session_id="ret-s1")
        s2 = create_session(ec_db, project["id"], session_id="ret-s2")
        _s3 = create_session(ec_db, project["id"], session_id="ret-s3")  # noqa: F841

        # End s1 and s2, leave s3 active
        ec_db.execute("UPDATE sessions SET ended_at = datetime('now') WHERE id = ?", (s1["id"],))
        ec_db.execute("UPDATE sessions SET ended_at = datetime('now') WHERE id = ?", (s2["id"],))
        ec_db.commit()

        # Retrieval event only in ended session s1
        ec_db.execute(
            "INSERT INTO retrieval_events (id, session_id, source, search_type, target, query, created_at)"
            " VALUES (?, ?, 'hook', 'regex', 'turn', 'test', datetime('now'))",
            (str(uuid4()), s1["id"]),
        )
        ec_db.commit()

        stats = get_dashboard_stats(ec_db)
        # 1 retrieval session / 2 ended sessions = 0.5 (NOT 1/3)
        assert stats["telemetry"]["rates"]["retrieval_assisted_session_rate"] == 0.5

    def test_retrieval_rate_since_filter_consistent(self, ec_repo, ec_db):
        """Numerator and denominator must use same session window when since is set."""
        from datetime import datetime, timedelta, timezone
        from uuid import uuid4

        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session

        project = get_project(str(ec_repo))

        old_time = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        new_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        # Old session (outside since window) with recent retrieval event
        s_old = create_session(ec_db, project["id"], session_id="old-s1")
        ec_db.execute(
            "UPDATE sessions SET started_at = ?, ended_at = ? WHERE id = ?",
            (old_time, old_time, s_old["id"]),
        )
        ec_db.execute(
            "INSERT INTO retrieval_events (id, session_id, source, search_type, target, query, created_at)"
            " VALUES (?, ?, 'hook', 'regex', 'turn', 'test', datetime('now'))",
            (str(uuid4()), s_old["id"]),
        )

        # New session (inside since window), no retrieval
        s_new = create_session(ec_db, project["id"], session_id="new-s1")
        ec_db.execute(
            "UPDATE sessions SET started_at = ?, ended_at = ? WHERE id = ?",
            (new_time, new_time, s_new["id"]),
        )
        ec_db.commit()

        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        stats = get_dashboard_stats(ec_db, since=since)

        # Old session should NOT appear in numerator despite recent retrieval event
        assert stats["telemetry"]["rates"]["retrieval_assisted_session_rate"] == 0.0

    def test_search_to_selection_rate_uses_distinct_events(self, ec_repo, ec_db):
        """Rate = DISTINCT events with >=1 selection / total events, so max 1.0."""
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session

        project = get_project(str(ec_repo))
        s1 = create_session(ec_db, project["id"], session_id="dist-s1")
        ec_db.execute("UPDATE sessions SET ended_at = datetime('now') WHERE id = ?", (s1["id"],))
        ec_db.commit()

        # Event 1: 3 selections
        ec_db.execute(
            "INSERT INTO retrieval_events (id, session_id, source, search_type, target, query, created_at)"
            " VALUES ('dist-re1', ?, 'hook', 'regex', 'turn', 'q1', datetime('now'))",
            (s1["id"],),
        )
        for i in range(3):
            ec_db.execute(
                "INSERT INTO retrieval_selections (id, retrieval_event_id, session_id, result_type, result_id, rank, created_at)"
                f" VALUES ('dist-rs{i}', 'dist-re1', ?, 'turn', 'turn-{i}', {i + 1}, datetime('now'))",
                (s1["id"],),
            )

        # Event 2: 0 selections
        ec_db.execute(
            "INSERT INTO retrieval_events (id, session_id, source, search_type, target, query, created_at)"
            " VALUES ('dist-re2', ?, 'hook', 'regex', 'turn', 'q2', datetime('now'))",
            (s1["id"],),
        )
        ec_db.commit()

        stats = get_dashboard_stats(ec_db)
        rate = stats["telemetry"]["rates"]["search_to_selection_rate"]
        # 1 DISTINCT event with selection / 2 total events = 0.5, NOT 3/2 = 1.5
        assert rate == 0.5

    def test_all_rate_metrics_in_valid_range(self, ec_repo, ec_db):
        """All _rate metrics must stay in [0, 1]."""
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session

        project = get_project(str(ec_repo))
        s1 = create_session(ec_db, project["id"], session_id="guard-s1")
        ec_db.execute("UPDATE sessions SET ended_at = datetime('now') WHERE id = ?", (s1["id"],))
        ec_db.commit()

        # 1 event with 10 selections
        ec_db.execute(
            "INSERT INTO retrieval_events (id, session_id, source, search_type, target, query, created_at)"
            " VALUES ('guard-re1', ?, 'hook', 'regex', 'turn', 'q', datetime('now'))",
            (s1["id"],),
        )
        for i in range(10):
            ec_db.execute(
                "INSERT INTO retrieval_selections (id, retrieval_event_id, session_id, result_type, result_id, rank, created_at)"
                f" VALUES ('guard-rs{i}', 'guard-re1', ?, 'turn', 'turn-{i}', {i + 1}, datetime('now'))",
                (s1["id"],),
            )
        ec_db.commit()

        stats = get_dashboard_stats(ec_db)
        rates = stats["telemetry"]["rates"]
        for key, value in rates.items():
            if key.endswith("_rate"):
                assert 0.0 <= value <= 1.0, f"{key} = {value} is outside [0, 1]"

    def test_retrieval_rate_ignores_active_session_retrieval(self, ec_repo, ec_db):
        from uuid import uuid4

        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session

        project = get_project(str(ec_repo))

        s1 = create_session(ec_db, project["id"], session_id="ret2-s1")
        s2 = create_session(ec_db, project["id"], session_id="ret2-s2")

        # End s1 (no retrieval), leave s2 active (with retrieval)
        ec_db.execute("UPDATE sessions SET ended_at = datetime('now') WHERE id = ?", (s1["id"],))
        ec_db.commit()

        # Retrieval event in active session s2
        ec_db.execute(
            "INSERT INTO retrieval_events (id, session_id, source, search_type, target, query, created_at)"
            " VALUES (?, ?, 'hook', 'regex', 'turn', 'test', datetime('now'))",
            (str(uuid4()), s2["id"]),
        )
        ec_db.commit()

        stats = get_dashboard_stats(ec_db)
        # Active session's retrieval must NOT count in numerator
        assert stats["telemetry"]["rates"]["retrieval_assisted_session_rate"] == 0.0


# ---------------------------------------------------------------------------
# TestDashboardCLI
# ---------------------------------------------------------------------------


def _mock_stats() -> dict:
    return {
        "sessions": {
            "total": 2,
            "active": 1,
            "ended": 1,
            "avg_turns_per_session": 2.0,
            "recent": [
                {
                    "id": "sess-aaa",
                    "session_title": "Test session",
                    "started_at": "2026-01-01 10:00:00",
                    "last_activity_at": "2026-01-01 11:00:00",
                    "ended_at": None,
                }
            ],
        },
        "checkpoints": {
            "total": 1,
            "changed_ended_sessions": 1,
            "changed_ended_sessions_with_checkpoints": 1,
            "checkpoint_coverage_rate": 1.0,
            "recent": [
                {
                    "id": "ckp-aaa",
                    "session_id": "sess-aaa",
                    "git_branch": "main",
                    "git_commit_hash": "abc12345",
                    "created_at": "2026-01-01 10:30:00",
                }
            ],
        },
        "assessments": {
            "total": 3,
            "by_verdict": {"expand": 2, "narrow": 1, "neutral": 0},
            "with_feedback": 1,
            "feedback_rate": 0.33,
            "with_checkpoint": 1,
            "checkpoint_anchored_assessment_rate": 0.33,
            "recent": [
                {
                    "id": "asmt-aaa",
                    "verdict": "expand",
                    "impact_summary": "Adds flexibility",
                    "feedback": "agree",
                    "created_at": "2026-01-01 10:00:00",
                }
            ],
        },
        "telemetry": {
            "retrieval_events": {"total": 2, "sessions_with_retrieval": 1},
            "retrieval_selections": {"total": 1},
            "context_applications": {"total": 1, "with_selection": 1},
            "rates": {
                "retrieval_assisted_session_rate": 0.5,
                "search_to_selection_rate": 0.5,
                "applied_context_rate": 1.0,
                "lesson_reuse_rate": 1.0,
                "checkpoint_anchored_assessment_rate": 0.33,
                "turns_with_files_rate": 0.5,
            },
        },
        "maturity_breakdown": {"capture": 10, "distill": 18, "retrieve": 13, "intervene": 20},
        "maturity_score": 61,
        "maturity_grade": "Operational",
        "since": None,
        "limit": 10,
    }


class TestDashboardCLI:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["dashboard"])
        assert result.exit_code == 1

    def test_basic_output_renders(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.dashboard.get_dashboard_stats", return_value=_mock_stats()),
        ):
            result = runner.invoke(app, ["dashboard"])
        assert result.exit_code == 0
        # Should contain session or numeric output
        assert "session" in result.output.lower() or "2" in result.output
        assert "Dogfooding Maturity" in result.output
        assert "Telemetry" in result.output

    def test_empty_stats_renders_without_error(self):
        mock_conn = MagicMock()
        empty = {
            "sessions": {"total": 0, "active": 0, "ended": 0, "recent": [], "avg_turns_per_session": 0.0},
            "checkpoints": {
                "total": 0,
                "recent": [],
                "changed_ended_sessions": 0,
                "changed_ended_sessions_with_checkpoints": 0,
                "checkpoint_coverage_rate": 0.0,
            },
            "assessments": {
                "total": 0,
                "by_verdict": {"expand": 0, "narrow": 0, "neutral": 0},
                "with_feedback": 0,
                "feedback_rate": 0.0,
                "with_checkpoint": 0,
                "checkpoint_anchored_assessment_rate": 0.0,
                "recent": [],
            },
            "telemetry": {
                "retrieval_events": {"total": 0, "sessions_with_retrieval": 0},
                "retrieval_selections": {"total": 0},
                "context_applications": {"total": 0, "with_selection": 0},
                "rates": {
                    "retrieval_assisted_session_rate": 0.0,
                    "search_to_selection_rate": 0.0,
                    "applied_context_rate": 0.0,
                    "lesson_reuse_rate": 0.0,
                    "checkpoint_anchored_assessment_rate": 0.0,
                    "turns_with_files_rate": 0.0,
                },
            },
            "maturity_breakdown": {"capture": 0, "distill": 0, "retrieve": 0, "intervene": 0},
            "maturity_score": 0,
            "maturity_grade": "Absent",
            "since": None,
            "limit": 10,
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.dashboard.get_dashboard_stats", return_value=empty),
        ):
            result = runner.invoke(app, ["dashboard"])
        assert result.exit_code == 0

    def test_since_option_passed_to_core(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.dashboard.get_dashboard_stats", return_value=_mock_stats()) as mock_fn,
        ):
            runner.invoke(app, ["dashboard", "--since", "2025-01-01"])
        assert mock_fn.call_args.kwargs.get("since") == "2025-01-01"

    def test_limit_option_passed_to_core(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.dashboard.get_dashboard_stats", return_value=_mock_stats()) as mock_fn,
        ):
            runner.invoke(app, ["dashboard", "--limit", "5"])
        assert mock_fn.call_args.kwargs.get("limit") == 5

    def test_default_limit_is_10(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.dashboard.get_dashboard_stats", return_value=_mock_stats()) as mock_fn,
        ):
            runner.invoke(app, ["dashboard"])
        assert mock_fn.call_args.kwargs.get("limit") == 10
