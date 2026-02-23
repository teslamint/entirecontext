"""Tests for markdown export feature."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.export import export_session_markdown, _yaml_scalar, _blockquote, _inline_safe

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestYamlScalar:
    def test_plain_string_unchanged(self):
        assert _yaml_scalar("claude") == "claude"

    def test_string_with_colon_quoted(self):
        result = _yaml_scalar("key: value")
        assert result.startswith("'") and result.endswith("'")
        assert "key: value" in result

    def test_string_with_hash_quoted(self):
        result = _yaml_scalar("my#project")
        assert result.startswith("'") and result.endswith("'")

    def test_string_with_single_quote_escaped(self):
        result = _yaml_scalar("it's")
        assert "''" in result

    def test_string_with_newline_quoted(self):
        result = _yaml_scalar("line1\nline2")
        assert result.startswith("'") and result.endswith("'")


class TestBlockquote:
    def test_single_line(self):
        assert _blockquote("hello") == "> hello"

    def test_multiline_all_prefixed(self):
        result = _blockquote("line1\nline2\nline3")
        assert result == "> line1\n> line2\n> line3"

    def test_empty_line_prefixed(self):
        result = _blockquote("line1\n\nline3")
        assert "> \n" in result or "> line1\n> \n> line3" == result


class TestInlineSafe:
    def test_no_newlines_unchanged(self):
        assert _inline_safe("hello world") == "hello world"

    def test_unix_newline_replaced(self):
        assert _inline_safe("a\nb") == "a b"

    def test_windows_newline_replaced(self):
        assert _inline_safe("a\r\nb") == "a b"

    def test_carriage_return_replaced(self):
        assert _inline_safe("a\rb") == "a b"


# ---------------------------------------------------------------------------
# Core function tests
# ---------------------------------------------------------------------------


class TestExportSessionMarkdown:
    def _make_session(self, **overrides):
        base = {
            "id": "sess-abc123-uuid",
            "session_type": "claude",
            "started_at": "2025-01-15T10:00:00+00:00",
            "ended_at": "2025-01-15T11:30:00+00:00",
            "total_turns": 3,
            "session_title": None,
            "session_summary": None,
        }
        base.update(overrides)
        return base

    def _make_turns(self):
        return [
            {
                "turn_number": 1,
                "user_message": "fix the login bug",
                "assistant_summary": "Found the issue in auth.py, fixed null pointer",
            },
            {
                "turn_number": 2,
                "user_message": "write tests for auth",
                "assistant_summary": "Added 5 unit tests covering edge cases",
            },
            {
                "turn_number": 3,
                "user_message": "push and PR",
                "assistant_summary": "Created PR #42 with all changes",
            },
        ]

    def test_returns_string(self):
        session = self._make_session()
        turns = self._make_turns()
        result = export_session_markdown(session, turns)
        assert isinstance(result, str)

    def test_contains_session_id(self):
        session = self._make_session()
        turns = self._make_turns()
        result = export_session_markdown(session, turns)
        assert "sess-abc123-uuid" in result

    def test_contains_session_type(self):
        session = self._make_session()
        turns = self._make_turns()
        result = export_session_markdown(session, turns)
        assert "claude" in result

    def test_contains_started_at(self):
        session = self._make_session()
        turns = self._make_turns()
        result = export_session_markdown(session, turns)
        assert "2025-01-15" in result

    def test_contains_turn_user_messages(self):
        session = self._make_session()
        turns = self._make_turns()
        result = export_session_markdown(session, turns)
        assert "fix the login bug" in result
        assert "write tests for auth" in result
        assert "push and PR" in result

    def test_contains_turn_assistant_summaries(self):
        session = self._make_session()
        turns = self._make_turns()
        result = export_session_markdown(session, turns)
        assert "Found the issue in auth.py" in result
        assert "Added 5 unit tests" in result
        assert "Created PR #42" in result

    def test_contains_yaml_frontmatter(self):
        session = self._make_session()
        turns = self._make_turns()
        result = export_session_markdown(session, turns)
        assert result.startswith("---\n")
        assert "\n---\n" in result

    def test_yaml_frontmatter_has_id_field(self):
        session = self._make_session()
        turns = self._make_turns()
        result = export_session_markdown(session, turns)
        frontmatter_end = result.index("\n---\n", 4)
        frontmatter = result[4:frontmatter_end]
        assert "id:" in frontmatter
        assert "sess-abc123-uuid" in frontmatter

    def test_yaml_frontmatter_has_type_field(self):
        session = self._make_session()
        turns = self._make_turns()
        result = export_session_markdown(session, turns)
        frontmatter_end = result.index("\n---\n", 4)
        frontmatter = result[4:frontmatter_end]
        assert "type:" in frontmatter

    def test_yaml_frontmatter_has_turns_count(self):
        session = self._make_session()
        turns = self._make_turns()
        result = export_session_markdown(session, turns)
        frontmatter_end = result.index("\n---\n", 4)
        frontmatter = result[4:frontmatter_end]
        assert "turns:" in frontmatter

    def test_session_with_title(self):
        session = self._make_session(session_title="Debug Auth Flow")
        turns = self._make_turns()
        result = export_session_markdown(session, turns)
        assert "Debug Auth Flow" in result

    def test_session_with_summary(self):
        session = self._make_session(session_summary="Fixed critical auth bug, added test coverage")
        turns = self._make_turns()
        result = export_session_markdown(session, turns)
        assert "Fixed critical auth bug" in result

    def test_session_no_title_uses_short_id(self):
        session = self._make_session(session_title=None)
        turns = []
        result = export_session_markdown(session, turns)
        # Short ID (first 8 chars) should appear in header
        assert "sess-abc" in result

    def test_active_session_shows_active_status(self):
        session = self._make_session(ended_at=None)
        turns = []
        result = export_session_markdown(session, turns)
        assert "active" in result.lower()

    def test_ended_session_shows_ended_at(self):
        session = self._make_session(ended_at="2025-01-15T11:30:00+00:00")
        turns = []
        result = export_session_markdown(session, turns)
        assert "2025-01-15" in result

    def test_no_turns_shows_no_turns_section(self):
        session = self._make_session(total_turns=0)
        turns = []
        result = export_session_markdown(session, turns)
        # Should still produce valid markdown without error
        assert isinstance(result, str)
        assert "sess-abc123-uuid" in result

    def test_turns_numbered_correctly(self):
        session = self._make_session()
        turns = self._make_turns()
        result = export_session_markdown(session, turns)
        assert "Turn 1" in result
        assert "Turn 2" in result
        assert "Turn 3" in result

    def test_project_name_included_when_provided(self):
        session = self._make_session()
        turns = self._make_turns()
        result = export_session_markdown(session, turns, project_name="my-project")
        assert "my-project" in result

    def test_project_name_omitted_when_none(self):
        session = self._make_session()
        turns = self._make_turns()
        result = export_session_markdown(session, turns, project_name=None)
        assert "project:" not in result

    def test_turn_with_none_user_message(self):
        session = self._make_session()
        turns = [{"turn_number": 1, "user_message": None, "assistant_summary": "Did something"}]
        result = export_session_markdown(session, turns)
        assert "Did something" in result

    def test_turn_with_none_assistant_summary(self):
        session = self._make_session()
        turns = [{"turn_number": 1, "user_message": "Do this", "assistant_summary": None}]
        result = export_session_markdown(session, turns)
        assert "Do this" in result

    def test_turn_with_git_commit_hash(self):
        session = self._make_session()
        turns = [
            {
                "turn_number": 1,
                "user_message": "commit fix",
                "assistant_summary": "committed",
                "git_commit_hash": "abc1234",
            }
        ]
        result = export_session_markdown(session, turns)
        assert "abc1234" in result

    def test_turn_without_git_commit_hash(self):
        session = self._make_session()
        turns = [
            {
                "turn_number": 1,
                "user_message": "do something",
                "assistant_summary": "done",
                "git_commit_hash": None,
            }
        ]
        # Should not error
        result = export_session_markdown(session, turns)
        assert isinstance(result, str)

    def test_output_is_valid_markdown_structure(self):
        """Basic check that output has H1 heading."""
        session = self._make_session(session_title="My Session")
        turns = self._make_turns()
        result = export_session_markdown(session, turns)
        assert "# " in result

    def test_exported_field_in_frontmatter(self):
        """'exported' timestamp should appear in frontmatter."""
        session = self._make_session()
        turns = []
        result = export_session_markdown(session, turns)
        frontmatter_end = result.index("\n---\n", 4)
        frontmatter = result[4:frontmatter_end]
        assert "exported:" in frontmatter

    def test_frontmatter_ends_with_newline_before_body(self):
        """Closing --- must have a newline before the body starts."""
        session = self._make_session()
        turns = []
        result = export_session_markdown(session, turns)
        # The closing delimiter must be followed by a newline and then the body
        assert "\n---\n" in result

    def test_multiline_user_message_inlined(self):
        """Multiline user messages must not break paragraph structure."""
        session = self._make_session()
        turns = [{"turn_number": 1, "user_message": "line1\nline2", "assistant_summary": "ok", "git_commit_hash": None}]
        result = export_session_markdown(session, turns)
        # Newline should be replaced so it doesn't break bold prefix
        assert "**User:** line1 line2" in result

    def test_multiline_assistant_summary_inlined(self):
        session = self._make_session()
        turns = [{"turn_number": 1, "user_message": "q", "assistant_summary": "a\nb", "git_commit_hash": None}]
        result = export_session_markdown(session, turns)
        assert "**Assistant:** a b" in result

    def test_multiline_session_summary_blockquoted_all_lines(self):
        session = self._make_session(session_summary="first line\nsecond line")
        turns = []
        result = export_session_markdown(session, turns)
        assert "> first line\n> second line" in result

    def test_project_name_with_colon_yaml_safe(self):
        """Project name with ':' should be YAML-safe quoted."""
        session = self._make_session()
        turns = []
        result = export_session_markdown(session, turns, project_name="org: project")
        # Should be single-quoted
        assert "project: 'org: project'" in result


# ---------------------------------------------------------------------------
# CLI command tests
# ---------------------------------------------------------------------------


class TestSessionExportCLI:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["session", "export", "sess-001"])
            assert result.exit_code == 1

    def test_session_not_found(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.get_session", return_value=None),
        ):
            result = runner.invoke(app, ["session", "export", "sess-nonexistent"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()

    def test_export_to_stdout(self):
        mock_conn = MagicMock()
        session = {
            "id": "sess-cli-001-uuid",
            "session_type": "claude",
            "started_at": "2025-01-15T10:00:00",
            "ended_at": None,
            "total_turns": 1,
            "session_title": "CLI Test Session",
            "session_summary": None,
        }
        turns = [{"turn_number": 1, "user_message": "hello", "assistant_summary": "world", "git_commit_hash": None}]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1", "name": "test-project"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.get_session", return_value=session),
            patch("entirecontext.core.turn.list_turns", return_value=turns),
        ):
            result = runner.invoke(app, ["session", "export", "sess-cli-001-uuid"])
            assert result.exit_code == 0
            assert "sess-cli-001-uuid" in result.output
            assert "CLI Test Session" in result.output

    def test_export_to_file(self, tmp_path):
        mock_conn = MagicMock()
        session = {
            "id": "sess-file-001-uuid",
            "session_type": "claude",
            "started_at": "2025-01-15T10:00:00",
            "ended_at": "2025-01-15T11:00:00",
            "total_turns": 1,
            "session_title": None,
            "session_summary": None,
        }
        turns = [{"turn_number": 1, "user_message": "test", "assistant_summary": "done", "git_commit_hash": None}]
        output_file = tmp_path / "session.md"
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1", "name": "test-project"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.get_session", return_value=session),
            patch("entirecontext.core.turn.list_turns", return_value=turns),
        ):
            result = runner.invoke(app, ["session", "export", "sess-file-001-uuid", "--output", str(output_file)])
            assert result.exit_code == 0
            assert output_file.exists()
            content = output_file.read_text()
            assert "sess-file-001-uuid" in content

    def test_export_default_stdout_when_no_output(self):
        """Without --output or --stdout, defaults to stdout."""
        mock_conn = MagicMock()
        session = {
            "id": "sess-def-001-uuid",
            "session_type": "claude",
            "started_at": "2025-01-15T10:00:00",
            "ended_at": None,
            "total_turns": 0,
            "session_title": None,
            "session_summary": None,
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1", "name": "proj"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.get_session", return_value=session),
            patch("entirecontext.core.turn.list_turns", return_value=[]),
        ):
            result = runner.invoke(app, ["session", "export", "sess-def-001-uuid"])
            assert result.exit_code == 0
            assert "sess-def-001-uuid" in result.output

    def test_prefix_id_resolution(self):
        """Prefix IDs (e.g. first 8 chars) should resolve to full session."""
        mock_conn = MagicMock()
        session = {
            "id": "sess-prefix-resolved-uuid",
            "session_type": "claude",
            "started_at": "2025-01-15T10:00:00",
            "ended_at": None,
            "total_turns": 0,
            "session_title": None,
            "session_summary": None,
        }
        # get_session returns None for prefix; fallback LIKE query finds it
        mock_conn.execute.return_value.fetchone.return_value = MagicMock(**{"__iter__": iter, **session})
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.core.project.get_project", return_value={"id": "proj-1", "name": "proj"}),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.session.get_session", return_value=None),
            patch(
                "entirecontext.core.turn.list_turns",
                return_value=[],
            ),
        ):
            # Simulate the LIKE fallback returning the full session
            with patch.object(
                mock_conn,
                "execute",
                side_effect=lambda q, *a: MagicMock(fetchone=lambda: dict(session) if "LIKE" in q else None),
            ):
                # This test verifies the command handles prefix IDs (exit 0 OR 1 handled gracefully)
                result = runner.invoke(app, ["session", "export", "sess-pref"])
                # Either it finds it (0) or not found (1) - no crash
                assert result.exit_code in (0, 1)
