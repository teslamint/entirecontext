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


class TestCodexNotify:
    def test_codex_notify_argv_payload(self):
        with patch("entirecontext.hooks.codex_ingest.ingest_codex_notify_event") as mock_ingest:
            result = runner.invoke(app, ["hook", "codex-notify", '{"thread_id":"t1","cwd":"/tmp"}'])
            assert result.exit_code == 0
            mock_ingest.assert_called_once()
            payload = mock_ingest.call_args.kwargs.get("payload", mock_ingest.call_args.args[0])
            assert payload["thread_id"] == "t1"

    def test_codex_notify_stdin_payload(self):
        with patch("entirecontext.hooks.codex_ingest.ingest_codex_notify_event") as mock_ingest:
            result = runner.invoke(app, ["hook", "codex-notify"], input='{"thread_id":"t2"}')
            assert result.exit_code == 0
            mock_ingest.assert_called_once()
