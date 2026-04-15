"""Tests for hook handler dispatch and error paths."""

from __future__ import annotations

import io
import sys
from unittest.mock import MagicMock, patch

import pytest

from entirecontext.hooks.handler import handle_hook, read_stdin_json


class TestReadStdinJson:
    def test_empty_stdin(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        assert read_stdin_json() == {}

    def test_malformed_json(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
        assert read_stdin_json() == {}

    def test_valid_json(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO('{"hook_type": "SessionStart"}'))
        assert read_stdin_json() == {"hook_type": "SessionStart"}


class TestHandleHook:
    def test_unknown_hook_type(self):
        assert handle_hook("UnknownType", data={}) == 0

    def test_dispatches_session_start(self):
        mock_handler = MagicMock(return_value=0)
        data = {"cwd": "."}
        with patch("entirecontext.hooks.handler._handle_session_start", mock_handler):
            result = handle_hook("SessionStart", data=data)
        mock_handler.assert_called_once_with(data)
        assert result == 0

    @pytest.mark.parametrize(
        "hook_type,handler_name",
        [
            ("SessionStart", "_handle_session_start"),
            ("UserPromptSubmit", "_handle_user_prompt"),
            ("Stop", "_handle_stop"),
            ("PostToolUse", "_handle_tool_use"),
            ("SessionEnd", "_handle_session_end"),
            ("PostCommit", "_handle_post_commit"),
        ],
    )
    def test_dispatches_all_types(self, hook_type, handler_name):
        mock_handler = MagicMock(return_value=0)
        data = {"cwd": "."}
        with patch(f"entirecontext.hooks.handler.{handler_name}", mock_handler):
            result = handle_hook(hook_type, data=data)
        mock_handler.assert_called_once_with(data)
        assert result == 0

    def test_exception_records_telemetry(self):
        mock_handler = MagicMock(side_effect=RuntimeError("boom"))
        mock_conn = MagicMock()
        mock_context = MagicMock()
        mock_context.conn = mock_conn
        mock_context.current_session_id = None

        with (
            patch("entirecontext.hooks.handler._handle_session_start", mock_handler),
            patch("entirecontext.hooks.handler.RepoContext.from_cwd", return_value=mock_context),
            patch("entirecontext.core.telemetry.record_operation_event") as mock_record,
        ):
            result = handle_hook("SessionStart", data={"cwd": "/tmp"})

        assert result == 0
        mock_record.assert_called_once_with(
            mock_conn,
            source="hook",
            operation_name="handle_hook",
            phase="SessionStart",
            status="warning",
            error_class="RuntimeError",
            message="boom",
            session_id=None,
            turn_id=None,
        )
        mock_context.__exit__.assert_called_once()

    def test_exception_prints_to_stderr(self, capsys):
        mock_handler = MagicMock(side_effect=RuntimeError("crash"))

        with (
            patch("entirecontext.hooks.handler._handle_session_start", mock_handler),
            patch("entirecontext.hooks.handler.RepoContext.from_cwd", return_value=None),
        ):
            result = handle_hook("SessionStart", data={"cwd": "."})

        assert result == 0
        captured = capsys.readouterr()
        assert "EntireContext hook error (SessionStart): crash" in captured.err
