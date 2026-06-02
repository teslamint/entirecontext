"""Tests for hook commands."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

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

    def test_codex_notify_argv_skips_stdin(self):
        """When payload_arg is provided, stdin must not be read (prevents blocking on open pipes)."""
        import threading

        call_completed = threading.Event()

        def run_in_thread():
            with patch("entirecontext.hooks.codex_ingest.ingest_codex_notify_event"):
                runner.invoke(
                    app,
                    ["hook", "codex-notify", '{"thread_id":"t3","cwd":"/tmp"}'],
                    input=None,
                )
                call_completed.set()

        t = threading.Thread(target=run_in_thread, daemon=True)
        t.start()
        completed = call_completed.wait(timeout=5)
        assert completed, "codex-notify blocked on stdin despite payload_arg being provided"


class TestCodexNotifyStdinFallback:
    """Tests for the stdin fallback path (no payload_arg), exercising select/os.read/JSON validation."""

    @staticmethod
    def _make_monotonic(step=0.001):
        counter = [0]

        def fake():
            counter[0] += 1
            return counter[0] * step

        return fake

    @staticmethod
    def _make_stdin_mock(fd=99):
        m = MagicMock()
        m.fileno.return_value = fd
        return m

    def test_chunked_json_reassembly(self):
        """Loop breaks on valid JSON, not EOF — os.read called exactly N chunks, not N+1."""
        chunks = iter([b'{"thread_id":', b'"t5","cwd":', b'"/tmp"}'])
        mock_stdin = self._make_stdin_mock()

        with (
            patch("entirecontext.hooks.codex_ingest.ingest_codex_notify_event") as mock_ingest,
            patch("select.select", return_value=([99], [], [])) as mock_select,
            patch("os.read", side_effect=lambda fd, sz: next(chunks, b"")) as mock_read,
            patch("time.monotonic", side_effect=self._make_monotonic()),
            patch.object(sys, "stdin", mock_stdin),
        ):
            from entirecontext.cli.hook_cmds import codex_notify

            codex_notify(payload_arg=None)

            assert mock_ingest.call_args[0][0] == {"thread_id": "t5", "cwd": "/tmp"}
            assert mock_read.call_count == 3, "should stop after valid JSON, not read to EOF (would be 4)"
            assert mock_select.call_count == 3, "one select per chunk, no extra iterations"

    def test_no_data_exits_without_blocking(self):
        """First select timeout with empty chunks breaks immediately — exactly 1 select call."""
        mock_stdin = self._make_stdin_mock()

        with (
            patch("entirecontext.hooks.codex_ingest.ingest_codex_notify_event") as mock_ingest,
            patch("select.select", return_value=([], [], [])) as mock_select,
            patch("time.monotonic", side_effect=self._make_monotonic()),
            patch.object(sys, "stdin", mock_stdin),
        ):
            from entirecontext.cli.hook_cmds import codex_notify

            codex_notify(payload_arg=None)

            assert mock_ingest.call_args[0][0] == {}
            assert mock_select.call_count == 1, "should break on first timeout, not loop to deadline"

    def test_idle_deadline_resets_on_chunk(self):
        """Without idle reset, chunk2 at t=6 would be lost (original deadline=5). With reset, both read."""
        chunks = iter([b'{"cwd":', b'"/tmp"}'])

        # chunk1 at t=2 resets idle_deadline from 5→7; chunk2 at t=6 (past 5, within 7)
        # Without reset: remaining at t=6 = 5-6 = -1 → break before reading chunk2
        mono_values = [0, 0, 2, 2, 4, 6, 6]
        mono_idx = [0]

        def fake_monotonic():
            idx = min(mono_idx[0], len(mono_values) - 1)
            mono_idx[0] += 1
            return mono_values[idx]

        select_calls = [0]

        def fake_select(rlist, wlist, xlist, timeout=None):
            select_calls[0] += 1
            if select_calls[0] in (1, 3):
                return (rlist, [], [])
            return ([], [], [])

        mock_stdin = self._make_stdin_mock()

        with (
            patch("entirecontext.hooks.codex_ingest.ingest_codex_notify_event") as mock_ingest,
            patch("select.select", side_effect=fake_select) as mock_select,
            patch("os.read", side_effect=lambda fd, sz: next(chunks, b"")) as mock_read,
            patch("time.monotonic", side_effect=fake_monotonic),
            patch.object(sys, "stdin", mock_stdin),
        ):
            from entirecontext.cli.hook_cmds import codex_notify

            codex_notify(payload_arg=None)

            assert mock_ingest.call_args[0][0] == {"cwd": "/tmp"}
            assert mock_read.call_count == 2, "both chunks read — idle reset prevented early break"
            assert mock_select.call_count == 3, "ready(chunk1), not-ready(gap), ready(chunk2)"

    def test_eof_stops_reading(self):
        """os.read returning b'' (EOF) stops the loop after exactly 1 select + 1 read."""
        mock_stdin = self._make_stdin_mock()

        with (
            patch("entirecontext.hooks.codex_ingest.ingest_codex_notify_event") as mock_ingest,
            patch("select.select", return_value=([99], [], [])) as mock_select,
            patch("os.read", return_value=b"") as mock_read,
            patch("time.monotonic", side_effect=self._make_monotonic()),
            patch.object(sys, "stdin", mock_stdin),
        ):
            from entirecontext.cli.hook_cmds import codex_notify

            codex_notify(payload_arg=None)

            assert mock_ingest.call_args[0][0] == {}
            assert mock_select.call_count == 1
            assert mock_read.call_count == 1
