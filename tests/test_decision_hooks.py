"""Tests for decision hooks."""

from __future__ import annotations

import json
import subprocess as _subprocess
from unittest.mock import MagicMock, patch

from entirecontext.core.async_worker import _pid_file, launch_worker, worker_status
from entirecontext.core.config import DEFAULT_CONFIG
from entirecontext.core.decisions import create_decision, get_decision, link_decision_to_file, list_decisions
from entirecontext.core.session import create_session
from entirecontext.core.turn import create_turn


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
            check=True,
            capture_output=True,
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
            check=True,
            capture_output=True,
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

    def test_session_start_excludes_contradicted_decisions(self, ec_repo, ec_db, monkeypatch):
        """Issue #39 regression: contradicted decisions must not appear in session-start output."""
        from entirecontext.core.decisions import update_decision_staleness

        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        good = create_decision(ec_db, title="Good choice")
        bad = create_decision(ec_db, title="Contradicted choice")
        link_decision_to_file(ec_db, good["id"], "src/handler.py")
        link_decision_to_file(ec_db, bad["id"], "src/handler.py")
        update_decision_staleness(ec_db, bad["id"], "contradicted")

        test_file = ec_repo / "src" / "handler.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("x = 1")
        _subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        _subprocess.run(
            ["git", "-C", str(ec_repo), "commit", "-m", "add handler"],
            check=True,
            capture_output=True,
        )

        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is not None
        assert "Good choice" in result
        assert "Contradicted choice" not in result

    def test_session_start_surfaces_successor_for_superseded(self, ec_repo, ec_db, monkeypatch):
        """Superseded decisions are replaced by their terminal successor in session-start output."""
        from entirecontext.core.decisions import supersede_decision

        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        old = create_decision(ec_db, title="Original auth decision")
        new = create_decision(ec_db, title="Updated auth decision")
        link_decision_to_file(ec_db, old["id"], "src/auth.py")
        link_decision_to_file(ec_db, new["id"], "src/auth.py")
        supersede_decision(ec_db, old["id"], new["id"])

        test_file = ec_repo / "src" / "auth.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("x = 1")
        _subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        _subprocess.run(
            ["git", "-C", str(ec_repo), "commit", "-m", "add auth"],
            check=True,
            capture_output=True,
        )

        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is not None
        assert "Updated auth decision" in result
        assert "Original auth decision" not in result


class TestMaybeExtractDecisions:
    def _setup_session_with_summaries(self, ec_db, summaries):
        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id)
        for i, summary in enumerate(summaries):
            turn = create_turn(ec_db, session["id"], i + 1, user_message=f"msg {i}")
            ec_db.execute(
                "UPDATE turns SET assistant_summary = ?, turn_status = 'completed' WHERE id = ?",
                (summary, turn["id"]),
            )
        ec_db.commit()
        return session

    def test_disabled_by_config(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_extract": False, "extract_keywords": ["decided"]},
        )
        from entirecontext.hooks.decision_hooks import maybe_extract_decisions

        maybe_extract_decisions(str(ec_repo), "fake-session-id")

    def test_no_keyword_matches_no_worker(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_extract": True, "extract_keywords": ["decided"]},
        )
        session = self._setup_session_with_summaries(ec_db, ["just a normal conversation"])
        launched = []
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.launch_worker",
            lambda *a, **kw: launched.append(1) or 0,
        )
        from entirecontext.hooks.decision_hooks import maybe_extract_decisions

        maybe_extract_decisions(str(ec_repo), session["id"])
        assert len(launched) == 0

    def test_keyword_match_launches_worker(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_extract": True, "extract_keywords": ["decided"]},
        )
        session = self._setup_session_with_summaries(ec_db, ["We decided to use Redis"])
        launched = []
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.launch_worker",
            lambda *a, **kw: launched.append(kw) or 0,
        )
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.worker_status",
            lambda *a, **kw: {"running": False, "pid": None},
        )
        from entirecontext.hooks.decision_hooks import maybe_extract_decisions

        maybe_extract_decisions(str(ec_repo), session["id"])
        assert len(launched) == 1

    def test_worker_already_running_skips(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_extract": True, "extract_keywords": ["decided"]},
        )
        session = self._setup_session_with_summaries(ec_db, ["We decided to use Redis"])
        launched = []
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.launch_worker",
            lambda *a, **kw: launched.append(1) or 0,
        )
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.worker_status",
            lambda *a, **kw: {"running": True, "pid": 999},
        )
        from entirecontext.hooks.decision_hooks import maybe_extract_decisions

        maybe_extract_decisions(str(ec_repo), session["id"])
        assert len(launched) == 0

    def test_idempotency_marker_skips(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_extract": True, "extract_keywords": ["decided"]},
        )
        session = self._setup_session_with_summaries(ec_db, ["We decided to use Redis"])
        ec_db.execute(
            "UPDATE sessions SET metadata = ? WHERE id = ?",
            (json.dumps({"decisions_extracted": True}), session["id"]),
        )
        ec_db.commit()
        launched = []
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.launch_worker",
            lambda *a, **kw: launched.append(1) or 0,
        )
        from entirecontext.hooks.decision_hooks import maybe_extract_decisions

        maybe_extract_decisions(str(ec_repo), session["id"])
        assert len(launched) == 0


