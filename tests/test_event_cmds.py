"""Tests for event management commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestEventList:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["event", "list"])
            assert result.exit_code == 1

    def test_empty_list(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.event.list_events", return_value=[]),
        ):
            result = runner.invoke(app, ["event", "list"])
            assert result.exit_code == 0
            assert "No events found" in result.output

    def test_normal_list(self):
        mock_conn = MagicMock()
        events = [
            {
                "id": "evt-abc123456789",
                "title": "Fix login bug",
                "event_type": "task",
                "status": "active",
                "created_at": "2025-01-01T00:00:00",
            },
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.event.list_events", return_value=events),
        ):
            result = runner.invoke(app, ["event", "list"])
            assert result.exit_code == 0
            assert "Events" in result.output

    def test_global_list(self):
        events = [
            {
                "id": "evt-abc123456789",
                "repo_name": "myrepo",
                "title": "Fix login bug",
                "event_type": "task",
                "status": "active",
                "created_at": "2025-01-01T00:00:00",
            },
        ]
        with patch("entirecontext.core.cross_repo.cross_repo_events", return_value=(events, [])):
            result = runner.invoke(app, ["event", "list", "--global"])
            assert result.exit_code == 0
            assert "Events" in result.output

    def test_global_list_empty(self):
        with patch("entirecontext.core.cross_repo.cross_repo_events", return_value=([], [])):
            result = runner.invoke(app, ["event", "list", "--global"])
            assert result.exit_code == 0
            assert "No events found" in result.output


class TestEventShow:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["event", "show", "evt-123"])
            assert result.exit_code == 1

    def test_not_found(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.event.get_event", return_value=None),
        ):
            result = runner.invoke(app, ["event", "show", "evt-notexist"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()

    def test_normal_show(self):
        mock_conn = MagicMock()
        event = {
            "id": "evt-abc123456789",
            "title": "Fix login bug",
            "event_type": "task",
            "status": "active",
            "created_at": "2025-01-01T00:00:00",
            "description": "Login form crashes on submit",
        }
        sessions = [
            {
                "id": "sess-123456789abc",
                "session_type": "claude",
                "ended_at": None,
            },
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.event.get_event", return_value=event),
            patch("entirecontext.core.event.get_event_sessions", return_value=sessions),
        ):
            result = runner.invoke(app, ["event", "show", "evt-abc123456789"])
            assert result.exit_code == 0
            assert "Event" in result.output
            assert "Linked Sessions" in result.output


class TestEventCreate:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["event", "create", "My Event"])
            assert result.exit_code == 1

    def test_invalid_type(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch(
                "entirecontext.core.event.create_event",
                side_effect=ValueError("Invalid event type: badtype"),
            ),
        ):
            result = runner.invoke(app, ["event", "create", "My Event", "--type", "badtype"])
            assert result.exit_code == 1
            assert "Invalid event type" in result.output

    def test_success(self):
        mock_conn = MagicMock()
        created = {"id": "evt-new123456789"}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.event.create_event", return_value=created),
        ):
            result = runner.invoke(app, ["event", "create", "My Event"])
            assert result.exit_code == 0
            assert "Created event" in result.output


class TestEventLink:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["event", "link", "evt-1", "sess-1"])
            assert result.exit_code == 1

    def test_event_not_found(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.event.get_event", return_value=None),
        ):
            result = runner.invoke(app, ["event", "link", "evt-notexist", "sess-1"])
            assert result.exit_code == 1
            assert "Event not found" in result.output

    def test_session_not_found(self):
        mock_conn = MagicMock()
        event = {"id": "evt-123"}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.event.get_event", return_value=event),
            patch("entirecontext.core.session.get_session", return_value=None),
        ):
            result = runner.invoke(app, ["event", "link", "evt-123", "sess-notexist"])
            assert result.exit_code == 1
            assert "Session not found" in result.output

    def test_success(self):
        mock_conn = MagicMock()
        event = {"id": "evt-123456789abc"}
        session = {"id": "sess-123456789abc"}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.event.get_event", return_value=event),
            patch("entirecontext.core.session.get_session", return_value=session),
            patch("entirecontext.core.event.link_event_session") as mock_link,
        ):
            result = runner.invoke(app, ["event", "link", "evt-123456789abc", "sess-123456789abc"])
            assert result.exit_code == 0
            assert "Linked" in result.output
            mock_link.assert_called_once_with(mock_conn, "evt-123456789abc", "sess-123456789abc")
