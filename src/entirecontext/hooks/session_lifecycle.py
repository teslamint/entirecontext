"""Session lifecycle management via Claude Code hooks."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_git_root(cwd: str) -> str | None:
    """Find the git repo root from cwd."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _record_hook_warning(repo_path: str, phase: str, exc: Exception) -> None:
    if not repo_path:
        return
    try:
        from ..db import check_and_migrate, get_db
        from ..core.telemetry import record_operation_event

        conn = get_db(repo_path)
        try:
            check_and_migrate(conn)
            record_operation_event(
                conn,
                source="hook",
                operation_name="session_lifecycle",
                phase=phase,
                status="warning",
                error_class=type(exc).__name__,
                message=str(exc),
            )
        finally:
            conn.close()
    except Exception:
        return


def _ensure_project(conn, repo_path: str) -> str:
    """Ensure project exists, return project_id."""
    row = conn.execute("SELECT id FROM projects WHERE repo_path = ?", (repo_path,)).fetchone()
    if row:
        return row["id"]

    from pathlib import Path

    project_id = str(uuid4())
    conn.execute(
        "INSERT INTO projects (id, name, repo_path) VALUES (?, ?, ?)",
        (project_id, Path(repo_path).name, repo_path),
    )
    conn.commit()
    return project_id


