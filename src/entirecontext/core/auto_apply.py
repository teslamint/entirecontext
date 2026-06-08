"""SessionEnd auto-apply: infer 'accepted' outcome for decisions with file overlap."""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from .context import transaction
from .decisions import record_decision_outcome
from .telemetry import record_context_application


def _normalize_file_path(p: str, repo_root: str | None = None) -> str:
    """Normalize to relative path: strip repo root prefix, backslashes, and leading './'."""
    p = p.replace("\\", "/")
    if repo_root:
        prefix = repo_root.replace("\\", "/").rstrip("/") + "/"
        if p.startswith(prefix):
            p = p[len(prefix) :]
    if p.startswith("./"):
        p = p[2:]
    return p


def _collect_session_modified_files(
    conn: sqlite3.Connection, session_id: str, repo_path: str | None = None
) -> set[str]:
    """Parse turns.files_touched (JSON array) for the session. Return set of relative file paths."""
    rows = conn.execute(
        """
        SELECT files_touched FROM turns
        WHERE session_id = ?
          AND files_touched IS NOT NULL
          AND TRIM(files_touched) NOT IN ('', '[]')
        """,
        (session_id,),
    ).fetchall()

    repo_root: str | None = None
    if repo_path:
        repo_root = os.path.realpath(repo_path)

    result: set[str] = set()
    for row in rows:
        raw = row["files_touched"]
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                result.update(_normalize_file_path(str(f), repo_root) for f in parsed if f)
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def _detect_overlapping_decisions(
    conn: sqlite3.Connection, session_id: str, repo_path: str | None = None
) -> list[dict[str, Any]]:
    """Pure detection, no writes.

    Query retrieval_selections where result_type='decision',
    no existing outcome in this session, and decision_files overlap with
    modified files. Deduplicate by decision_id (first selection wins by
    turn_number then created_at).
    """
    modified_files = _collect_session_modified_files(conn, session_id, repo_path)
    if not modified_files:
        return []

    rows = conn.execute(
        """
        SELECT rs.id AS selection_id, rs.result_id AS decision_id,
               rs.turn_id, t.turn_number, rs.created_at
        FROM retrieval_selections rs
        JOIN retrieval_events re ON re.id = rs.retrieval_event_id
        LEFT JOIN turns t ON t.id = rs.turn_id
        WHERE rs.session_id = ?
          AND rs.result_type = 'decision'
          AND NOT EXISTS (
              SELECT 1 FROM decision_outcomes do
              WHERE do.decision_id = rs.result_id
                AND do.session_id = ?
          )
        ORDER BY rs.result_id, COALESCE(t.turn_number, 0) ASC, rs.created_at ASC
        """,
        (session_id, session_id),
    ).fetchall()

    seen_decisions: set[str] = set()
    matches: list[dict[str, Any]] = []

    for row in rows:
        decision_id = row["decision_id"]
        if decision_id in seen_decisions:
            continue

        decision_files = conn.execute(
            "SELECT file_path FROM decision_files WHERE decision_id = ?",
            (decision_id,),
        ).fetchall()

        overlap = {_normalize_file_path(r["file_path"]) for r in decision_files} & modified_files
        if not overlap:
            continue

        seen_decisions.add(decision_id)
        matches.append(
            {
                "decision_id": decision_id,
                "selection_id": row["selection_id"],
                "turn_id": row["turn_id"],
                "overlap_files": sorted(overlap),
            }
        )

    return matches


def infer_applied_decisions(
    conn: sqlite3.Connection, session_id: str, *, dry_run: bool = False, repo_path: str | None = None
) -> dict[str, Any]:
    """Infer 'accepted' outcome for decisions whose files were modified this session.

    If dry_run or no matches, return count only. Otherwise atomically write BOTH
    context_application + accepted outcome in ONE transaction per match.
    """
    matches = _detect_overlapping_decisions(conn, session_id, repo_path)

    if dry_run or not matches:
        return {"applied_count": len(matches), "applied_decisions": []}

    applied: list[dict[str, Any]] = []
    for match in matches:
        note = f"auto: session_end file_overlap ({', '.join(match['overlap_files'][:3])})"
        infer_session = session_id
        infer_turn = match["turn_id"]
        if infer_session and not infer_turn:
            infer_session = None
        with transaction(conn):
            record_context_application(
                conn,
                application_type="decision_change",
                selection_id=match["selection_id"],
                session_id=infer_session,
                turn_id=infer_turn,
                note=note,
            )
            record_decision_outcome(
                conn,
                match["decision_id"],
                outcome_type="accepted",
                retrieval_selection_id=match["selection_id"],
                session_id=infer_session,
                turn_id=infer_turn,
                note=note,
            )
        applied.append(match)

    return {"applied_count": len(applied), "applied_decisions": applied}
