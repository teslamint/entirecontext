"""SessionEnd auto-apply: infer outcomes for decisions/lessons with file overlap."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from typing import Any

from .context import transaction
from .decisions import record_decision_outcome
from .telemetry import record_context_application

_MUTATING_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "MultiEdit"})


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
) -> dict[str, set[int]]:
    """Return {relative_file_path: set_of_mutating_turn_numbers}.

    Only includes files from turns where a mutating tool (Edit/Write/NotebookEdit)
    was used, filtering out pure-read turns.
    """
    rows = conn.execute(
        """
        SELECT files_touched, tools_used, turn_number FROM turns
        WHERE session_id = ?
          AND files_touched IS NOT NULL
          AND TRIM(files_touched) NOT IN ('', '[]')
        """,
        (session_id,),
    ).fetchall()

    repo_root: str | None = None
    if repo_path:
        repo_root = os.path.realpath(repo_path)

    result: dict[str, set[int]] = {}
    for row in rows:
        tools_raw = row["tools_used"]
        tools = set(json.loads(tools_raw)) if tools_raw else set()
        if not (tools & _MUTATING_TOOLS):
            continue

        turn_num = row["turn_number"] or 0
        raw = row["files_touched"]
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for f in parsed:
                    if f:
                        path = _normalize_file_path(str(f), repo_root)
                        result.setdefault(path, set()).add(turn_num)
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def _detect_overlapping_decisions(
    conn: sqlite3.Connection, session_id: str, repo_path: str | None = None
) -> list[dict[str, Any]]:
    """Pure detection, no writes.

    Query retrieval_selections where result_type='decision',
    no existing outcome in this session, and decision_files overlap with
    files modified AT OR AFTER the decision was surfaced.
    Deduplicate by decision_id (first selection wins by turn_number then created_at).
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
          AND re.search_type != 'post_tool_use'
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
        repo_root = os.path.realpath(repo_path) if repo_path else None
        decision_paths = {_normalize_file_path(r["file_path"], repo_root) for r in decision_files}

        surfaced_turn = row["turn_number"] or 0
        overlap = {
            path
            for path in decision_paths
            if path in modified_files and any(t >= surfaced_turn for t in modified_files[path])
        }
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


def _detect_overlapping_lessons(
    conn: sqlite3.Connection, session_id: str, repo_path: str | None = None
) -> list[dict[str, Any]]:
    """Detect surfaced lessons/assessments with file overlap. No writes.

    Checks retrieval_selections with result_type IN ('assessment', 'lesson'),
    cross-references with checkpoint files_snapshot, and compares with
    session-modified files. Deduplicates by result_id.
    Skips if a context_application already exists for this selection+session.
    """
    modified_files = _collect_session_modified_files(conn, session_id, repo_path)
    if not modified_files:
        return []

    rows = conn.execute(
        """
        SELECT rs.id AS selection_id, rs.result_id AS assessment_id,
               rs.result_type, rs.turn_id, t.turn_number, rs.created_at
        FROM retrieval_selections rs
        JOIN retrieval_events re ON re.id = rs.retrieval_event_id
        LEFT JOIN turns t ON t.id = rs.turn_id
        WHERE rs.session_id = ?
          AND rs.result_type IN ('assessment', 'lesson')
          AND NOT EXISTS (
              SELECT 1 FROM context_applications ca
              WHERE ca.retrieval_selection_id = rs.id
                AND ca.session_id = ?
          )
        ORDER BY rs.result_id, COALESCE(t.turn_number, 0) ASC, rs.created_at ASC
        """,
        (session_id, session_id),
    ).fetchall()

    seen_assessments: set[str] = set()
    matches: list[dict[str, Any]] = []

    repo_root = os.path.realpath(repo_path) if repo_path else None

    for row in rows:
        assessment_id = row["assessment_id"]
        if assessment_id in seen_assessments:
            continue

        checkpoint_files_row = conn.execute(
            """
            SELECT c.files_snapshot
            FROM assessments a
            JOIN checkpoints c ON c.id = a.checkpoint_id
            WHERE a.id = ?
              AND c.files_snapshot IS NOT NULL
            """,
            (assessment_id,),
        ).fetchone()

        if not checkpoint_files_row:
            continue

        try:
            snapshot = json.loads(checkpoint_files_row["files_snapshot"])
            if isinstance(snapshot, dict):
                lesson_paths = set(snapshot.keys())
            elif isinstance(snapshot, list):
                lesson_paths = {str(p) for p in snapshot if p}
            else:
                continue
        except (json.JSONDecodeError, TypeError):
            continue

        normalized_lesson_paths = {_normalize_file_path(p, repo_root) for p in lesson_paths}

        surfaced_turn = row["turn_number"] or 0
        overlap = {
            path
            for path in normalized_lesson_paths
            if path in modified_files and any(t >= surfaced_turn for t in modified_files[path])
        }
        if not overlap:
            continue

        seen_assessments.add(assessment_id)
        matches.append(
            {
                "assessment_id": assessment_id,
                "selection_id": row["selection_id"],
                "result_type": row["result_type"],
                "turn_id": row["turn_id"],
                "overlap_files": sorted(overlap),
            }
        )

    return matches