def on_session_start(data: dict[str, Any]) -> None:
    """Handle SessionStart hook — create or resume a session."""
    session_id = data.get("session_id")
    cwd = data.get("cwd", ".")
    source = data.get("source", "startup")

    repo_path = _find_git_root(cwd)
    if not repo_path:
        return

    from ..db import get_db, check_and_migrate

    conn = get_db(repo_path)
    try:
        check_and_migrate(conn)

        project_id = _ensure_project(conn, repo_path)
        now = _now_iso()

        if source == "resume" and session_id:
            row = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE sessions SET last_activity_at = ?, updated_at = ? WHERE id = ?",
                    (now, now, session_id),
                )
                conn.commit()
                return

        if not session_id:
            session_id = str(uuid4())

        conn.execute(
            """INSERT OR IGNORE INTO sessions
            (id, project_id, session_type, workspace_path, started_at, last_activity_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, project_id, "claude", cwd, now, now),
        )
        conn.commit()

        try:
            import json

            git_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if git_result.returncode == 0:
                start_git_commit = git_result.stdout.strip()
                metadata = json.dumps({"start_git_commit": start_git_commit})
                conn.execute(
                    "UPDATE sessions SET metadata = ? WHERE id = ? AND metadata IS NULL",
                    (metadata, session_id),
                )
                conn.commit()
        except Exception as exc:
            _record_hook_warning(repo_path, "session_start_metadata", exc)
    finally:
        conn.close()


def _populate_session_summary(conn, session_id: str) -> None:
    """Generate session title/summary from turns if not already set."""
    session = conn.execute(
        "SELECT session_title, session_summary FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if not session:
        return

    needs_title = session["session_title"] is None
    needs_summary = session["session_summary"] is None
    if not needs_title and not needs_summary:
        return

    turns = conn.execute(
        "SELECT user_message, assistant_summary FROM turns WHERE session_id = ? ORDER BY turn_number ASC LIMIT 3",
        (session_id,),
    ).fetchall()
    if not turns:
        return

    updates = {}
    if needs_title:
        first_msg = turns[0]["user_message"] or ""
        if first_msg:
            updates["session_title"] = first_msg[:100]

    if needs_summary:
        summaries = [t["assistant_summary"] for t in turns if t["assistant_summary"]]
        if summaries:
            combined = " | ".join(summaries)
            updates["session_summary"] = combined[:500]

    if updates:
        if "session_title" in updates:
            conn.execute(
                "UPDATE sessions SET session_title = ? WHERE id = ?",
                (updates["session_title"], session_id),
            )
        if "session_summary" in updates:
            conn.execute(
                "UPDATE sessions SET session_summary = ? WHERE id = ?",
                (updates["session_summary"], session_id),
            )
        conn.commit()

    _maybe_generate_intent_summary(conn, session_id)


def _maybe_generate_intent_summary(conn, session_id: str) -> None:
    """Generate intent summary via LLM if enabled. No-op on config disabled or LLM failure."""
    try:
        from ..core.config import load_config

        session = conn.execute("SELECT project_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not session:
            return
        project = conn.execute("SELECT repo_path FROM projects WHERE id = ?", (session["project_id"],)).fetchone()
        if not project:
            return
        config = load_config(project["repo_path"])
        if not config.get("capture", {}).get("intent_summary", False):
            return

        turn_count = conn.execute("SELECT COUNT(*) FROM turns WHERE session_id = ?", (session_id,)).fetchone()[0]
        if turn_count < 3:
            return

        turns = conn.execute(
            "SELECT user_message, assistant_summary FROM turns WHERE session_id = ? ORDER BY turn_number ASC",
            (session_id,),
        ).fetchall()

        from ..core.llm import get_backend
        from ..core.security import filter_secrets

        backend_name = config.get("futures", {}).get("default_backend", "openai")
        model = config.get("futures", {}).get("default_model", None)
        backend = get_backend(backend_name, model=model)

        sec_patterns = config.get("security", {}).get("patterns", None)
        context = "\n".join(
            f"User: {filter_secrets(t['user_message'] or '', sec_patterns)}\n"
            f"Assistant: {filter_secrets(t['assistant_summary'] or '', sec_patterns)}"
            for t in turns[:10]
        )
        system = (
            "Summarize the user's intent and goals from this coding session in 1-2 sentences. "
            "Be specific about what they were trying to accomplish."
        )
        summary = backend.complete(system, context)

        conn.execute("UPDATE sessions SET session_summary = ? WHERE id = ?", (summary[:500], session_id))
        conn.commit()
    except Exception as exc:
        _record_hook_warning(project["repo_path"] if project else "unknown", "intent_summary", exc)


def on_session_end(data: dict[str, Any]) -> None:
    """Handle SessionEnd hook — mark session as ended and update global counts."""
    session_id = data.get("session_id")
    cwd = data.get("cwd", ".")

    if not session_id:
        return

    repo_path = _find_git_root(cwd)
    if not repo_path:
        return

    from ..db import get_db

    conn = get_db(repo_path)
    try:
        now = _now_iso()

        _populate_session_summary(conn, session_id)

        conn.execute(
            "UPDATE sessions SET ended_at = ?, updated_at = ? WHERE id = ?",
            (now, now, session_id),
        )
        conn.commit()

        session_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        turn_count = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
    finally:
        conn.close()

    try:
        from ..db import get_global_db
        from ..db.global_schema import init_global_schema

        gconn = get_global_db()
        try:
            init_global_schema(gconn)
            gconn.execute(
                "UPDATE repo_index SET session_count = ?, turn_count = ? WHERE repo_path = ?",
                (session_count, turn_count, repo_path),
            )
            gconn.commit()
        finally:
            gconn.close()
    except Exception as exc:
        _record_hook_warning(repo_path, "session_end_global_counts", exc)

    _maybe_auto_cleanup_no_changes(repo_path, session_id)
    _maybe_create_auto_checkpoint(repo_path, session_id)
    _maybe_trigger_auto_sync(repo_path)
    _maybe_trigger_auto_distill(repo_path)
    _maybe_trigger_auto_embed(repo_path)
    _maybe_check_stale_decisions(repo_path)
    _maybe_extract_decisions(repo_path, session_id)
    _maybe_infer_ignored_decisions(repo_path, session_id)


def _maybe_infer_ignored_decisions(repo_path: str, session_id: str) -> None:
    """Infer 'ignored' outcome for decisions surfaced but never acted on. Config-gated."""
    try:
        from ..core.config import load_config

        config = load_config(repo_path)
        decisions_config = config.get("decisions", {})
        if not decisions_config.get("infer_ignored_on_session_end", False):
            return

        min_turn_gap = decisions_config.get("ignored_inference_min_turn_gap", 2)

        from ..core.decisions import record_decision_outcome
        from ..db import get_db

        conn = get_db(repo_path)
        try:
            max_turn = conn.execute(
                "SELECT MAX(turn_number) FROM turns WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0] or 0

            rows = conn.execute(
                """
                SELECT rs.id AS selection_id, rs.result_id AS decision_id,
                       rs.turn_id, t.turn_number
                FROM retrieval_selections rs
                LEFT JOIN turns t ON t.id = rs.turn_id
                WHERE rs.session_id = ?
                  AND rs.result_type = 'decision'
                  AND NOT EXISTS (
                      SELECT 1 FROM decision_outcomes do
                      WHERE do.decision_id = rs.result_id
                        AND do.session_id = ?
                  )
                """,
                (session_id, session_id),
            ).fetchall()

            for row in rows:
                turn_number = row["turn_number"] or 0
                if max_turn - turn_number < min_turn_gap:
                    continue
                try:
                    record_decision_outcome(
                        conn,
                        row["decision_id"],
                        outcome_type="ignored",
                        retrieval_selection_id=row["selection_id"],
                        session_id=session_id,
                        turn_id=row["turn_id"],
                        note="auto: session_end inference",
                    )
                except Exception:
                    pass
        finally:
            conn.close()
    except Exception as exc:
        _record_hook_warning(repo_path, "infer_ignored_decisions", exc)


def _session_has_change_signals(conn, session_id: str) -> bool:
    """Return True when session has any signal that implies code changes."""
    files_touched = conn.execute(
        """
        SELECT 1 FROM turns
        WHERE session_id = ?
          AND files_touched IS NOT NULL
          AND TRIM(files_touched) NOT IN ('', '[]')
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    if files_touched:
        return True

    commit_hash = conn.execute(
        """
        SELECT 1 FROM turns
        WHERE session_id = ?
          AND git_commit_hash IS NOT NULL
          AND TRIM(git_commit_hash) != ''
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    if commit_hash:
        return True

    checkpoint = conn.execute("SELECT 1 FROM checkpoints WHERE session_id = ? LIMIT 1", (session_id,)).fetchone()
    return checkpoint is not None


def _maybe_auto_cleanup_no_changes(repo_path: str, session_id: str) -> None:
    """Consolidate turn content for ended sessions that have no code-change signals."""
    try:
        from ..core.config import load_config
        from ..core.consolidation import consolidate_old_turns
        from ..db import get_db

        config = load_config(repo_path)
        if not config.get("capture", {}).get("auto_cleanup_no_changes", False):
            return

        conn = get_db(repo_path)
        try:
            session = conn.execute("SELECT ended_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not session or session["ended_at"] is None:
                return
            if _session_has_change_signals(conn, session_id):
                return
            consolidate_old_turns(conn, repo_path, before_date="9999-12-31", session_id=session_id, dry_run=False)
        finally:
            conn.close()
    except Exception as exc:
        _record_hook_warning(repo_path, "auto_cleanup_no_changes", exc)


def _maybe_create_auto_checkpoint(repo_path: str, session_id: str) -> None:
    """Auto-create checkpoint on session end if enabled. Never crashes the hook."""
    try:
        from ..core.config import load_config

        config = load_config(repo_path)
        if not config.get("capture", {}).get("checkpoint_on_session_end", False):
            return

        import json

        from ..core.checkpoint import create_checkpoint, list_checkpoints
        from ..core.git_utils import get_current_branch, get_current_commit, get_diff_stat
        from ..db import get_db

        git_commit = get_current_commit(repo_path)
        if not git_commit:
            return

        git_branch = get_current_branch(repo_path)
        conn = get_db(repo_path)
        try:
            prev_checkpoints = list_checkpoints(conn, session_id=session_id, limit=1)
            if prev_checkpoints:
                from_commit = prev_checkpoints[0]["git_commit_hash"]
            else:
                from_commit = None
                session_row = conn.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
                if session_row and session_row["metadata"]:
                    try:
                        meta = json.loads(session_row["metadata"])
                        from_commit = meta.get("start_git_commit")
                    except Exception:
                        pass

            diff_summary = get_diff_stat(repo_path, from_commit=from_commit)

            create_checkpoint(
                conn,
                session_id=session_id,
                git_commit_hash=git_commit,
                git_branch=git_branch,
                diff_summary=diff_summary,
                metadata={"source": "auto_session_end"},
            )
        finally:
            conn.close()
    except Exception as exc:
        _record_hook_warning(repo_path, "auto_checkpoint", exc)


def on_post_commit(data: dict[str, Any]) -> None:
    """Handle PostCommit hook — create checkpoint for active session. Never crashes."""
    repo_path = data.get("cwd", ".")
    try:
        cwd = data.get("cwd", ".")
        repo_path = _find_git_root(cwd)
        if not repo_path:
            return

        import json

        from ..core.checkpoint import create_checkpoint, list_checkpoints
        from ..core.git_utils import get_current_branch, get_current_commit, get_diff_stat
        from ..core.session import get_current_session
        from ..db import get_db

        git_commit = get_current_commit(repo_path)
        if not git_commit:
            return

        conn = get_db(repo_path)
        try:
            session = get_current_session(conn)
            if not session:
                return

            session_id = session["id"]
            git_branch = get_current_branch(repo_path)

            prev_checkpoints = list_checkpoints(conn, session_id=session_id, limit=1)
            if prev_checkpoints:
                from_commit = prev_checkpoints[0]["git_commit_hash"]
            else:
                from_commit = None
                session_meta = session.get("metadata")
                if session_meta:
                    try:
                        meta = json.loads(session_meta) if isinstance(session_meta, str) else session_meta
                        from_commit = meta.get("start_git_commit")
                    except Exception:
                        pass

            diff_summary = get_diff_stat(repo_path, from_commit=from_commit)

            create_checkpoint(
                conn,
                session_id=session_id,
                git_commit_hash=git_commit,
                git_branch=git_branch,
                diff_summary=diff_summary,
                metadata={"source": "post_commit"},
            )
        finally:
            conn.close()
    except Exception as exc:
        _record_hook_warning(repo_path, "post_commit", exc)


def _maybe_trigger_auto_embed(repo_path: str) -> None:
    """Trigger background embedding indexing if auto_embed is enabled. Never crashes the hook."""
    try:
        from ..core.config import load_config

        config = load_config(repo_path)
        if not config.get("index", {}).get("auto_embed", False):
            return

        import sys

        from ..core.async_worker import launch_worker, worker_status

        if worker_status(repo_path).get("running"):
            return
        launch_worker(repo_path, [sys.executable, "-m", "entirecontext.cli", "index", "rebuild", "--semantic"])
    except Exception as exc:
        _record_hook_warning(repo_path, "auto_embed", exc)


def _maybe_check_stale_decisions(repo_path: str) -> None:
    try:
        from .decision_hooks import maybe_check_stale_decisions

        maybe_check_stale_decisions(repo_path)
    except Exception as exc:
        _record_hook_warning(repo_path, "decision_stale_dispatch", exc)


def _maybe_extract_decisions(repo_path: str, session_id: str) -> None:
    try:
        from .decision_hooks import maybe_extract_decisions

        maybe_extract_decisions(repo_path, session_id)
    except Exception as exc:
        _record_hook_warning(repo_path, "decision_extract_dispatch", exc)


def _maybe_trigger_auto_distill(repo_path: str) -> None:
    """Auto-distill lessons if enabled. Never crashes the hook."""
    try:
        from ..core.futures import auto_distill_lessons

        auto_distill_lessons(repo_path)
    except Exception as exc:
        _record_hook_warning(repo_path, "auto_distill", exc)


def _maybe_trigger_auto_sync(repo_path: str) -> None:
    """Trigger background sync if auto_sync is enabled. Never crashes the hook."""
    try:
        from ..core.config import load_config

        config = load_config(repo_path)
        if not config.get("sync", {}).get("auto_sync", False):
            return
        from ..sync.auto_sync import trigger_background_sync

        trigger_background_sync(repo_path)
    except Exception as exc:
        _record_hook_warning(repo_path, "auto_sync", exc)
