"""Tests for decision hooks."""

from __future__ import annotations

import subprocess as _subprocess
from unittest.mock import MagicMock, patch

from entirecontext.core.async_worker import _pid_file, launch_worker, worker_status
from entirecontext.core.config import DEFAULT_CONFIG
from entirecontext.core.decisions import create_decision, get_decision, link_decision_to_file


class TestDecisionConfig:
    def test_decisions_section_exists(self):
        assert "decisions" in DEFAULT_CONFIG

    def test_decisions_defaults_all_off(self):
        decisions = DEFAULT_CONFIG["decisions"]
        assert decisions["auto_stale_check"] is False
        assert decisions["auto_extract"] is False
        assert decisions["show_related_on_start"] is False

    def test_extract_keywords_present(self):
        keywords = DEFAULT_CONFIG["decisions"]["extract_keywords"]
        assert isinstance(keywords, list)
        assert len(keywords) > 0
        assert "decided" in keywords


class TestNamedWorker:
    def test_pid_file_default_name(self, tmp_path):
        result = _pid_file(str(tmp_path))
        assert result == tmp_path / ".entirecontext" / "worker.pid"

    def test_pid_file_custom_name(self, tmp_path):
        result = _pid_file(str(tmp_path), pid_name="worker-decision")
        assert result == tmp_path / ".entirecontext" / "worker-decision.pid"

    def test_launch_worker_custom_pid(self, tmp_path):
        ec_dir = tmp_path / ".entirecontext"
        ec_dir.mkdir()
        with patch("entirecontext.core.async_worker.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc
            pid = launch_worker(str(tmp_path), ["echo", "test"], pid_name="worker-decision")
            assert pid == 12345
            pid_path = ec_dir / "worker-decision.pid"
            assert pid_path.exists()
            assert pid_path.read_text().strip() == "12345"
            assert not (ec_dir / "worker.pid").exists()

    def test_worker_status_custom_pid(self, tmp_path):
        ec_dir = tmp_path / ".entirecontext"
        ec_dir.mkdir()
        status = worker_status(str(tmp_path), pid_name="worker-decision")
        assert status["running"] is False


class TestMaybeCheckStaleDecisions:
    def test_disabled_by_config(self, ec_repo, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_stale_check": False},
        )
        from entirecontext.hooks.decision_hooks import maybe_check_stale_decisions

        maybe_check_stale_decisions(str(ec_repo))

    def test_no_decisions_early_return(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_stale_check": True},
        )
        from entirecontext.hooks.decision_hooks import maybe_check_stale_decisions

        maybe_check_stale_decisions(str(ec_repo))

    def test_stale_detection_updates_status(self, ec_repo, ec_db, monkeypatch):
        import subprocess

        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_stale_check": True},
        )
        d = create_decision(ec_db, title="Test decision")
        test_file = ec_repo / "src" / "app.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("x = 1")
        link_decision_to_file(ec_db, d["id"], "src/app.py")

        subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(ec_repo), "commit", "-m", "change app"],
            check=True, capture_output=True,
        )

        from entirecontext.hooks.decision_hooks import maybe_check_stale_decisions

        maybe_check_stale_decisions(str(ec_repo))

        updated = get_decision(ec_db, d["id"])
        assert updated["staleness_status"] == "stale"

    def test_exception_does_not_propagate(self, ec_repo, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_stale_check": True},
        )

        def _boom(*a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr("entirecontext.core.decisions.list_decisions", _boom)
        from entirecontext.hooks.decision_hooks import maybe_check_stale_decisions

        maybe_check_stale_decisions(str(ec_repo))


class TestOnSessionStartDecisions:
    def test_disabled_by_config(self, ec_repo, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": False},
        )
        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is None

    def test_no_related_decisions_returns_none(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is None

    def test_related_decisions_shown(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        d = create_decision(ec_db, title="Arch decision")
        link_decision_to_file(ec_db, d["id"], "src/app.py")

        test_file = ec_repo / "src" / "app.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("x = 1")
        _subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        _subprocess.run(
            ["git", "-C", str(ec_repo), "commit", "-m", "add app"],
            check=True, capture_output=True,
        )

        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is not None
        assert "Arch decision" in result
        assert "Related Decisions" in result

    def test_stale_decisions_shown(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        create_decision(ec_db, title="Stale one", staleness_status="stale")

        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is not None
        assert "Stale Decisions" in result
        assert "Stale one" in result

    def test_max_5_decisions(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        for i in range(8):
            create_decision(ec_db, title=f"Stale {i}", staleness_status="stale")

        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is not None
        entries = [line for line in result.split("\n") if line.strip().startswith("- [")]
        assert len(entries) <= 5

    def test_git_failure_returns_none(self, ec_repo, ec_db, monkeypatch):
        from unittest.mock import MagicMock
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.subprocess.run",
            lambda *a, **kw: MagicMock(returncode=1, stdout=""),
        )
        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is None
