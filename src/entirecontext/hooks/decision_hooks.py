"""Decision-related hook functions — stale detection, extraction, context surfacing."""

from __future__ import annotations

from typing import Any

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
