"""Tests for hook commands."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestHookHandle:
    def test_with_type_flag(self):
        with patch("entirecontext.hooks.handler.handle_hook", return_value=0) as mock_handle:
            result = runner.invoke(app, ["hook", "handle", "--type", "SessionStart"], input="{}")
            assert result.exit_code == 0
            mock_handle.assert_called_once()
            assert mock_handle.call_args[0][0] == "SessionStart"

    def test_stdin_json_with_hook_type(self):
        with patch("entirecontext.hooks.handler.handle_hook", return_value=0) as mock_handle:
            result = runner.invoke(
                app,
                ["hook", "handle"],
                input='{"hook_type": "Stop", "session_id": "s1"}',
            )
            assert result.exit_code == 0
            mock_handle.assert_called_once()
            assert mock_handle.call_args[0][0] == "Stop"

    def test_empty_stdin(self):
        with patch("entirecontext.hooks.handler.handle_hook", return_value=0) as mock_handle:
            result = runner.invoke(app, ["hook", "handle", "--type", "SessionEnd"], input="")
            assert result.exit_code == 0
            mock_handle.assert_called_once()

    def test_nonzero_exit_code(self):
        with patch("entirecontext.hooks.handler.handle_hook", return_value=2):
            result = runner.invoke(app, ["hook", "handle", "--type", "UserPromptSubmit"], input="{}")
            assert result.exit_code == 2