def _has_new_decision_with_file_overlap(conn: sqlite3.Connection, session_id: str, decision_id: str) -> bool:
    """Check if a new decision was created during this session with overlapping decision_files."""
    session_row = conn.execute("SELECT created_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not session_row:
        return False

    session_start = session_row["created_at"]

    original_files = {
        r["file_path"]
        for r in conn.execute("SELECT file_path FROM decision_files WHERE decision_id = ?", (decision_id,)).fetchall()
    }
    if not original_files:
        return False

    new_decisions = conn.execute(
        """
        SELECT DISTINCT d.id
        FROM decisions d
        JOIN decision_files df ON df.decision_id = d.id
        WHERE d.created_at >= ?
          AND d.id != ?
        """,
        (session_start, decision_id),
    ).fetchall()

    for row in new_decisions:
        new_files = {
            r["file_path"]
            for r in conn.execute("SELECT file_path FROM decision_files WHERE decision_id = ?", (row["id"],)).fetchall()
        }
        if original_files & new_files:
            return True

    return False


def _classify_diff_pattern(repo_path: str, session_id: str, overlap_files: list[str], conn: sqlite3.Connection) -> str:
    """Classify diff as 'refined' (net additions) or 'replaced' (net deletions).

    Uses git diff --numstat between session start commit and HEAD,
    filtered to overlapping files.
    """
    session_row = conn.execute("SELECT metadata FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not session_row or not session_row["metadata"]:
        return "accepted"

    try:
        metadata = json.loads(session_row["metadata"])
        start_sha = metadata.get("start_git_commit")
    except (json.JSONDecodeError, TypeError):
        return "accepted"

    if not start_sha:
        return "accepted"

    try:
        cmd = ["git", "diff", "--numstat", f"{start_sha}..HEAD", "--"] + overlap_files
        result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return "accepted"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "accepted"

    total_added = 0
    total_deleted = 0
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            try:
                added = int(parts[0]) if parts[0] != "-" else 0
                deleted = int(parts[1]) if parts[1] != "-" else 0
                total_added += added
                total_deleted += deleted
            except ValueError:
                continue

    if total_added == 0 and total_deleted == 0:
        return "accepted"

    if total_added > total_deleted:
        return "refined"
    return "replaced"


def infer_applied_decisions(
    conn: sqlite3.Connection, session_id: str, *, dry_run: bool = False, repo_path: str | None = None
) -> dict[str, Any]:
    """Infer outcomes for decisions and lessons whose files were modified this session."""
    matches = _detect_overlapping_decisions(conn, session_id, repo_path)
    lesson_matches = _detect_overlapping_lessons(conn, session_id, repo_path)

    if dry_run or (not matches and not lesson_matches):
        return {"applied_count": len(matches) + len(lesson_matches), "applied_decisions": []}

    applied: list[dict[str, Any]] = []

    # Layer 2 config gate
    infer_outcome_type = False
    if repo_path:
        try:
            from .config import load_config

            cfg = load_config(repo_path)
            infer_outcome_type = cfg.get("decisions", {}).get("infer_outcome_type", True)
        except Exception:
            pass

    # Decision outcomes — with optional Layer 2 classification
    for match in matches:
        outcome_type = "accepted"
        if infer_outcome_type and repo_path:
            if _has_new_decision_with_file_overlap(conn, session_id, match["decision_id"]):
                outcome_type = _classify_diff_pattern(repo_path, session_id, match["overlap_files"], conn)

        note = f"auto: session_end {outcome_type} ({', '.join(match['overlap_files'][:3])})"
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
                outcome_type=outcome_type,
                retrieval_selection_id=match["selection_id"],
                session_id=infer_session,
                turn_id=infer_turn,
                note=note,
            )
        applied.append(match)

    # Lesson applications (no decision_outcome — assessments aren't decisions)
    for match in lesson_matches:
        note = f"auto: session_end lesson_overlap ({', '.join(match['overlap_files'][:3])})"
        infer_session = session_id
        infer_turn = match["turn_id"]
        if infer_session and not infer_turn:
            infer_session = None
        with transaction(conn):
            record_context_application(
                conn,
                application_type="lesson_applied",
                selection_id=match["selection_id"],
                session_id=infer_session,
                turn_id=infer_turn,
                note=note,
            )
        applied.append(match)

    return {"applied_count": len(applied), "applied_decisions": applied}
