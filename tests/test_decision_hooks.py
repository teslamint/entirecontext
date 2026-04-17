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
        from entirecontext.core.project import get_project

        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        d = create_decision(ec_db, title="Arch decision")
        link_decision_to_file(ec_db, d["id"], "src/app.py")

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="s1-telemetry")

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

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": session["id"]})
        assert result is not None
        assert "Arch decision" in result
        assert "Related Decisions" in result

        events = ec_db.execute(
            "SELECT COUNT(*) AS n FROM retrieval_events WHERE search_type = 'session_start'"
        ).fetchone()["n"]
        assert events == 1

        selections = ec_db.execute(
            "SELECT COUNT(*) AS n FROM retrieval_selections WHERE result_type = 'decision'"
        ).fetchone()["n"]
        assert selections >= 1

        assert "Selection:" in result

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

    def test_session_start_ranker_respects_display_limit(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )

        changed_files = [f"src/file_{i}.py" for i in range(8)]
        for i, file_path in enumerate(changed_files):
            decision = create_decision(ec_db, title=f"Decision {i}")
            link_decision_to_file(ec_db, decision["id"], file_path)

        monkeypatch.setattr("entirecontext.hooks.decision_hooks._get_recently_changed_files", lambda _: changed_files)

        from entirecontext.core.decisions import rank_related_decisions as core_ranker

        ranker_calls: list[dict] = []

        def spy_ranker(conn, **kwargs):
            ranker_calls.append(kwargs)
            return core_ranker(conn, **kwargs)

        monkeypatch.setattr("entirecontext.core.decisions.rank_related_decisions", spy_ranker)

        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})

        assert result is not None
        assert len(ranker_calls) == 1
        assert ranker_calls[0]["limit"] == 5
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

    def test_session_start_hot_file_with_many_contradicted_still_surfaces_fresh(self, ec_repo, ec_db, monkeypatch):
        """When a hot file has many contradicted decisions, a fresh decision
        must still surface — rank_related_decisions excludes contradicted
        entries via include_contradicted=False so they cannot suppress valid
        guidance.
        """
        from entirecontext.core.decisions import update_decision_staleness

        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )

        hot_file = "src/hot.py"
        # Create 15 contradicted decisions linked to the hot file — more than
        # the list_decisions limit (10). Without SQL-side filtering, these
        # would fill the bucket first and crowd out the fresh row.
        for i in range(15):
            d = create_decision(ec_db, title=f"Bad call #{i}")
            link_decision_to_file(ec_db, d["id"], hot_file)
            update_decision_staleness(ec_db, d["id"], "contradicted")

        # One fresh decision — must surface in the session-start hook output.
        fresh = create_decision(ec_db, title="Current architecture choice")
        link_decision_to_file(ec_db, fresh["id"], hot_file)

        test_file = ec_repo / "src" / "hot.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("x = 1")
        _subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        _subprocess.run(
            ["git", "-C", str(ec_repo), "commit", "-m", "add hot"],
            check=True,
            capture_output=True,
        )

        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is not None
        assert "Current architecture choice" in result
        # No contradicted titles should appear in the output.
        assert "Bad call" not in result

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

    def test_session_start_chain_collapse_when_only_ancestor_is_linked(self, ec_repo, ec_db, monkeypatch):
        """PR #55 review regression: link ONLY the ancestor to the changed file.

        This is the migration state where a replacement (new) exists but hasn't
        had its file links copied over yet. The chain-collapse branch in the
        hook must still substitute `new` for `old` — otherwise the PR's claim
        that "superseded decisions are replaced with their successor" is vacuous.
        """
        from entirecontext.core.decisions import supersede_decision

        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"show_related_on_start": True},
        )
        old = create_decision(ec_db, title="Original payments decision")
        new = create_decision(ec_db, title="Current payments decision")
        # ONLY the ancestor has the file link — mimics the in-flight migration.
        link_decision_to_file(ec_db, old["id"], "src/payments.py")
        supersede_decision(ec_db, old["id"], new["id"])

        test_file = ec_repo / "src" / "payments.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("x = 1")
        _subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        _subprocess.run(
            ["git", "-C", str(ec_repo), "commit", "-m", "add payments"],
            check=True,
            capture_output=True,
        )

        from entirecontext.hooks.decision_hooks import on_session_start_decisions

        result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": "s1"})
        assert result is not None
        assert "Current payments decision" in result
        assert "Original payments decision" not in result


