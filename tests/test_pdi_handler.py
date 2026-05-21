"""E5: PDI sync path tests for _handle_user_prompt (PR-E E5).

Covers:
  (a) sync success → stdout JSON format verified
  (b) sync empty result → no stdout (async fallback separate)
  (c) sync exception → stderr only, no raise
  (d) inject_on_user_prompt=false → no PDI output
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from entirecontext.hooks.handler import _handle_user_prompt


_HOOK_DATA = {
    "hook_type": "UserPromptSubmit",
    "session_id": "sess-test-001",
    "cwd": "/tmp/repo",
    "prompt": "why did we choose SQLite over Postgres?",
}

_FAKE_DECISION = {
    "id": "aabbccdd-1234-5678-abcd-ef0123456789",
    "title": "SQLite over Postgres for embedded agent memory",
    "rationale": "Zero-config, no server process, portable across environments.",
    "staleness_status": "fresh",
    "score": 0.82,
    "rank": 1,
}

_INJECTION_CONFIG = {
    "decisions": {
        "injection": {
            "inject_on_user_prompt": True,
            "top_k": 5,
            "max_tokens": 800,
            "min_confidence": 0.4,
            "inject_timeout_ms": 250,
        }
    }
}

_NO_INJECT_CONFIG = {
    "decisions": {
        "injection": {
            "inject_on_user_prompt": False,
        }
    }
}


class TestPDIHandlerSyncPath:
    def test_sync_success_outputs_json_to_stdout(self, capsys):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.hooks.turn_capture.on_user_prompt"),
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.core.config.load_config", return_value=_INJECTION_CONFIG),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch(
                "entirecontext.core.decision_prompt_surfacing.rank_decisions_for_prompt",
                return_value=([_FAKE_DECISION], []),
            ),
            patch(
                "entirecontext.core.decision_prompt_surfacing.optimize_for_context_budget",
                return_value=[_FAKE_DECISION],
            ),
        ):
            result = _handle_user_prompt(_HOOK_DATA)

        assert result == 0
        captured = capsys.readouterr()
        assert captured.out.strip(), "Expected JSON output on stdout"
        payload = json.loads(captured.out.strip())
        assert "hookSpecificOutput" in payload
        hook_out = payload["hookSpecificOutput"]
        assert hook_out["hookEventName"] == "UserPromptSubmit"
        assert "additionalContext" in hook_out
        assert "SQLite over Postgres" in hook_out["additionalContext"]

    def test_sync_empty_result_no_stdout(self, capsys):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.hooks.turn_capture.on_user_prompt"),
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.core.config.load_config", return_value=_INJECTION_CONFIG),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch(
                "entirecontext.core.decision_prompt_surfacing.rank_decisions_for_prompt",
                return_value=([], []),
            ),
            patch(
                "entirecontext.core.decision_prompt_surfacing.optimize_for_context_budget",
                return_value=[],
            ),
        ):
            result = _handle_user_prompt(_HOOK_DATA)

        assert result == 0
        captured = capsys.readouterr()
        assert not captured.out.strip(), "Expected no stdout when no decisions matched"

    def test_sync_exception_goes_to_stderr_only(self, capsys):
        with (
            patch("entirecontext.hooks.turn_capture.on_user_prompt"),
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.core.config.load_config", return_value=_INJECTION_CONFIG),
            patch("entirecontext.db.get_db", side_effect=RuntimeError("db exploded")),
        ):
            result = _handle_user_prompt(_HOOK_DATA)

        assert result == 0
        captured = capsys.readouterr()
        assert not captured.out.strip(), "No stdout on exception"
        assert "PDI error" in captured.err

    def test_inject_disabled_skips_pdi(self, capsys):
        with (
            patch("entirecontext.hooks.turn_capture.on_user_prompt"),
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.core.config.load_config", return_value=_NO_INJECT_CONFIG),
            patch("entirecontext.core.decision_prompt_surfacing.rank_decisions_for_prompt") as mock_rank,
        ):
            result = _handle_user_prompt(_HOOK_DATA)

        assert result == 0
        mock_rank.assert_not_called()
        captured = capsys.readouterr()
        assert not captured.out.strip()

    def test_no_session_id_skips_pdi(self, capsys):
        data = {**_HOOK_DATA, "session_id": None}
        with (
            patch("entirecontext.hooks.turn_capture.on_user_prompt"),
            patch("entirecontext.core.decision_prompt_surfacing.rank_decisions_for_prompt") as mock_rank,
        ):
            result = _handle_user_prompt(data)

        assert result == 0
        mock_rank.assert_not_called()

    def test_inject_timeout_skips_pdi(self, capsys):
        import time

        def _slow_rank(*args, **kwargs):
            time.sleep(0.5)
            return ([_FAKE_DECISION], [])

        config = {
            "decisions": {
                "injection": {
                    "inject_on_user_prompt": True,
                    "top_k": 5,
                    "max_tokens": 800,
                    "min_confidence": 0.4,
                    "inject_timeout_ms": 50,
                }
            }
        }
        with (
            patch("entirecontext.hooks.turn_capture.on_user_prompt"),
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.core.config.load_config", return_value=config),
            patch("entirecontext.db.get_db"),
            patch(
                "entirecontext.core.decision_prompt_surfacing.rank_decisions_for_prompt",
                side_effect=_slow_rank,
            ),
        ):
            result = _handle_user_prompt(_HOOK_DATA)

        assert result == 0
        captured = capsys.readouterr()
        assert not captured.out.strip(), "Timeout must suppress PDI output"

    def test_capture_disabled_skips_pdi(self, capsys):
        config_no_capture = {
            "capture": {"auto_capture": False},
            "decisions": {
                "injection": {
                    "inject_on_user_prompt": True,
                }
            },
        }
        with (
            patch("entirecontext.hooks.turn_capture.on_user_prompt"),
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.core.config.load_config", return_value=config_no_capture),
            patch("entirecontext.core.decision_prompt_surfacing.rank_decisions_for_prompt") as mock_rank,
        ):
            result = _handle_user_prompt(_HOOK_DATA)

        assert result == 0
        mock_rank.assert_not_called()
        captured = capsys.readouterr()
        assert not captured.out.strip()

    def test_stdout_json_contains_decision_id(self, capsys):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.hooks.turn_capture.on_user_prompt"),
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.core.config.load_config", return_value=_INJECTION_CONFIG),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch(
                "entirecontext.core.decision_prompt_surfacing.rank_decisions_for_prompt",
                return_value=([_FAKE_DECISION], []),
            ),
            patch(
                "entirecontext.core.decision_prompt_surfacing.optimize_for_context_budget",
                return_value=[_FAKE_DECISION],
            ),
        ):
            _handle_user_prompt(_HOOK_DATA)

        captured = capsys.readouterr()
        payload = json.loads(captured.out.strip())
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        assert "aabbccdd" in ctx, "Expected decision ID prefix in additionalContext"

    def test_session_capture_disabled_skips_pdi(self, capsys):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (
            '{"capture_disabled": true}',
        )
        with (
            patch("entirecontext.hooks.turn_capture.on_user_prompt"),
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.core.config.load_config", return_value=_INJECTION_CONFIG),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.decision_prompt_surfacing.rank_decisions_for_prompt") as mock_rank,
        ):
            result = _handle_user_prompt(_HOOK_DATA)

        assert result == 0
        mock_rank.assert_not_called()
        captured = capsys.readouterr()
        assert not captured.out.strip()

    def test_on_user_prompt_receives_pre_resolved_repo_path(self):
        """handler.py resolves git root once and forwards it to on_user_prompt."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        captured_kwargs: list[dict] = []

        def _capture_call(data, **kwargs):
            captured_kwargs.append(kwargs)

        with (
            patch("entirecontext.hooks.turn_capture.on_user_prompt", side_effect=_capture_call),
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo") as mock_find,
            patch("entirecontext.core.config.load_config", return_value=_INJECTION_CONFIG),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch(
                "entirecontext.core.decision_prompt_surfacing.rank_decisions_for_prompt",
                return_value=([], []),
            ),
        ):
            _handle_user_prompt(_HOOK_DATA)

        # find_git_root called exactly once — not twice
        assert mock_find.call_count == 1
        # pre-resolved path forwarded via _resolved_repo_path kwarg
        assert captured_kwargs[0].get("_resolved_repo_path") == "/tmp/repo"