class TestExtractFromSessionCLI:
    def _setup_session_with_turns(self, ec_db, turn_data):
        """Helper: create session with turns. turn_data = [(summary, files_touched), ...]"""
        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id)
        for i, (summary, files) in enumerate(turn_data):
            turn = create_turn(ec_db, session["id"], i + 1, user_message=f"msg {i}")
            ec_db.execute(
                "UPDATE turns SET assistant_summary = ?, files_touched = ?, turn_status = 'completed' WHERE id = ?",
                (summary, json.dumps(files) if files else None, turn["id"]),
            )
        ec_db.commit()
        return session

    def test_creates_decisions_from_llm_response(self, ec_repo, ec_db, monkeypatch):
        session = self._setup_session_with_turns(
            ec_db,
            [
                ("We decided to use Redis for caching", ["src/cache.py"]),
            ],
        )
        llm_response = json.dumps(
            [
                {
                    "title": "Use Redis for caching",
                    "rationale": "Fast in-memory store",
                    "scope": "caching",
                    "rejected_alternatives": ["memcached"],
                },
            ]
        )
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: llm_response,
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))

        decisions = list_decisions(ec_db)
        titles = [d["title"] for d in decisions]
        assert "Use Redis for caching" in titles

        row = ec_db.execute("SELECT metadata FROM sessions WHERE id = ?", (session["id"],)).fetchone()
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        assert meta.get("decisions_extracted") is True

    def test_auto_links_files(self, ec_repo, ec_db, monkeypatch):
        session = self._setup_session_with_turns(
            ec_db,
            [
                ("We decided to use Redis", ["src/cache.py", "src/config.py"]),
            ],
        )
        llm_response = json.dumps(
            [
                {"title": "Use Redis", "rationale": "Fast", "scope": "cache", "rejected_alternatives": []},
            ]
        )
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: llm_response,
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))

        decisions = list_decisions(ec_db)
        d = get_decision(ec_db, decisions[0]["id"])
        assert "src/cache.py" in d.get("files", [])

    def test_empty_array_sets_marker(self, ec_repo, ec_db, monkeypatch):
        session = self._setup_session_with_turns(
            ec_db,
            [
                ("We decided nothing", []),
            ],
        )
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: "[]",
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))

        row = ec_db.execute("SELECT metadata FROM sessions WHERE id = ?", (session["id"],)).fetchone()
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        assert meta.get("decisions_extracted") is True

    def test_invalid_json_no_marker(self, ec_repo, ec_db, monkeypatch):
        session = self._setup_session_with_turns(
            ec_db,
            [
                ("We decided something", []),
            ],
        )
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: "not json at all",
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))

        row = ec_db.execute("SELECT metadata FROM sessions WHERE id = ?", (session["id"],)).fetchone()
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        assert meta.get("decisions_extracted") is not True

    def test_max_5_decisions(self, ec_repo, ec_db, monkeypatch):
        session = self._setup_session_with_turns(
            ec_db,
            [
                ("Many decisions decided", []),
            ],
        )
        llm_response = json.dumps(
            [{"title": f"Decision {i}", "rationale": "r", "scope": "s", "rejected_alternatives": []} for i in range(8)]
        )
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: llm_response,
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))

        decisions = list_decisions(ec_db)
        assert len(decisions) <= 5

    def test_idempotency_second_run_skips(self, ec_repo, ec_db, monkeypatch):
        session = self._setup_session_with_turns(
            ec_db,
            [
                ("We decided X", []),
            ],
        )
        call_count = []
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: (call_count.append(1), "[]")[1],
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))
        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))
        assert len(call_count) == 1


class TestHandlerIntegration:
    def test_session_start_prints_decisions(self, ec_repo, ec_db, monkeypatch, capsys):
        """Verify _handle_session_start prints decision context to stdout."""
        create_decision(ec_db, title="Integration test decision", staleness_status="stale")
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )

        from entirecontext.hooks.handler import _handle_session_start

        _handle_session_start({"cwd": str(ec_repo), "session_id": "test-session"})
        captured = capsys.readouterr()
        assert "Integration test decision" in captured.out

    def test_session_end_calls_decision_hooks(self, ec_repo, ec_db, monkeypatch, isolated_global_db):
        from entirecontext.core.session import create_session

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id)
        stale_called = []
        extract_called = []
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.maybe_check_stale_decisions",
            lambda rp: stale_called.append(rp),
        )
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.maybe_extract_decisions",
            lambda rp, sid: extract_called.append((rp, sid)),
        )
        from entirecontext.hooks.handler import _handle_session_end

        _handle_session_end({"cwd": str(ec_repo), "session_id": session["id"]})
        assert len(stale_called) == 1
        assert len(extract_called) == 1


class TestStdoutContract:
    def test_handler_prints_decision_context(self, ec_repo, ec_db, monkeypatch, capsys):
        """Verify _handle_session_start actually prints decision text to stdout."""
        create_decision(ec_db, title="Stdout test decision", staleness_status="stale")
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        from entirecontext.hooks.handler import _handle_session_start

        _handle_session_start({"cwd": str(ec_repo), "session_id": "stdout-test"})
        captured = capsys.readouterr()
        assert "Stdout test decision" in captured.out

    def test_fallback_file_written(self, ec_repo, ec_db, monkeypatch):
        """Verify fallback file is written alongside stdout."""
        create_decision(ec_db, title="Fallback test decision", staleness_status="stale")
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "fb-test"})
        assert result is not None

        from pathlib import Path

        fallback_path = Path(str(ec_repo)) / ".entirecontext" / "decisions-context.md"
        assert fallback_path.exists()
        content = fallback_path.read_text(encoding="utf-8")
        assert "Fallback test decision" in content

    def test_fallback_file_cleaned_when_no_decisions(self, ec_repo, ec_db, monkeypatch):
        """Verify fallback file is removed when there are no decisions to show."""
        from pathlib import Path

        fallback_path = Path(str(ec_repo)) / ".entirecontext" / "decisions-context.md"
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        fallback_path.write_text("old content")

        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "cleanup-test"})
        assert result is None
        assert not fallback_path.exists()