class TestOnPostToolUseDecisions:
    """Issue #42 regression: mid-session decision surfacing on PostToolUse."""

    def _setup_session_and_turn(self, ec_db, session_id="s-post", turn_number=2):
        """Create a session + in-progress turn with the given turn_number."""
        import json as _json

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        ec_db.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at, "
            "session_title, session_summary, total_turns) "
            "VALUES (?, ?, 'claude', '2025-01-01', '2025-01-01', 't', 't', 0)",
            (session_id, project_id),
        )
        turn_id = f"{session_id}-turn-{turn_number}"
        ec_db.execute(
            "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, "
            "content_hash, timestamp, tools_used, files_touched, turn_status) "
            "VALUES (?, ?, ?, 'u', NULL, 'h', '2025-01-01', ?, '[]', 'in_progress')",
            (turn_id, session_id, turn_number, _json.dumps([])),
        )
        ec_db.commit()
        return session_id, turn_id

    def _enable_surface_on_tool_use(self, monkeypatch, interval=1, limit=3):
        from entirecontext.core.config import load_config as real_load_config

        def patched_load(repo_path=None):
            cfg = real_load_config(repo_path)
            cfg.setdefault("decisions", {})
            cfg["decisions"]["surface_on_tool_use"] = True
            cfg["decisions"]["surface_on_tool_use_turn_interval"] = interval
            cfg["decisions"]["surface_on_tool_use_limit"] = limit
            return cfg

        monkeypatch.setattr("entirecontext.core.config.load_config", patched_load)

    def test_disabled_by_default(self, ec_repo, ec_db):
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        session_id, _turn_id = self._setup_session_and_turn(ec_db)
        d = create_decision(ec_db, title="Never surfaces")
        link_decision_to_file(ec_db, d["id"], "src/app.py")

        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app.py"},
            }
        )
        assert result is None

    def test_surfaces_decision_when_file_edited(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        session_id, _turn_id = self._setup_session_and_turn(ec_db)
        d = create_decision(ec_db, title="Routing strategy")
        link_decision_to_file(ec_db, d["id"], "src/app.py")

        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app.py"},
            }
        )
        assert result is not None
        assert "Routing strategy" in result

        # Fallback file written (PostToolUse-specific, session-scoped —
        # distinct from SessionStart's `decisions-context.md`).
        fallback = ec_repo / ".entirecontext" / f"decisions-context-tooluse-{session_id}.md"
        assert fallback.exists()
        assert "Routing strategy" in fallback.read_text(encoding="utf-8")

        events = ec_db.execute(
            "SELECT COUNT(*) AS n FROM retrieval_events WHERE search_type = 'post_tool_use'"
        ).fetchone()["n"]
        assert events == 1

        selections = ec_db.execute(
            "SELECT COUNT(*) AS n FROM retrieval_selections WHERE result_type = 'decision'"
        ).fetchone()["n"]
        assert selections >= 1

    def test_respects_turn_interval_gate(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        # Interval=2, turn_number=1 → gate fails
        self._enable_surface_on_tool_use(monkeypatch, interval=2)
        session_id, _turn_id = self._setup_session_and_turn(ec_db, turn_number=1)
        d = create_decision(ec_db, title="Gated")
        link_decision_to_file(ec_db, d["id"], "src/app.py")

        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app.py"},
            }
        )
        assert result is None

    def test_per_turn_dedup_single_event_per_turn(self, ec_repo, ec_db, monkeypatch):
        """P1-2 regression: two tool calls in the same user turn → second returns None."""
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        session_id, _turn_id = self._setup_session_and_turn(ec_db)
        d = create_decision(ec_db, title="Per turn")
        link_decision_to_file(ec_db, d["id"], "src/app.py")

        payload = {
            "cwd": str(ec_repo),
            "session_id": session_id,
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/app.py"},
        }

        first = on_post_tool_use_decisions(payload)
        assert first is not None

        second = on_post_tool_use_decisions(payload)
        assert second is None  # same turn → no re-surface

    def test_dedup_within_session_across_turns(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        session_id, first_turn_id = self._setup_session_and_turn(ec_db, turn_number=2)
        d = create_decision(ec_db, title="Cross turn dedup")
        link_decision_to_file(ec_db, d["id"], "src/app.py")

        payload = {
            "cwd": str(ec_repo),
            "session_id": session_id,
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/app.py"},
        }

        first = on_post_tool_use_decisions(payload)
        assert first is not None

        # Mark first turn as completed and create a new in-progress turn
        ec_db.execute("UPDATE turns SET turn_status = 'completed' WHERE id = ?", (first_turn_id,))
        ec_db.execute(
            "INSERT INTO turns (id, session_id, turn_number, user_message, assistant_summary, "
            "content_hash, timestamp, tools_used, files_touched, turn_status) "
            "VALUES (?, ?, ?, 'u', NULL, 'h2', '2025-01-02', '[]', '[]', 'in_progress')",
            (
                "turn-2",
                session_id,
                4,
            ),
        )
        ec_db.commit()

        second = on_post_tool_use_decisions(payload)
        # Decision already in session-wide surfaced_decisions → None (empty candidates cleans up file)
        assert second is None

    def test_cross_channel_dedup_with_session_start(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions, on_session_start_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {
                "show_related_on_start": True,
                "surface_on_tool_use": True,
                "surface_on_tool_use_turn_interval": 1,
                "surface_on_tool_use_limit": 3,
            },
        )
        session_id, _turn_id = self._setup_session_and_turn(ec_db)
        d = create_decision(ec_db, title="Shared between channels")
        link_decision_to_file(ec_db, d["id"], "src/app.py")

        test_file = ec_repo / "src" / "app.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("x = 1")
        _subprocess.run(["git", "-C", str(ec_repo), "add", "."], check=True, capture_output=True)
        _subprocess.run(["git", "-C", str(ec_repo), "commit", "-m", "add"], check=True, capture_output=True)

        session_start_result = on_session_start_decisions({"cwd": str(ec_repo), "session_id": session_id})
        assert session_start_result is not None
        assert "Shared between channels" in session_start_result

        # PostToolUse must not re-surface it
        post_tool_result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app.py"},
            }
        )
        assert post_tool_result is None

    def test_filters_contradicted_and_superseded(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.core.decisions import update_decision_staleness
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        session_id, _turn_id = self._setup_session_and_turn(ec_db)
        bad = create_decision(ec_db, title="Contradicted one")
        link_decision_to_file(ec_db, bad["id"], "src/app.py")
        update_decision_staleness(ec_db, bad["id"], "contradicted")

        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app.py"},
            }
        )
        # Only contradicted decision → candidates empty → None + fallback cleanup
        assert result is None

    def test_no_in_progress_turn_early_returns(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        # Create session but no in-progress turn
        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        ec_db.execute(
            "INSERT INTO sessions (id, project_id, session_type, started_at, last_activity_at, "
            "session_title, session_summary, total_turns) "
            "VALUES ('s-no-turn', ?, 'claude', '2025-01-01', '2025-01-01', 't', 't', 0)",
            (project_id,),
        )
        ec_db.commit()
        d = create_decision(ec_db, title="Has no turn")
        link_decision_to_file(ec_db, d["id"], "src/app.py")

        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": "s-no-turn",
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app.py"},
            }
        )
        assert result is None

    def test_exception_swallowed(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        # Force get_db to raise
        monkeypatch.setattr("entirecontext.db.get_db", lambda _: (_ for _ in ()).throw(RuntimeError("boom")))

        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": "s1",
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app.py"},
            }
        )
        assert result is None

    def test_honors_should_skip_file(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.core.config import load_config as real_load_config
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        def patched_load(repo_path=None):
            cfg = real_load_config(repo_path)
            cfg.setdefault("decisions", {})["surface_on_tool_use"] = True
            cfg["decisions"]["surface_on_tool_use_turn_interval"] = 1
            cfg["decisions"]["surface_on_tool_use_limit"] = 3
            cfg.setdefault("capture", {}).setdefault("exclusions", {})["enabled"] = True
            cfg["capture"]["exclusions"]["file_patterns"] = [".env"]
            return cfg

        monkeypatch.setattr("entirecontext.core.config.load_config", patched_load)

        session_id, _turn_id = self._setup_session_and_turn(ec_db)
        d = create_decision(ec_db, title="Skipped env")
        link_decision_to_file(ec_db, d["id"], ".env")

        # Must use an edit-capable tool here: read-only tools (``Read``,
        # ``NotebookRead``) short-circuit on the ``_READ_ONLY_TOOLS`` guard
        # added for Codex P2, which would bypass ``should_skip_file`` entirely
        # and give a false-positive pass on this test.
        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": ".env"},
            }
        )
        assert result is None

    def test_read_only_tool_does_not_consume_dedup(self, ec_repo, ec_db, monkeypatch):
        """[Codex P2] Read / NotebookRead must NOT fire mid-session surfacing.

        Typical agent flow is Read-then-Edit within one turn: letting the
        Read consume the per-turn dedup marker would suppress the Edit's
        Markdown block, destroying the core timing of the feature. The
        subsequent Edit in the same turn must still surface normally.
        """
        import json as _json

        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        session_id, _turn_id = self._setup_session_and_turn(ec_db)
        d = create_decision(ec_db, title="Survives Read-then-Edit")
        link_decision_to_file(ec_db, d["id"], "src/app.py")

        read_result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Read",
                "tool_input": {"file_path": "src/app.py"},
            }
        )
        assert read_result is None

        notebook_read_result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "NotebookRead",
                "tool_input": {"notebook_path": "nb.ipynb"},
            }
        )
        assert notebook_read_result is None

        row = ec_db.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row["metadata"]:
            meta = _json.loads(row["metadata"])
            assert not meta.get("surfaced_decisions"), "read-only tools must not populate surfaced_decisions"
            assert not meta.get("post_tool_surfaced_turns"), "read-only tools must not consume per-turn dedup"

        edit_result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app.py"},
            }
        )
        assert edit_result is not None, (
            "Edit after Read in same turn must still surface — Read must not have consumed the per-turn dedup marker"
        )
        assert "Survives Read-then-Edit" in edit_result

        row = ec_db.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
        meta = _json.loads(row["metadata"])
        assert d["id"] in meta.get("surfaced_decisions", [])

    def test_write_tool_captures_file_path(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        session_id, _turn_id = self._setup_session_and_turn(ec_db)
        d = create_decision(ec_db, title="Written file rule")
        link_decision_to_file(ec_db, d["id"], "src/new.py")

        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Write",
                "tool_input": {"file_path": "src/new.py", "content": "x = 1"},
            }
        )
        assert result is not None
        assert "Written file rule" in result

    def test_notebook_edit_captures_notebook_path(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        session_id, _turn_id = self._setup_session_and_turn(ec_db)
        d = create_decision(ec_db, title="Notebook convention")
        link_decision_to_file(ec_db, d["id"], "notebooks/explore.ipynb")

        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "NotebookEdit",
                "tool_input": {"notebook_path": "notebooks/explore.ipynb"},
            }
        )
        assert result is not None
        assert "Notebook convention" in result

    def test_multiedit_captures_all_edits(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        session_id, _turn_id = self._setup_session_and_turn(ec_db)
        d = create_decision(ec_db, title="Second file rule")
        link_decision_to_file(ec_db, d["id"], "src/second.py")

        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "MultiEdit",
                "tool_input": {
                    "edits": [
                        {"file_path": "src/first.py"},
                        {"file_path": "src/second.py"},
                    ],
                },
            }
        )
        assert result is not None
        assert "Second file rule" in result

    def test_handles_legacy_relative_path(self, ec_repo, ec_db, monkeypatch):
        """P0-2 regression: decision linked with `./src/app.py`, tool payload
        sends `src/app.py` — must surface via _gather_exact_file_matches
        normalization (inline SQL `SUBSTR` strips `./` prefixes and normalizes
        backslashes before the IN check).
        """
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        session_id, _turn_id = self._setup_session_and_turn(ec_db)
        d = create_decision(ec_db, title="Legacy path linkage")
        link_decision_to_file(ec_db, d["id"], "./src/legacy.py")

        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/legacy.py"},
            }
        )
        assert result is not None
        assert "Legacy path linkage" in result

    def test_null_session_metadata_write_safe(self, ec_repo, ec_db, monkeypatch):
        """P1-4 regression: session.metadata NULL → json_set uses COALESCE."""
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        session_id, _turn_id = self._setup_session_and_turn(ec_db)
        # Explicitly ensure NULL metadata
        ec_db.execute("UPDATE sessions SET metadata = NULL WHERE id = ?", (session_id,))
        ec_db.commit()

        d = create_decision(ec_db, title="Null metadata test")
        link_decision_to_file(ec_db, d["id"], "src/null.py")

        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/null.py"},
            }
        )
        assert result is not None

        # Metadata should now contain the dedup keys
        row = ec_db.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
        import json as _json

        meta = _json.loads(row["metadata"])
        assert d["id"] in meta.get("surfaced_decisions", [])
        assert "post_tool_surfaced_turns" in meta

    def test_metadata_failure_leaves_no_orphan_telemetry(self, ec_repo, ec_db, monkeypatch):
        """PR #56 round 7 (#discussion_r3080485995) regression:
        ``record_retrieval_event`` commits internally (telemetry.py:75),
        so if it runs before ``_write_session_metadata_patch`` and the
        metadata write subsequently fails, the rollback in the except
        handler cannot undo the already-committed telemetry row.

        The fix reorders the writes so the metadata patch runs first.
        This test asserts that when the metadata patch raises, ZERO
        rows end up in ``retrieval_events`` — proving telemetry was
        never called (let alone committed) before the metadata failure.
        A regression that re-orders the calls would leave one orphan row.
        """
        import sqlite3

        from entirecontext.hooks import decision_hooks
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        session_id, _turn_id = self._setup_session_and_turn(ec_db)
        d = create_decision(ec_db, title="Atomic ordering test")
        link_decision_to_file(ec_db, d["id"], "src/atomic.py")

        def failing_patch(conn, sid, patch):
            raise sqlite3.OperationalError("simulated SQLITE_BUSY")

        monkeypatch.setattr(decision_hooks, "_write_session_metadata_patch", failing_patch)

        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/atomic.py"},
            }
        )
        assert result is None

        events = ec_db.execute(
            "SELECT COUNT(*) AS n FROM retrieval_events WHERE search_type = 'post_tool_use'"
        ).fetchone()["n"]
        assert events == 0, (
            "orphan retrieval_events row detected — record_retrieval_event "
            "must not run before _write_session_metadata_patch"
        )

        fallback = ec_repo / ".entirecontext" / f"decisions-context-tooluse-{session_id}.md"
        assert not fallback.exists()

        row = ec_db.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row["metadata"]:
            import json as _json

            meta = _json.loads(row["metadata"])
            assert not meta.get("surfaced_decisions"), (
                "surfaced_decisions must remain empty after a failed metadata patch"
            )
            assert not meta.get("post_tool_surfaced_turns"), (
                "post_tool_surfaced_turns must remain empty after a failed metadata patch"
            )

    def test_concurrent_sessions_do_not_clobber_each_others_fallback(self, ec_repo, ec_db, monkeypatch):
        """PR #56 round 4: two sessions in the same repo each get their own
        `decisions-context-tooluse-<session>.md` file. An empty PostToolUse
        event in session B must not delete the file session A has just
        written — the filename is session-qualified.
        """
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)

        session_a, _ = self._setup_session_and_turn(ec_db, session_id="s-alpha", turn_number=2)
        session_b, _ = self._setup_session_and_turn(ec_db, session_id="s-beta", turn_number=2)

        d = create_decision(ec_db, title="Alpha linked decision")
        link_decision_to_file(ec_db, d["id"], "src/alpha.py")

        # Session A surfaces and writes its fallback.
        result_a = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_a,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/alpha.py"},
            }
        )
        assert result_a is not None
        file_a = ec_repo / ".entirecontext" / f"decisions-context-tooluse-{session_a}.md"
        file_b = ec_repo / ".entirecontext" / f"decisions-context-tooluse-{session_b}.md"
        assert file_a.exists()
        assert not file_b.exists()

        # Session B edits an unlinked file → empty result → its own cleanup
        # fires but must not touch session A's fallback.
        result_b = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_b,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/beta.py"},
            }
        )
        assert result_b is None
        assert file_a.exists()  # still there
        assert "Alpha linked decision" in file_a.read_text(encoding="utf-8")

    def test_chain_collapse_reachable_when_ancestor_already_surfaced(self, ec_repo, ec_db, monkeypatch):
        """PR #56 review round 3 — Bug 1: the session-wide dedup set may
        contain a superseded ancestor (because SessionStart surfaced it).
        The hook must still walk the chain and surface the fresh terminal
        successor; subtracting the ancestor from ``candidate_ids`` before
        chain resolution would hide the new decision entirely.
        """
        import json as _json

        from entirecontext.core.decisions import supersede_decision
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        session_id, _turn_id = self._setup_session_and_turn(ec_db)

        old = create_decision(ec_db, title="Ancestor D1")
        new = create_decision(ec_db, title="Fresh successor D2")
        link_decision_to_file(ec_db, old["id"], "src/migration.py")
        supersede_decision(ec_db, old["id"], new["id"])

        # Pretend SessionStart already surfaced the ancestor; the hook
        # must not short-circuit before chain resolution.
        ec_db.execute(
            "UPDATE sessions SET metadata = ? WHERE id = ?",
            (_json.dumps({"surfaced_decisions": [old["id"]]}), session_id),
        )
        ec_db.commit()

        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/migration.py"},
            }
        )

        assert result is not None
        assert "Fresh successor D2" in result
        assert "Ancestor D1" not in result

    def test_post_tool_cleanup_does_not_touch_session_start_file(self, ec_repo, ec_db, monkeypatch):
        """PR #56 review round 3 — Bug 2: when PostToolUse returns None on
        an empty/deduped result, it must only clean its own fallback file
        (``decisions-context-tooluse.md``) and leave the SessionStart file
        (``decisions-context.md``) alone.
        """
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        session_id, _turn_id = self._setup_session_and_turn(ec_db)

        # SessionStart has written its file; PostToolUse must not touch it.
        session_start_file = ec_repo / ".entirecontext" / "decisions-context.md"
        session_start_file.parent.mkdir(parents=True, exist_ok=True)
        session_start_file.write_text("important session-start context", encoding="utf-8")

        # Edit a file with no linked decisions → empty result → cleanup fires
        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/unlinked.py"},
            }
        )
        assert result is None
        # SessionStart file untouched
        assert session_start_file.exists()
        assert session_start_file.read_text(encoding="utf-8") == "important session-start context"

    def test_chain_collapse_substitutes_terminal_successor(self, ec_repo, ec_db, monkeypatch):
        """PR #56 Codex review P1: when the file link is on the superseded
        ancestor (common migration state — old linked, new not yet linked),
        the hook must walk the chain and surface the terminal successor."""
        from entirecontext.core.decisions import supersede_decision
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        session_id, _turn_id = self._setup_session_and_turn(ec_db)

        old = create_decision(ec_db, title="Retired routing")
        new = create_decision(ec_db, title="Current routing")
        # File link stays on `old`; `new` has no file link yet.
        link_decision_to_file(ec_db, old["id"], "src/router.py")
        supersede_decision(ec_db, old["id"], new["id"])

        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/router.py"},
            }
        )

        assert result is not None
        assert "Current routing" in result  # terminal successor surfaces
        assert "Retired routing" not in result  # ancestor is hidden

    def test_exact_match_beats_sibling_directory_candidate(self, ec_repo, ec_db, monkeypatch):
        """PR #56 Codex review P2: a decision with an exact file link must
        outrank a more-recent sibling decision in the same directory when
        the limit is small.
        """
        import time as _time

        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch, limit=1)
        session_id, _turn_id = self._setup_session_and_turn(ec_db)

        exact = create_decision(ec_db, title="Exact hit")
        link_decision_to_file(ec_db, exact["id"], "src/app.py")

        # Create a newer sibling decision in the same directory
        _time.sleep(0.01)  # ensure updated_at differs
        sibling = create_decision(ec_db, title="Recent sibling")
        link_decision_to_file(ec_db, sibling["id"], "src/other.py")

        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app.py"},
            }
        )

        assert result is not None
        assert "Exact hit" in result
        assert "Recent sibling" not in result  # sibling must not crowd out the exact match

    def test_nested_cwd_resolves_repo_scoped_config(self, ec_repo, ec_db):
        """PR #56 Codex review P1: PostToolUse hook invoked from a nested
        subdirectory must still honor `<repo>/.entirecontext/config.toml`
        and write the fallback file at the repo root, not the subdirectory.
        """
        import json as _json

        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        # Write a repo-scoped .entirecontext/config.toml that enables the flag.
        ec_config_dir = ec_repo / ".entirecontext"
        ec_config_dir.mkdir(parents=True, exist_ok=True)
        (ec_config_dir / "config.toml").write_text(
            "[decisions]\nsurface_on_tool_use = true\nsurface_on_tool_use_turn_interval = 1\nsurface_on_tool_use_limit = 3\n",
            encoding="utf-8",
        )

        session_id, _turn_id = self._setup_session_and_turn(ec_db)
        d = create_decision(ec_db, title="Nested cwd rule")
        link_decision_to_file(ec_db, d["id"], "src/nested.py")

        nested_dir = ec_repo / "src" / "features"
        nested_dir.mkdir(parents=True, exist_ok=True)

        result = on_post_tool_use_decisions(
            {
                "cwd": str(nested_dir),  # <-- nested, not repo root
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/nested.py"},
            }
        )

        assert result is not None
        assert "Nested cwd rule" in result

        # PostToolUse fallback file lives at the REPO root, not in the
        # nested subdirectory. Filename is session-qualified.
        repo_fallback = ec_repo / ".entirecontext" / f"decisions-context-tooluse-{session_id}.md"
        nested_fallback = nested_dir / ".entirecontext" / f"decisions-context-tooluse-{session_id}.md"
        assert repo_fallback.exists()
        assert not nested_fallback.exists()

        # Session metadata was updated on the session row.
        row = ec_db.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
        meta = _json.loads(row["metadata"])
        assert d["id"] in meta["surfaced_decisions"]

    def test_empty_result_cleans_up_fallback_file(self, ec_repo, ec_db, monkeypatch):
        """Stale PostToolUse fallback is removed when the current surface
        event returns no results. Only the tool-use file is cleaned; the
        SessionStart file (if present) is never touched by this path
        (PR #56 review round 3 — cross-channel cleanup bug)."""
        from entirecontext.hooks.decision_hooks import on_post_tool_use_decisions

        self._enable_surface_on_tool_use(monkeypatch)
        session_id, _turn_id = self._setup_session_and_turn(ec_db)
        create_decision(ec_db, title="Not linked")

        fallback = ec_repo / ".entirecontext" / f"decisions-context-tooluse-{session_id}.md"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text("stale tool-use context", encoding="utf-8")

        # Seed SessionStart file too so we can confirm it survives cleanup.
        session_start_fallback = ec_repo / ".entirecontext" / "decisions-context.md"
        session_start_fallback.write_text("session start context", encoding="utf-8")

        # Edit file not linked to any decision → empty result
        result = on_post_tool_use_decisions(
            {
                "cwd": str(ec_repo),
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/unlinked.py"},
            }
        )
        assert result is None
        # PostToolUse fallback file removed
        assert not fallback.exists()
        # SessionStart file must NOT be touched by PostToolUse cleanup
        assert session_start_fallback.exists()
        assert session_start_fallback.read_text(encoding="utf-8") == "session start context"


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
            lambda _: {"auto_extract": True, "extract_keywords": ["decided"], "noise_gate_min_turns_with_files": 0},
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
            lambda _: {"auto_extract": True, "extract_keywords": ["decided"], "noise_gate_min_turns_with_files": 0},
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
            lambda _: {"auto_extract": True, "extract_keywords": ["decided"], "noise_gate_min_turns_with_files": 0},
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
            lambda _: {"auto_extract": True, "extract_keywords": ["decided"], "noise_gate_min_turns_with_files": 0},
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

    def test_gate_respects_extract_sources_session_only(self, ec_repo, ec_db, monkeypatch):
        """Regression: with extract_sources=['session'] and no keyword-match
        in summaries but a checkpoint diff_summary present, the gate must
        NOT launch the worker. Previously the gate unconditionally OR'd
        all three signals and spawned a no-op worker."""
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {
                "auto_extract": True,
                "extract_keywords": ["decided"],
                "extract_sources": ["session"],
                "noise_gate_min_turns_with_files": 0,
            },
        )
        session = self._setup_session_with_summaries(ec_db, ["just a normal conversation"])
        # Seed a checkpoint with non-empty diff_summary — used to trigger the
        # checkpoint signal path. Must be ignored because extract_sources
        # excludes checkpoint.
        import uuid as _uuid

        ec_db.execute(
            "INSERT INTO checkpoints (id, session_id, git_commit_hash, diff_summary) VALUES (?, ?, ?, ?)",
            (str(_uuid.uuid4()), session["id"], "abc", "src/cache.py | 5 +++--\nsrc/db.py | 3 +"),
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

    def test_gate_respects_extract_sources_checkpoint_only(self, ec_repo, ec_db, monkeypatch):
        """Regression: with extract_sources=['checkpoint'] and a session
        summary that would have matched the keyword, the gate must still
        launch (checkpoint signal present) but must NOT launch due to the
        session signal. Verified indirectly: we also add a session summary
        that matches the keyword, set extract_sources to ['checkpoint']
        only, omit any checkpoint, and expect no launch — proving that
        the session path is correctly gated off."""
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {
                "auto_extract": True,
                "extract_keywords": ["decided"],
                "extract_sources": ["checkpoint"],
                "noise_gate_min_turns_with_files": 0,
            },
        )
        session = self._setup_session_with_summaries(ec_db, ["We decided to use Redis"])
        launched = []
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks.launch_worker",
            lambda *a, **kw: launched.append(1) or 0,
        )
        from entirecontext.hooks.decision_hooks import maybe_extract_decisions

        maybe_extract_decisions(str(ec_repo), session["id"])
        # No checkpoint seeded; session signal was disabled by extract_sources.
        # Worker must not spawn.
        assert len(launched) == 0


