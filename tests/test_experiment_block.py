"""Verify experiment_block='off' suppresses all 4 proactive surfacing channels."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _decisions_config(block_value: str | None, **overrides) -> dict:
    """Build a decisions sub-dict with experiment_block set."""
    cfg = {
        "show_related_on_start": True,
        "surface_on_tool_use": True,
        "surface_on_user_prompt": True,
        "injection": {
            "inject_on_user_prompt": True,
            "inject_timeout_ms": 250,
            "experiment_block": block_value,
        },
    }
    cfg.update(overrides)
    return cfg


def _full_config(block_value: str | None, **overrides) -> dict:
    """Build a full config dict with experiment_block set."""
    return {
        "capture": {"auto_capture": True},
        "decisions": _decisions_config(block_value, **overrides),
    }


class TestExperimentBlockOff:
    """When experiment_block='off', all 4 channels must produce no output."""

    def test_session_start_suppressed(self, ec_repo, ec_db):
        """Uses the real ec_repo/ec_db fixtures so _find_git_root resolves to
        an actual repo, and seeds a stale decision so the un-suppressed path
        would produce non-None output. Without both, `result is None` would
        pass vacuously — either because there's no git root, or because a
        fresh repo has no decisions to surface regardless of the block."""
        from entirecontext.core.decisions import create_decision
        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        create_decision(ec_db, title="Stale one", staleness_status="stale")

        decisions_cfg = _decisions_config("off")
        with patch("entirecontext.hooks.decision_hooks._load_decisions_config", return_value=decisions_cfg):
            result = on_session_start_decisions({
                "session_id": "test-sess",
                "cwd": str(ec_repo),
            })
        assert result is None

    def test_post_tool_use_suppressed(self):
        """Assert the block fires before any DB query, not merely that the
        result is None (a MagicMock conn could plausibly yield None via an
        unrelated path, e.g. a falsy fetchone masking the real check)."""
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        cfg = _full_config("off")
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.config.load_config", return_value=cfg),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.hooks.decision_hooks._find_ec_repo_root", return_value="/tmp/repo"),
        ):
            result = on_post_tool_use_decisions({
                "session_id": "test-sess",
                "cwd": "/tmp/repo",
                "tool_name": "Write",
                "tool_input": {"file_path": "/tmp/repo/foo.py"},
            })
        assert result is None
        mock_conn.execute.assert_not_called()

    def test_user_prompt_surfacing_suppressed(self, ec_repo, ec_db):
        """surface_on_user_prompt path in turn_capture should not launch worker.

        Uses real ec_repo/ec_db fixtures (real git repo + real SQLite conn,
        per tests/conftest.py) rather than a hand-mocked connection, so the
        function actually runs the surface_on_user_prompt decision point
        instead of returning early on some unrelated mock gap — which would
        make mock_launch.assert_not_called() pass vacuously.
        """
        from entirecontext.core.session import create_session

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id, session_id="test-sess")
        ec_db.commit()

        cfg = _full_config("off")
        with (
            patch("entirecontext.hooks.turn_capture._maybe_launch_prompt_surfacing_worker") as mock_launch,
            patch("entirecontext.core.config.load_config", return_value=cfg),
        ):
            from entirecontext.hooks.turn_capture import on_user_prompt

            on_user_prompt({
                "hook_type": "UserPromptSubmit",
                "session_id": session["id"],
                "cwd": str(ec_repo),
                "prompt": "test",
            })
            mock_launch.assert_not_called()

    def test_sync_pdi_suppressed(self):
        """inject_on_user_prompt path in handler should return 0 via the
        experiment_block short-circuit specifically — not via an incidental
        error further down the call chain (the outer handler swallows all
        exceptions and also returns 0, so `result == 0` alone can't tell
        the two apart). Assert get_db is never reached instead.
        """
        from entirecontext.hooks.handler import _handle_user_prompt

        cfg = _full_config("off")

        with (
            patch("entirecontext.core.config.load_config", return_value=cfg),
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.hooks.turn_capture.on_user_prompt"),
            patch("entirecontext.db.get_db") as mock_get_db,
        ):
            result = _handle_user_prompt({
                "session_id": "test-sess",
                "cwd": "/tmp/repo",
                "prompt": "test",
            })
        assert result == 0
        mock_get_db.assert_not_called()


class TestExperimentBlockOn:
    """When experiment_block='on', channels are NOT force-enabled — per-channel toggles still govern."""

    def test_session_start_respects_own_toggle_when_block_on(self):
        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        decisions_cfg = _decisions_config("on", show_related_on_start=False)
        with patch("entirecontext.hooks.decision_hooks._load_decisions_config", return_value=decisions_cfg):
            result = on_session_start_decisions({
                "session_id": "test-sess",
                "cwd": "/tmp/repo",
            })
        assert result is None


class TestExperimentBlockAbsent:
    """When experiment_block is absent/null, behavior unchanged — block check passes through."""

    def test_session_start_passes_block_check(self):
        from entirecontext.core.config import is_experiment_off

        decisions_cfg = _decisions_config(None)
        assert is_experiment_off(decisions_cfg) is False

    def test_block_on_passes_check(self):
        from entirecontext.core.config import is_experiment_off

        decisions_cfg = _decisions_config("on")
        assert is_experiment_off(decisions_cfg) is False

    def test_block_off_triggers_check(self):
        from entirecontext.core.config import is_experiment_off

        decisions_cfg = _decisions_config("off")
        assert is_experiment_off(decisions_cfg) is True
