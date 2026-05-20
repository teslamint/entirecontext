"""Tests for session commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestSessionList:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["session", "list"])
            assert result.exit_code == 1

    def test_not_initialized(self):
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value=None),
        ):
            result = runner.invoke(app, ["session", "list"])
            assert result.exit_code == 1
            assert "init" in result.output.lower()

    def test_empty_sessions(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.list_sessions", return_value=[]),
        ):
            result = runner.invoke(app, ["session", "list"])
            assert result.exit_code == 0
            assert "No sessions found" in result.output

    def test_normal_list(self):
        mock_conn = MagicMock()
        sessions = [
            {
                "id": "sess-001-uuid12",
                "session_type": "claude",
                "started_at": "2025-01-01T10:00:00",
                "ended_at": None,
                "total_turns": 5,
            },
            {
                "id": "sess-002-uuid12",
                "session_type": "manual",
                "started_at": "2025-01-02T10:00:00",
                "ended_at": "2025-01-02T11:00:00",
                "total_turns": 3,
            },
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.list_sessions", return_value=sessions),
        ):
            result = runner.invoke(app, ["session", "list"])
            assert result.exit_code == 0
            assert "sess-001-uui" in result.output
            assert "sess-002-uui" in result.output

    def test_global_list(self):
        sessions = [
            {
                "id": "sess-g01-uuid1",
                "repo_name": "repo-a",
                "session_type": "claude",
                "started_at": "2025-01-01",
                "ended_at": None,
                "total_turns": 10,
            }
        ]
        with patch("entirecontext.core.cross_repo.cross_repo_sessions", return_value=sessions) as mock_cross:
            result = runner.invoke(app, ["session", "list", "--global"])
            assert result.exit_code == 0
            mock_cross.assert_called_once()
            assert "repo-a" in result.output


class TestSessionShow:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["session", "show", "sess-001"])
            assert result.exit_code == 1

    def test_not_found(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.get_session", return_value=None),
        ):
            result = runner.invoke(app, ["session", "show", "sess-nonexistent"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()

    def test_normal_with_turns(self):
        mock_conn = MagicMock()
        session = {
            "id": "sess-show-001-uuid",
            "session_type": "claude",
            "started_at": "2025-01-01T10:00:00",
            "ended_at": None,
            "total_turns": 2,
            "session_title": "Debug Session",
            "session_summary": "Fixed auth bug",
        }
        turns = [
            {"turn_number": 1, "user_message": "fix the login bug", "assistant_summary": "found the issue"},
            {"turn_number": 2, "user_message": "test it", "assistant_summary": "all tests pass"},
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.get_session", return_value=session),
            patch("entirecontext.core.turn.list_turns", return_value=turns),
        ):
            result = runner.invoke(app, ["session", "show", "sess-show-001-uuid"])
            assert result.exit_code == 0
            assert "Debug Session" in result.output
            assert "fix the login bug" in result.output
            assert "all tests pass" in result.output

    def test_global_show(self):
        session = {
            "id": "sess-g-show-001",
            "repo_name": "repo-b",
            "session_type": "claude",
            "started_at": "2025-01-01",
            "ended_at": None,
            "total_turns": 1,
            "session_title": "Global Session",
            "session_summary": None,
            "turns": [
                {"turn_number": 1, "user_message": "hello", "assistant_summary": "hi"},
            ],
        }
        with patch(
            "entirecontext.core.cross_repo.cross_repo_session_detail",
            return_value=(session, []),
        ):
            result = runner.invoke(app, ["session", "show", "sess-g-show-001", "--global"])
            assert result.exit_code == 0
            assert "repo-b" in result.output
            assert "Global Session" in result.output

    def test_global_show_not_found(self):
        with patch(
            "entirecontext.core.cross_repo.cross_repo_session_detail",
            return_value=(None, []),
        ):
            result = runner.invoke(app, ["session", "show", "nonexistent", "--global"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()


class TestSessionBackfillEndedAt:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["session", "backfill-ended-at"])
            assert result.exit_code == 1

    def test_not_initialized(self):
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value=None),
        ):
            result = runner.invoke(app, ["session", "backfill-ended-at"])
            assert result.exit_code == 1
            assert "init" in result.output.lower()

    def test_no_eligible_rows(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
        ):
            result = runner.invoke(app, ["session", "backfill-ended-at"])
            assert result.exit_code == 0
            assert "No eligible" in result.output

    def test_dry_run_shows_rows_without_update(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {"id": "sess-old-001-uuid", "last_activity_at": "2025-01-01T09:00:00"},
            {"id": "sess-old-002-uuid", "last_activity_at": "2025-01-02T10:00:00"},
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
        ):
            result = runner.invoke(app, ["session", "backfill-ended-at"])
            assert result.exit_code == 0
            assert "sess-old-001" in result.output
            assert "2 row(s) eligible" in result.output
            assert "Dry-run" in result.output
            mock_conn.commit.assert_not_called()

    def test_apply_updates_eligible_rows(self):
        mock_conn = MagicMock()
        eligible = [
            {"id": "sess-old-001-uuid", "last_activity_at": "2025-01-01T09:00:00"},
        ]
        mock_conn.execute.return_value.fetchall.return_value = eligible
        mock_conn.execute.return_value.rowcount = 1
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
        ):
            result = runner.invoke(app, ["session", "backfill-ended-at", "--apply"])
            assert result.exit_code == 0
            assert "Updated 1 session(s)" in result.output
            mock_conn.commit.assert_called_once()

    def test_recent_rows_not_eligible(self):
        """Rows younger than max_age_hours must not appear (SQL enforces this; mock verifies query param)."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
        ):
            result = runner.invoke(app, ["session", "backfill-ended-at", "--max-age-hours", "2"])
            assert result.exit_code == 0
            call_args = mock_conn.execute.call_args
            assert "-2 hours" in call_args[0][1]

    def test_max_age_hours_zero_rejected(self):
        result = runner.invoke(app, ["session", "backfill-ended-at", "--max-age-hours", "0"])
        assert result.exit_code != 0

    def test_max_age_hours_negative_rejected(self):
        result = runner.invoke(app, ["session", "backfill-ended-at", "--max-age-hours", "-5"])
        assert result.exit_code != 0

    def test_apply_skips_concurrent_modification(self):
        """UPDATE WHERE re-checks ended_at IS NULL and last_activity_at; rowcount=0 = skipped."""
        mock_conn = MagicMock()
        eligible = [
            {"id": "sess-001-uuid", "last_activity_at": "2025-01-01T09:00:00"},
            {"id": "sess-002-uuid", "last_activity_at": "2025-01-02T10:00:00"},
        ]
        select_cursor = MagicMock()
        select_cursor.fetchall.return_value = eligible
        update_cursor = MagicMock()
        update_cursor.rowcount = 0
        mock_conn.execute.side_effect = [select_cursor, update_cursor, update_cursor]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
        ):
            result = runner.invoke(app, ["session", "backfill-ended-at", "--apply"])
            assert result.exit_code == 0
            assert "Updated 0 session(s)" in result.output
            assert "2 skipped" in result.output


class TestSessionCurrent:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["session", "current"])
            assert result.exit_code == 1

    def test_no_active_session(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.get_current_session", return_value=None),
        ):
            result = runner.invoke(app, ["session", "current"])
            assert result.exit_code == 0
            assert "No active session" in result.output

    def test_active_session(self):
        mock_conn = MagicMock()
        session = {
            "id": "sess-active-001",
            "started_at": "2025-01-01T10:00:00",
            "total_turns": 7,
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.get_current_session", return_value=session),
        ):
            result = runner.invoke(app, ["session", "current"])
            assert result.exit_code == 0
            assert "sess-active-001" in result.output