class TestNoiseGate:
    def test_passes_with_checkpoint(self, ec_repo, ec_db):
        from entirecontext.hooks.decision_hooks import _session_passes_noise_gate

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id)
        ec_db.execute(
            "INSERT INTO checkpoints (id, session_id, git_commit_hash) VALUES (?, ?, ?)",
            ("cp-ng-1", session["id"], "abc123"),
        )
        ec_db.commit()
        assert _session_passes_noise_gate(ec_db, session["id"]) is True

    def test_passes_with_enough_file_turns(self, ec_repo, ec_db):
        from entirecontext.hooks.decision_hooks import _session_passes_noise_gate

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id)
        for i in range(3):
            turn = create_turn(ec_db, session["id"], i + 1, user_message=f"edit {i}")
            ec_db.execute(
                "UPDATE turns SET files_touched = ? WHERE id = ?",
                (json.dumps([f"src/file{i}.py"]), turn["id"]),
            )
        ec_db.commit()
        assert _session_passes_noise_gate(ec_db, session["id"]) is True

    def test_rejects_low_signal(self, ec_repo, ec_db):
        from entirecontext.hooks.decision_hooks import _session_passes_noise_gate

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id)
        create_turn(ec_db, session["id"], 1, user_message="just chatting")
        assert _session_passes_noise_gate(ec_db, session["id"]) is False

    def test_maybe_extract_skips_below_noise_gate(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.hooks.decision_hooks._load_decisions_config",
            lambda _: {"auto_extract": True, "extract_keywords": ["decided"], "noise_gate_min_turns_with_files": 3},
        )
        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id)
        turn = create_turn(ec_db, session["id"], 1, user_message="msg")
        ec_db.execute(
            "UPDATE turns SET assistant_summary = ? WHERE id = ?",
            ("We decided to use Redis", turn["id"]),
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

    def test_creates_candidates_from_llm_response(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.core.decision_candidates import list_candidates

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

        candidates = list_candidates(ec_db, session_id=session["id"])
        titles = [c["title"] for c in candidates]
        assert "Use Redis for caching" in titles
        # Real decisions table should be untouched
        assert list_decisions(ec_db) == []

        row = ec_db.execute("SELECT metadata FROM sessions WHERE id = ?", (session["id"],)).fetchone()
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        assert meta.get("candidates_extracted") is True

    def test_auto_files_on_candidate(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.core.decision_candidates import list_candidates

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

        candidates = list_candidates(ec_db, session_id=session["id"])
        assert len(candidates) >= 1
        candidate_files = candidates[0].get("files") or []
        # Files live on the candidate row until confirm promotes them.
        assert "src/cache.py" in candidate_files

    def test_empty_array_sets_candidates_marker(self, ec_repo, ec_db, monkeypatch):
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
        assert meta.get("candidates_extracted") is True

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
        # parse failure must not mark the session so the next SessionEnd retries
        assert meta.get("candidates_extracted") is not True
        assert meta.get("decisions_extracted") is not True

    def test_max_5_candidates(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.core.decision_candidates import list_candidates

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

        candidates = list_candidates(ec_db, session_id=session["id"])
        assert len(candidates) <= 5

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

    def test_v12_marker_shim_short_circuits(self, ec_repo, ec_db, monkeypatch):
        """v12 decisions_extracted marker must be honored as already-extracted."""
        session = self._setup_session_with_turns(
            ec_db,
            [
                ("We decided X", []),
            ],
        )
        ec_db.execute(
            "UPDATE sessions SET metadata = ? WHERE id = ?",
            (json.dumps({"decisions_extracted": True}), session["id"]),
        )
        ec_db.commit()

        call_count = []
        monkeypatch.setattr(
            "entirecontext.cli.decisions_cmds._get_llm_response",
            lambda *a, **kw: (call_count.append(1), "[]")[1],
        )
        from entirecontext.cli.decisions_cmds import _extract_from_session_impl

        _extract_from_session_impl(ec_db, session["id"], str(ec_repo))
        assert len(call_count) == 0


class TestIgnoredInference:
    def test_infers_ignored_for_surfaced_unacted(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.core.project import get_project
        from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="ignored-inf")
        for i in range(5):
            create_turn(ec_db, session["id"], i + 1, user_message=f"turn {i}")

        d = create_decision(ec_db, title="Surfaced but unacted")
        event = record_retrieval_event(
            ec_db,
            source="hook",
            search_type="session_start",
            target="decision",
            query="test",
            result_count=1,
            latency_ms=0,
            session_id=session["id"],
        )
        record_retrieval_selection(
            ec_db,
            event["id"],
            "decision",
            d["id"],
            rank=1,
            session_id=session["id"],
            turn_id=ec_db.execute(
                "SELECT id FROM turns WHERE session_id = ? AND turn_number = 1", (session["id"],)
            ).fetchone()["id"],
        )

        monkeypatch.setattr(
            "entirecontext.core.config.load_config",
            lambda _: {"decisions": {"infer_ignored_on_session_end": True, "ignored_inference_min_turn_gap": 2}},
        )
        from entirecontext.hooks.session_lifecycle import _maybe_infer_ignored_decisions

        _maybe_infer_ignored_decisions(str(ec_repo), session["id"])

        outcomes = ec_db.execute(
            "SELECT outcome_type FROM decision_outcomes WHERE decision_id = ?",
            (d["id"],),
        ).fetchall()
        assert len(outcomes) == 1
        assert outcomes[0]["outcome_type"] == "ignored"

    def test_skips_acted_decisions(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.core.decisions import record_decision_outcome
        from entirecontext.core.project import get_project
        from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="acted-skip")
        for i in range(5):
            create_turn(ec_db, session["id"], i + 1, user_message=f"turn {i}")

        d = create_decision(ec_db, title="Already accepted")
        event = record_retrieval_event(
            ec_db,
            source="hook",
            search_type="session_start",
            target="decision",
            query="test",
            result_count=1,
            latency_ms=0,
            session_id=session["id"],
        )
        sel = record_retrieval_selection(
            ec_db,
            event["id"],
            "decision",
            d["id"],
            rank=1,
            session_id=session["id"],
            turn_id=ec_db.execute(
                "SELECT id FROM turns WHERE session_id = ? AND turn_number = 1", (session["id"],)
            ).fetchone()["id"],
        )
        turn1_id = ec_db.execute(
            "SELECT id FROM turns WHERE session_id = ? AND turn_number = 1", (session["id"],)
        ).fetchone()["id"]
        record_decision_outcome(
            ec_db,
            d["id"],
            "accepted",
            retrieval_selection_id=sel["id"],
            session_id=session["id"],
            turn_id=turn1_id,
        )

        monkeypatch.setattr(
            "entirecontext.core.config.load_config",
            lambda _: {"decisions": {"infer_ignored_on_session_end": True, "ignored_inference_min_turn_gap": 2}},
        )
        from entirecontext.hooks.session_lifecycle import _maybe_infer_ignored_decisions

        _maybe_infer_ignored_decisions(str(ec_repo), session["id"])

        outcomes = ec_db.execute(
            "SELECT outcome_type FROM decision_outcomes WHERE decision_id = ?",
            (d["id"],),
        ).fetchall()
        assert len(outcomes) == 1
        assert outcomes[0]["outcome_type"] == "accepted"

    def test_grace_period_skips_recent(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.core.project import get_project
        from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="grace-period")
        for i in range(3):
            create_turn(ec_db, session["id"], i + 1, user_message=f"turn {i}")

        d = create_decision(ec_db, title="Surfaced in last turn")
        event = record_retrieval_event(
            ec_db,
            source="hook",
            search_type="post_tool_use",
            target="decision",
            query="test",
            result_count=1,
            latency_ms=0,
            session_id=session["id"],
        )
        last_turn_id = ec_db.execute(
            "SELECT id FROM turns WHERE session_id = ? AND turn_number = 3", (session["id"],)
        ).fetchone()["id"]
        record_retrieval_selection(
            ec_db,
            event["id"],
            "decision",
            d["id"],
            rank=1,
            session_id=session["id"],
            turn_id=last_turn_id,
        )

        monkeypatch.setattr(
            "entirecontext.core.config.load_config",
            lambda _: {"decisions": {"infer_ignored_on_session_end": True, "ignored_inference_min_turn_gap": 2}},
        )
        from entirecontext.hooks.session_lifecycle import _maybe_infer_ignored_decisions

        _maybe_infer_ignored_decisions(str(ec_repo), session["id"])

        outcomes = ec_db.execute(
            "SELECT COUNT(*) AS n FROM decision_outcomes WHERE decision_id = ?",
            (d["id"],),
        ).fetchone()["n"]
        assert outcomes == 0

    def test_config_gated_default_off(self, ec_repo, ec_db, monkeypatch):
        monkeypatch.setattr(
            "entirecontext.core.config.load_config",
            lambda _: {"decisions": {}},
        )
        from entirecontext.hooks.session_lifecycle import _maybe_infer_ignored_decisions

        _maybe_infer_ignored_decisions(str(ec_repo), "any-session")

    def test_infers_ignored_with_null_turn_id(self, ec_repo, ec_db, monkeypatch):
        """SessionStart-style selections (turn_id NULL) must still produce ignored outcomes.

        Before the fix, record_decision_outcome raised ValueError (pair constraint) and was
        silently swallowed by ``except Exception: pass``. After the fix, we pass session_id=None
        when turn_id is NULL, and ``_resolve_outcome_context`` inherits session_id from the
        retrieval_selection via its fallback path — preserving audit trail without tripping
        the pair check.
        """
        from entirecontext.core.project import get_project
        from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="null-turn-id")
        for i in range(5):
            create_turn(ec_db, session["id"], i + 1, user_message=f"turn {i}")

        d = create_decision(ec_db, title="Surfaced with null turn_id")
        event = record_retrieval_event(
            ec_db,
            source="hook",
            search_type="session_start",
            target="decision",
            query="test",
            result_count=1,
            latency_ms=0,
            session_id=session["id"],
        )
        record_retrieval_selection(
            ec_db,
            event["id"],
            "decision",
            d["id"],
            rank=1,
            session_id=session["id"],
            turn_id=None,
        )

        monkeypatch.setattr(
            "entirecontext.core.config.load_config",
            lambda _: {"decisions": {"infer_ignored_on_session_end": True, "ignored_inference_min_turn_gap": 2}},
        )
        from entirecontext.hooks.session_lifecycle import _maybe_infer_ignored_decisions

        _maybe_infer_ignored_decisions(str(ec_repo), session["id"])

        rows = ec_db.execute(
            "SELECT outcome_type, session_id, turn_id FROM decision_outcomes WHERE decision_id = ?",
            (d["id"],),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["outcome_type"] == "ignored"
        assert rows[0]["session_id"] == session["id"]
        assert rows[0]["turn_id"] is None

    def test_infers_ignored_deduplicates_multiple_surfacings(self, ec_repo, ec_db, monkeypatch):
        """Same decision surfaced at SessionStart and PostToolUse must yield exactly one ignored outcome."""
        from entirecontext.core.project import get_project
        from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="dedupe-multi")
        for i in range(5):
            create_turn(ec_db, session["id"], i + 1, user_message=f"turn {i}")

        d = create_decision(ec_db, title="Surfaced twice")
        event_start = record_retrieval_event(
            ec_db,
            source="hook",
            search_type="session_start",
            target="decision",
            query="test",
            result_count=1,
            latency_ms=0,
            session_id=session["id"],
        )
        sel_start = record_retrieval_selection(
            ec_db,
            event_start["id"],
            "decision",
            d["id"],
            rank=1,
            session_id=session["id"],
            turn_id=None,
        )
        event_tool = record_retrieval_event(
            ec_db,
            source="hook",
            search_type="post_tool_use",
            target="decision",
            query="test",
            result_count=1,
            latency_ms=0,
            session_id=session["id"],
        )
        turn2_id = ec_db.execute(
            "SELECT id FROM turns WHERE session_id = ? AND turn_number = 2", (session["id"],)
        ).fetchone()["id"]
        record_retrieval_selection(
            ec_db,
            event_tool["id"],
            "decision",
            d["id"],
            rank=1,
            session_id=session["id"],
            turn_id=turn2_id,
        )

        monkeypatch.setattr(
            "entirecontext.core.config.load_config",
            lambda _: {"decisions": {"infer_ignored_on_session_end": True, "ignored_inference_min_turn_gap": 2}},
        )
        from entirecontext.hooks.session_lifecycle import _maybe_infer_ignored_decisions

        _maybe_infer_ignored_decisions(str(ec_repo), session["id"])

        rows = ec_db.execute(
            "SELECT outcome_type, retrieval_selection_id FROM decision_outcomes WHERE decision_id = ?",
            (d["id"],),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["outcome_type"] == "ignored"
        # Earliest surfacing (SessionStart, NULL turn_id) wins the representative slot via COALESCE(..., 0).
        assert rows[0]["retrieval_selection_id"] == sel_start["id"]

    def test_grace_period_uses_earliest_surfacing(self, ec_repo, ec_db, monkeypatch):
        """Late surfacing must not mask an earlier surfacing that satisfies the grace period."""
        from entirecontext.core.project import get_project
        from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="earliest-wins")
        for i in range(5):
            create_turn(ec_db, session["id"], i + 1, user_message=f"turn {i}")

        d = create_decision(ec_db, title="Surfaced early and late")
        turn1_id = ec_db.execute(
            "SELECT id FROM turns WHERE session_id = ? AND turn_number = 1", (session["id"],)
        ).fetchone()["id"]
        turn5_id = ec_db.execute(
            "SELECT id FROM turns WHERE session_id = ? AND turn_number = 5", (session["id"],)
        ).fetchone()["id"]

        event_early = record_retrieval_event(
            ec_db,
            source="hook",
            search_type="session_start",
            target="decision",
            query="test",
            result_count=1,
            latency_ms=0,
            session_id=session["id"],
        )
        record_retrieval_selection(
            ec_db,
            event_early["id"],
            "decision",
            d["id"],
            rank=1,
            session_id=session["id"],
            turn_id=turn1_id,
        )
        event_late = record_retrieval_event(
            ec_db,
            source="hook",
            search_type="post_tool_use",
            target="decision",
            query="test",
            result_count=1,
            latency_ms=0,
            session_id=session["id"],
        )
        record_retrieval_selection(
            ec_db,
            event_late["id"],
            "decision",
            d["id"],
            rank=1,
            session_id=session["id"],
            turn_id=turn5_id,
        )

        # max_turn=5, early surfacing at turn=1 → gap=4 ≥ 2 (passes).
        # Late surfacing at turn=5 → gap=0 < 2 (would fail if it won the slot).
        monkeypatch.setattr(
            "entirecontext.core.config.load_config",
            lambda _: {"decisions": {"infer_ignored_on_session_end": True, "ignored_inference_min_turn_gap": 2}},
        )
        from entirecontext.hooks.session_lifecycle import _maybe_infer_ignored_decisions

        _maybe_infer_ignored_decisions(str(ec_repo), session["id"])

        rows = ec_db.execute(
            "SELECT outcome_type FROM decision_outcomes WHERE decision_id = ?",
            (d["id"],),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["outcome_type"] == "ignored"


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
