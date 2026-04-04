"""Decision-related hook functions — stale detection, extraction, context surfacing."""

from __future__ import annotations

import re
import subprocess
from typing import Any

from ..core.async_worker import launch_worker, worker_status
from .session_lifecycle import _find_git_root, _record_hook_warning


def _load_decisions_config(repo_path: str) -> dict:
    from ..core.config import load_config

    config = load_config(repo_path)
    return config.get("decisions", {})


def maybe_check_stale_decisions(repo_path: str) -> None:
    """Auto-detect stale decisions on SessionEnd. Never raises."""
    try:
        config = _load_decisions_config(repo_path)
        if not config.get("auto_stale_check", False):
            return

        from ..core.decisions import check_staleness, list_decisions, update_decision_staleness
        from ..db import get_db

        conn = get_db(repo_path)
        try:
            decisions = list_decisions(conn, staleness_status="fresh", limit=50)
            for d in decisions:
                result = check_staleness(conn, d["id"], repo_path)
                if result["stale"]:
                    update_decision_staleness(conn, d["id"], "stale")
        finally:
            conn.close()
    except Exception as exc:
        _record_hook_warning(repo_path, "auto_stale_check", exc)


def _get_recently_changed_files(repo_path: str) -> list[str]:
    """Get files changed in recent commits. Falls back to git log if both fail, records warning."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~5..HEAD"],
            cwd=repo_path, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [f for f in result.stdout.strip().split("\n") if f]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        result = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:", "-5"],
            cwd=repo_path, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return list({f for f in result.stdout.strip().split("\n") if f})
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    _record_hook_warning(repo_path, "get_recently_changed_files", RuntimeError("both git diff and git log failed"))
    return []


def _format_decision_entry(d: dict, stale: bool = False) -> str:
    id_prefix = d["id"][:8]
    title = d.get("title", "")
    status = "STALE" if stale else d.get("staleness_status", "fresh")
    rationale = d.get("rationale", "") or ""
    rationale_short = rationale[:120] + "..." if len(rationale) > 120 else rationale
    files = ", ".join(d.get("files", [])[:3])
    parts = [f"- [{id_prefix}] {title}"]
    parts.append(f"  Status: {status}")
    if files:
        parts.append(f"  Files: {files}")
    if rationale_short:
        parts.append(f"  Rationale: {rationale_short}")
    return "\n".join(parts)


def on_session_start_decisions(data: dict[str, Any]) -> str | None:
    """Surface related and stale decisions at session start. Never raises."""
    try:
        cwd = data.get("cwd", ".")
        repo_path = _find_git_root(cwd)
        if not repo_path:
            return None

        config = _load_decisions_config(repo_path)
        if not config.get("show_related_on_start", False):
            return None

        from ..core.decisions import get_decision, list_decisions
        from ..db import get_db

        conn = get_db(repo_path)
        try:
            sections = []
            seen_ids: set[str] = set()

            # 1. Recently changed files → linked decisions (DB-level file_path filter)
            changed_files = _get_recently_changed_files(repo_path)
            file_related = []
            if changed_files:
                for f in changed_files:
                    for d in list_decisions(conn, file_path=f, limit=10):
                        if d["id"] not in seen_ids:
                            full = get_decision(conn, d["id"]) or d
                            file_related.append(full)
                            seen_ids.add(d["id"])
                        if len(seen_ids) >= 5:
                            break
                    if len(seen_ids) >= 5:
                        break

                if file_related:
                    entries = [_format_decision_entry(d) for d in file_related[:5]]
                    sections.append(
                        "## Related Decisions\n\n"
                        "The following decisions are linked to recently changed files:\n\n"
                        + "\n\n".join(entries)
                    )

            # 2. Stale decisions
            stale = list_decisions(conn, staleness_status="stale", limit=10)
            stale_new = [d for d in stale if d["id"] not in seen_ids]
            remaining = 5 - len(seen_ids)
            if stale_new and remaining > 0:
                stale_entries = []
                for d in stale_new[:remaining]:
                    full = get_decision(conn, d["id"]) or d
                    stale_entries.append(_format_decision_entry(full, stale=True))
                    seen_ids.add(d["id"])
                sections.append(
                    "## Stale Decisions (action needed)\n\n"
                    + "\n\n".join(stale_entries)
                    + "\n\nConsider updating stale decisions or marking them as superseded."
                )

            # Write fallback file for agents that don't capture stdout
            from pathlib import Path

            fallback_path = Path(repo_path) / ".entirecontext" / "decisions-context.md"
            if sections:
                output = "\n\n".join(sections)
                fallback_path.parent.mkdir(parents=True, exist_ok=True)
                fallback_path.write_text(output, encoding="utf-8")
                return output
            else:
                # Clean up stale fallback file
                if fallback_path.exists():
                    try:
                        fallback_path.unlink()
                    except OSError:
                        pass
                return None
        finally:
            conn.close()
    except Exception as exc:
        try:
            repo_path = _find_git_root(data.get("cwd", "."))
            if repo_path:
                _record_hook_warning(repo_path, "session_start_decisions", exc)
        except Exception:
            pass
        return None


def _session_has_extraction_marker(conn, session_id: str) -> bool:
    row = conn.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row or not row["metadata"]:
        return False
    try:
        import json

        meta = json.loads(row["metadata"])
        return meta.get("decisions_extracted", False) is True
    except (ValueError, TypeError):
        return False


def _summaries_match_keywords(summaries: list[str], keywords: list[str]) -> bool:
    if not keywords:
        return False
    pattern = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
    return any(pattern.search(s) for s in summaries)


def maybe_extract_decisions(repo_path: str, session_id: str) -> None:
    """Launch background decision extraction if keywords match. Never raises."""
    try:
        config = _load_decisions_config(repo_path)
        if not config.get("auto_extract", False):
            return

        from ..db import get_db

        conn = get_db(repo_path)
        try:
            if _session_has_extraction_marker(conn, session_id):
                return

            rows = conn.execute(
                "SELECT assistant_summary FROM turns "
                "WHERE session_id = ? AND assistant_summary IS NOT NULL "
                "ORDER BY turn_number ASC",
                (session_id,),
            ).fetchall()
            summaries = [r["assistant_summary"] for r in rows if r["assistant_summary"]]
            if not summaries:
                return

            keywords = config.get("extract_keywords", [])
            if not _summaries_match_keywords(summaries, keywords):
                return

            if worker_status(repo_path, pid_name="worker-decision").get("running"):
                return

            import sys

            launch_worker(
                repo_path,
                [sys.executable, "-m", "entirecontext.cli", "decision", "extract-from-session", session_id],
                pid_name="worker-decision",
            )
        finally:
            conn.close()
    except Exception as exc:
        _record_hook_warning(repo_path, "auto_extract_decisions", exc)
