"""Decision domain operations."""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from .context import transaction
from .resolve import escape_like as _escape_like
from .resolve import resolve_assessment_id as _resolve_assessment_id
from .resolve import resolve_checkpoint_id as _resolve_checkpoint_id
from .resolve import resolve_decision_id as _resolve_decision_id


class _UnsetType:
    """Sentinel type for distinguishing 'not provided' from None."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<UNSET>"

    def __bool__(self) -> bool:
        return False


_UNSET = _UnsetType()

VALID_STALENESS = frozenset(("fresh", "stale", "superseded", "contradicted"))
VALID_DECISION_OUTCOME_TYPES = frozenset(("accepted", "ignored", "contradicted"))
# relation_type is part of identity so one decision-assessment pair can keep
# multiple typed links (e.g. informed_by + contradicts) when historically true.
VALID_DECISION_ASSESSMENT_RELATION_TYPES = frozenset(("supports", "informed_by", "contradicts", "supersedes"))

# Max hops walked when resolving a superseded_by_id chain; cycle defense-in-depth.
_SUCCESSOR_CHAIN_DEPTH_CAP = 10

# Auto-promotion threshold: a decision with this many "contradicted" outcomes
# (and more contradicted than accepted) will be automatically promoted to
# staleness_status='contradicted'. Configurable via [decisions] TOML section.
_DEFAULT_AUTO_PROMOTION_CONTRADICTED_THRESHOLD = 2


def _excluded_statuses(
    *,
    include_stale: bool = True,
    include_superseded: bool = False,
    include_contradicted: bool = False,
) -> tuple[str, ...]:
    excluded: list[str] = []
    if not include_stale:
        excluded.append("stale")
    if not include_superseded:
        excluded.append("superseded")
    if not include_contradicted:
        excluded.append("contradicted")
    return tuple(excluded)


def _staleness_sql_predicate(
    *,
    include_stale: bool = True,
    include_superseded: bool = False,
    include_contradicted: bool = False,
    column: str = "staleness_status",
) -> tuple[str, list[str]]:
    """Build a SQL predicate fragment + params for pushdown filtering.

    Returns (predicate, params) where predicate is empty when all statuses pass.
    """
    excluded = _excluded_statuses(
        include_stale=include_stale,
        include_superseded=include_superseded,
        include_contradicted=include_contradicted,
    )
    if not excluded:
        return "", []
    placeholders = ",".join("?" * len(excluded))
    return f"{column} NOT IN ({placeholders})", list(excluded)


def _apply_staleness_policy(
    rows: list[dict[str, Any]],
    *,
    include_stale: bool = True,
    include_superseded: bool = False,
    include_contradicted: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Filter decision rows by staleness policy; return (kept, stats).

    stats shape: {"filtered_count": N, "by_reason": {"stale": x, "superseded": y, "contradicted": z}}
    """
    excluded = set(
        _excluded_statuses(
            include_stale=include_stale,
            include_superseded=include_superseded,
            include_contradicted=include_contradicted,
        )
    )
    if not excluded:
        return rows, {"filtered_count": 0, "by_reason": {}}

    kept: list[dict[str, Any]] = []
    by_reason: dict[str, int] = {}
    for row in rows:
        status = row.get("staleness_status") or "fresh"
        if status in excluded:
            by_reason[status] = by_reason.get(status, 0) + 1
            continue
        kept.append(row)
    return kept, {"filtered_count": sum(by_reason.values()), "by_reason": by_reason}


def _format_allowed(values: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted(values))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _escape_like_contains(value: str) -> str:
    return f"%{_escape_like(value)}%"


def _parse_decision_json_fields(decision: dict[str, Any]) -> dict[str, Any]:
    for json_field in ("rejected_alternatives", "supporting_evidence"):
        raw = decision.get(json_field)
        try:
            decision[json_field] = json.loads(raw) if raw else []
        except (json.JSONDecodeError, TypeError):
            decision[json_field] = []
    return decision


def calculate_decision_quality_score(counts: dict[str, int]) -> float:
    """Calculate a quality score from outcome counts.

    Formula: accepted * 1.0 - ignored * 0.5 - contradicted * 2.0, clamped to [-4, +4].
    Contradictions are penalised heavily; ignored outcomes have mild negative weight.
    """
    raw_score = (
        float(counts.get("accepted", 0))
        - (0.5 * float(counts.get("ignored", 0)))
        - (2.0 * float(counts.get("contradicted", 0)))
    )
    return max(-4.0, min(4.0, raw_score))


def _resolve_outcome_context(
    conn,
    *,
    selection: dict[str, Any] | None,
    session_id: str | None,
    turn_id: str | None,
) -> tuple[str | None, str | None]:
    if (session_id is None) != (turn_id is None):
        raise ValueError("session_id and turn_id must be provided together")

    if session_id is not None and turn_id is not None:
        session_row = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if session_row is None:
            raise ValueError(f"Session '{session_id}' not found")
        row = conn.execute("SELECT session_id FROM turns WHERE id = ?", (turn_id,)).fetchone()
        if row is None:
            raise ValueError(f"Turn '{turn_id}' not found")
        if row["session_id"] != session_id:
            raise ValueError("turn_id does not belong to session_id")
        return session_id, turn_id

    if selection is not None:
        return selection.get("session_id"), selection.get("turn_id")

    return None, None


def create_decision(
    conn,
    title: str,
    rationale: str | None = None,
    scope: str | None = None,
    staleness_status: str = "fresh",
    rejected_alternatives: list[dict[str, Any]] | list[str] | None = None,
    supporting_evidence: list[dict[str, Any]] | list[str] | None = None,
) -> dict:
    if staleness_status not in VALID_STALENESS:
        raise ValueError(
            f"Invalid staleness_status '{staleness_status}'. Must be one of: {_format_allowed(VALID_STALENESS)}"
        )

    decision_id = str(uuid4())
    now = _now_iso()
    rejected_json = json.dumps(rejected_alternatives or [])
    evidence_json = json.dumps(supporting_evidence or [])

    conn.execute(
        """INSERT INTO decisions (
            id, title, rationale, scope, staleness_status,
            rejected_alternatives, supporting_evidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (decision_id, title, rationale, scope, staleness_status, rejected_json, evidence_json, now, now),
    )
    conn.commit()
    return get_decision(conn, decision_id) or {}


def get_decision(conn, decision_id: str) -> dict | None:
    full_id = _resolve_decision_id(conn, decision_id)
    if full_id is None:
        return None

    row = conn.execute("SELECT * FROM decisions WHERE id = ?", (full_id,)).fetchone()
    if row is None:
        return None

    decision = _parse_decision_json_fields(dict(row))

    decision["files"] = [
        r["file_path"]
        for r in conn.execute(
            "SELECT file_path FROM decision_files WHERE decision_id = ? ORDER BY added_at DESC", (full_id,)
        )
    ]
    decision["assessments"] = [
        {
            "assessment_id": r["assessment_id"],
            "relation_type": r["relation_type"],
            "added_at": r["added_at"],
        }
        for r in conn.execute(
            (
                "SELECT assessment_id, relation_type, added_at "
                "FROM decision_assessments WHERE decision_id = ? ORDER BY added_at DESC"
            ),
            (full_id,),
        )
    ]
    decision["quality_summary"] = _get_decision_quality_summary_resolved(conn, full_id)
    decision["recent_outcomes"] = _list_decision_outcomes_resolved(conn, full_id, limit=10)

    # Surface the immediate successor when this decision has been superseded.
    successor_id = decision.get("superseded_by_id")
    if successor_id:
        succ_row = conn.execute("SELECT id, title FROM decisions WHERE id = ?", (successor_id,)).fetchone()
        if succ_row is not None:
            decision["successor"] = {"id": succ_row["id"], "title": succ_row["title"]}

    return decision


def list_decisions(
    conn,
    staleness_status: str | None = None,
    file_path: str | None = None,
    limit: int = 20,
    include_contradicted: bool = False,
) -> list[dict]:
    """List decisions with optional filters.

    include_contradicted: when False, contradicted decisions are excluded at
    the SQL level so downstream callers do not lose fresh/stale/superseded
    results behind a wall of contradicted rows that hit the row-count limit.
    The flag is ignored when `staleness_status` explicitly selects one status.
    """
    if staleness_status and staleness_status not in VALID_STALENESS:
        raise ValueError(
            f"Invalid staleness_status '{staleness_status}'. Must be one of: {_format_allowed(VALID_STALENESS)}"
        )

    query = "SELECT DISTINCT d.* FROM decisions d"
    params: list[Any] = []
    conditions: list[str] = []

    if file_path:
        query += " JOIN decision_files df ON df.decision_id = d.id"
        conditions.append("df.file_path LIKE ? ESCAPE '\\'")
        params.append(_escape_like_contains(file_path))

    if staleness_status:
        conditions.append("d.staleness_status = ?")
        params.append(staleness_status)
    elif not include_contradicted:
        conditions.append("d.staleness_status != 'contradicted'")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY d.updated_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [_parse_decision_json_fields(dict(r)) for r in rows]


def update_decision_staleness(conn, decision_id: str, status: str) -> dict:
    if status not in VALID_STALENESS:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {_format_allowed(VALID_STALENESS)}")

    full_id = _resolve_decision_id(conn, decision_id)
    if full_id is None:
        raise ValueError(f"Decision '{decision_id}' not found")

    now = _now_iso()
    if status == "fresh":
        conn.execute(
            "UPDATE decisions SET staleness_status = ?, auto_promotion_reset_at = ?, updated_at = ? WHERE id = ?",
            (status, now, now, full_id),
        )
    else:
        conn.execute(
            "UPDATE decisions SET staleness_status = ?, updated_at = ? WHERE id = ?",
            (status, now, full_id),
        )
    conn.commit()
    return get_decision(conn, full_id) or {}


def list_decision_outcomes(conn, decision_id: str, limit: int = 20) -> list[dict]:
    full_id = _resolve_decision_id(conn, decision_id)
    if full_id is None:
        raise ValueError(f"Decision '{decision_id}' not found")
    return _list_decision_outcomes_resolved(conn, full_id, limit)


def _list_decision_outcomes_resolved(conn, resolved_id: str, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, decision_id, retrieval_selection_id, session_id, turn_id, outcome_type, note, created_at
        FROM decision_outcomes
        WHERE decision_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (resolved_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def get_decision_quality_summary(conn, decision_id: str) -> dict[str, Any]:
    full_id = _resolve_decision_id(conn, decision_id)
    if full_id is None:
        raise ValueError(f"Decision '{decision_id}' not found")
    return _get_decision_quality_summary_resolved(conn, full_id)


def _get_decision_quality_summary_resolved(conn, resolved_id: str) -> dict[str, Any]:
    counts = {outcome_type: 0 for outcome_type in VALID_DECISION_OUTCOME_TYPES}
    rows = conn.execute(
        """
        SELECT outcome_type, COUNT(*) AS total
        FROM decision_outcomes
        WHERE decision_id = ?
        GROUP BY outcome_type
        """,
        (resolved_id,),
    ).fetchall()
    for row in rows:
        counts[row["outcome_type"]] = row["total"] or 0

    total_outcomes = sum(counts.values())
    return {
        "total_outcomes": total_outcomes,
        "counts": counts,
        "quality_score": calculate_decision_quality_score(counts),
    }


def record_decision_outcome(
    conn,
    decision_id: str,
    outcome_type: str,
    *,
    retrieval_selection_id: str | None = None,
    note: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> dict[str, Any]:
    if outcome_type not in VALID_DECISION_OUTCOME_TYPES:
        raise ValueError(
            f"Invalid outcome_type '{outcome_type}'. Must be one of: {_format_allowed(VALID_DECISION_OUTCOME_TYPES)}"
        )

    full_decision_id = _resolve_decision_id(conn, decision_id)
    if full_decision_id is None:
        raise ValueError(f"Decision '{decision_id}' not found")

    selection = None
    if retrieval_selection_id is not None:
        from .telemetry import get_retrieval_selection

        selection = get_retrieval_selection(conn, retrieval_selection_id)
        if not selection:
            raise ValueError(f"Retrieval selection '{retrieval_selection_id}' not found")
        if selection["result_type"] != "decision":
            raise ValueError("Retrieval selection must point to a decision result")
        if selection["result_id"] != full_decision_id:
            raise ValueError("Retrieval selection decision does not match the requested decision")

    session_id, turn_id = _resolve_outcome_context(
        conn,
        selection=selection,
        session_id=session_id,
        turn_id=turn_id,
    )

    outcome_id = str(uuid4())
    now = _now_iso()

    # Wrap outcome insert + updated_at bump + potential auto-promotion in a single
    # BEGIN IMMEDIATE boundary so concurrent contradicted outcomes can't double-promote
    # or miss the threshold. `transaction()` defers commit/rollback to any outer owner.
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO decision_outcomes (
                id, decision_id, retrieval_selection_id, session_id, turn_id, outcome_type, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (outcome_id, full_decision_id, retrieval_selection_id, session_id, turn_id, outcome_type, note, now),
        )
        conn.execute("UPDATE decisions SET updated_at = ? WHERE id = ?", (now, full_decision_id))

        if outcome_type == "contradicted":
            _maybe_auto_promote_contradicted(conn, full_decision_id, now)

    row = conn.execute(
        """
        SELECT id, decision_id, retrieval_selection_id, session_id, turn_id, outcome_type, note, created_at
        FROM decision_outcomes
        WHERE id = ?
        """,
        (outcome_id,),
    ).fetchone()
    return dict(row) if row else {}


def _maybe_auto_promote_contradicted(conn, full_decision_id: str, now: str) -> None:
    """Promote a decision to staleness_status='contradicted' when usage feedback
    crosses the configured threshold.

    Conditions (all must hold):
    - current status NOT IN ('contradicted', 'superseded')  — one-way ratchet
    - contradicted_count >= threshold
    - contradicted_count > accepted_count
    """
    threshold = _get_auto_promotion_threshold(conn)
    current_row = conn.execute(
        "SELECT staleness_status, auto_promotion_reset_at FROM decisions WHERE id = ?",
        (full_decision_id,),
    ).fetchone()
    if current_row is None:
        return
    current_status = current_row["staleness_status"] or "fresh"
    if current_status in ("contradicted", "superseded"):
        return

    baseline_at = current_row["auto_promotion_reset_at"]
    if baseline_at:
        count_rows = conn.execute(
            """
            SELECT outcome_type, COUNT(*) AS total
            FROM decision_outcomes
            WHERE decision_id = ? AND created_at > ?
            GROUP BY outcome_type
            """,
            (full_decision_id, baseline_at),
        ).fetchall()
    else:
        count_rows = conn.execute(
            "SELECT outcome_type, COUNT(*) AS total FROM decision_outcomes WHERE decision_id = ? GROUP BY outcome_type",
            (full_decision_id,),
        ).fetchall()
    counts = {r["outcome_type"]: r["total"] for r in count_rows}
    contradicted_count = counts.get("contradicted", 0)
    accepted_count = counts.get("accepted", 0)

    if contradicted_count >= threshold and contradicted_count > accepted_count:
        conn.execute(
            "UPDATE decisions SET staleness_status = 'contradicted', updated_at = ? WHERE id = ?",
            (now, full_decision_id),
        )


def _infer_repo_path_from_conn(conn) -> str | None:
    """Best-effort extraction of the repo root from the SQLite connection.

    EntireContext stores per-repo DBs at `<repo>/.entirecontext/db/local.db`,
    so walking two levels up from the main database file recovers the repo.
    Returns None for the global DB or any connection we cannot map.
    """
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
    except sqlite3.Error:
        return None
    for row in rows:
        name = row["name"]
        file_path = row["file"]
        if name != "main" or not file_path:
            continue
        db_path = Path(file_path)
        parts = db_path.parts
        if len(parts) >= 3 and parts[-3] == ".entirecontext" and parts[-2] == "db":
            return str(db_path.parent.parent.parent)
        return None
    return None


def _get_auto_promotion_threshold(conn=None) -> int:
    """Read threshold from [decisions] config section with sensible fallback.

    When a connection is supplied, load the repo-scoped config so
    `.entirecontext/config.toml` values take precedence over global defaults.
    """
    try:
        from .config import load_config

        repo_path = _infer_repo_path_from_conn(conn) if conn is not None else None
        cfg = load_config(repo_path)
        decisions_cfg = cfg.get("decisions", {}) if isinstance(cfg, dict) else {}
        raw = decisions_cfg.get("auto_promotion_contradicted_threshold")
        if isinstance(raw, int) and raw >= 1:
            return raw
    except Exception:
        pass
    return _DEFAULT_AUTO_PROMOTION_CONTRADICTED_THRESHOLD


def link_decision_to_assessment(conn, decision_id: str, assessment_id: str, relation_type: str = "supports") -> dict:
    if relation_type not in VALID_DECISION_ASSESSMENT_RELATION_TYPES:
        raise ValueError(
            "Invalid relation_type "
            f"'{relation_type}'. Must be one of: {_format_allowed(VALID_DECISION_ASSESSMENT_RELATION_TYPES)}"
        )

    full_decision_id = _resolve_decision_id(conn, decision_id)
    if full_decision_id is None:
        raise ValueError(f"Decision '{decision_id}' not found")

    full_assessment_id = _resolve_assessment_id(conn, assessment_id)
    if full_assessment_id is None:
        raise ValueError(f"Assessment '{assessment_id}' not found")

    conn.execute(
        # Duplicate inserts for the same typed link are ignored, while the same
        # decision-assessment pair may coexist with additional relation types.
        """INSERT OR IGNORE INTO decision_assessments (decision_id, assessment_id, relation_type)
        VALUES (?, ?, ?)""",
        (full_decision_id, full_assessment_id, relation_type),
    )
    conn.execute("UPDATE decisions SET updated_at = ? WHERE id = ?", (_now_iso(), full_decision_id))
    conn.commit()
    row = conn.execute(
        (
            "SELECT decision_id, assessment_id, relation_type, added_at "
            "FROM decision_assessments WHERE decision_id = ? AND assessment_id = ? AND relation_type = ?"
        ),
        (full_decision_id, full_assessment_id, relation_type),
    ).fetchone()
    return dict(row) if row else {}


def link_decision_to_file(conn, decision_id: str, file_path: str) -> dict:
    full_decision_id = _resolve_decision_id(conn, decision_id)
    if full_decision_id is None:
        raise ValueError(f"Decision '{decision_id}' not found")

    conn.execute(
        "INSERT OR IGNORE INTO decision_files (decision_id, file_path) VALUES (?, ?)",
        (full_decision_id, file_path),
    )
    conn.execute("UPDATE decisions SET updated_at = ? WHERE id = ?", (_now_iso(), full_decision_id))
    conn.commit()
    row = conn.execute(
        "SELECT decision_id, file_path, added_at FROM decision_files WHERE decision_id = ? AND file_path = ?",
        (full_decision_id, file_path),
    ).fetchone()
    return dict(row) if row else {}


def link_decision_to_commit(conn, decision_id: str, commit_sha: str) -> dict:
    full_decision_id = _resolve_decision_id(conn, decision_id)
    if full_decision_id is None:
        raise ValueError(f"Decision '{decision_id}' not found")

    conn.execute(
        "INSERT OR IGNORE INTO decision_commits (decision_id, commit_sha) VALUES (?, ?)",
        (full_decision_id, commit_sha),
    )
    conn.execute("UPDATE decisions SET updated_at = ? WHERE id = ?", (_now_iso(), full_decision_id))
    conn.commit()
    row = conn.execute(
        "SELECT decision_id, commit_sha, added_at FROM decision_commits WHERE decision_id = ? AND commit_sha = ?",
        (full_decision_id, commit_sha),
    ).fetchone()
    return dict(row) if row else {}


def link_decision_to_checkpoint(conn, decision_id: str, checkpoint_id: str) -> dict:
    full_decision_id = _resolve_decision_id(conn, decision_id)
    if full_decision_id is None:
        raise ValueError(f"Decision '{decision_id}' not found")

    full_checkpoint_id = _resolve_checkpoint_id(conn, checkpoint_id)
    if full_checkpoint_id is None:
        raise ValueError(f"Checkpoint '{checkpoint_id}' not found")

    conn.execute(
        "INSERT OR IGNORE INTO decision_checkpoints (decision_id, checkpoint_id) VALUES (?, ?)",
        (full_decision_id, full_checkpoint_id),
    )
    conn.execute("UPDATE decisions SET updated_at = ? WHERE id = ?", (_now_iso(), full_decision_id))
    conn.commit()
    row = conn.execute(
        (
            "SELECT decision_id, checkpoint_id, added_at "
            "FROM decision_checkpoints WHERE decision_id = ? AND checkpoint_id = ?"
        ),
        (full_decision_id, full_checkpoint_id),
    ).fetchone()
    return dict(row) if row else {}


def update_decision(
    conn,
    decision_id: str,
    title: str | None | _UnsetType = _UNSET,
    rationale: str | None | _UnsetType = _UNSET,
    scope: str | None | _UnsetType = _UNSET,
    rejected_alternatives: list | None | _UnsetType = _UNSET,
    supporting_evidence: list | None | _UnsetType = _UNSET,
) -> dict:
    full_id = _resolve_decision_id(conn, decision_id)
    if full_id is None:
        raise ValueError(f"Decision '{decision_id}' not found")

    updates: list[str] = []
    params: list[Any] = []

    if title is not _UNSET:
        updates.append("title = ?")
        params.append(title)
    if rationale is not _UNSET:
        updates.append("rationale = ?")
        params.append(rationale)
    if scope is not _UNSET:
        updates.append("scope = ?")
        params.append(scope)
    if rejected_alternatives is not _UNSET:
        updates.append("rejected_alternatives = ?")
        params.append(json.dumps(rejected_alternatives or []))
    if supporting_evidence is not _UNSET:
        updates.append("supporting_evidence = ?")
        params.append(json.dumps(supporting_evidence or []))

    if not updates:
        return get_decision(conn, full_id) or {}

    updates.append("updated_at = ?")
    params.append(_now_iso())
    params.append(full_id)

    conn.execute(f"UPDATE decisions SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    return get_decision(conn, full_id) or {}


def resolve_successor_chain(conn, decision_id: str) -> tuple[str, str]:
    """Walk superseded_by_id to the terminal decision.

    Returns (terminal_id, terminal_staleness_status). If the decision is not
    superseded, returns itself. Depth cap prevents runaway cycles.

    The loop counter walks one node past the nominal depth cap so a chain
    of length exactly `cap + 1` nodes (cap hops) resolves cleanly instead of
    exiting one hop early with the penultimate node as a misreported terminal.
    """
    full_id = _resolve_decision_id(conn, decision_id)
    if full_id is None:
        raise ValueError(f"Decision '{decision_id}' not found")

    current_id = full_id
    visited: set[str] = set()
    for _ in range(_SUCCESSOR_CHAIN_DEPTH_CAP + 1):
        if current_id in visited:
            break
        visited.add(current_id)
        row = conn.execute(
            "SELECT superseded_by_id, staleness_status FROM decisions WHERE id = ?",
            (current_id,),
        ).fetchone()
        if row is None:
            break
        successor = row["superseded_by_id"]
        status = row["staleness_status"] or "fresh"
        if not successor:
            return current_id, status
        current_id = successor
    # Hit depth cap without finding a terminal node. Return the current node's
    # status as best-effort terminal; chains deeper than the cap intentionally
    # drop downstream (treated as superseded / unresolved).
    row = conn.execute("SELECT staleness_status FROM decisions WHERE id = ?", (current_id,)).fetchone()
    return current_id, (row["staleness_status"] if row else "fresh")


def supersede_decision(conn, old_decision_id: str, new_decision_id: str) -> dict:
    old_full = _resolve_decision_id(conn, old_decision_id)
    if old_full is None:
        raise ValueError(f"Decision '{old_decision_id}' not found")

    new_full = _resolve_decision_id(conn, new_decision_id)
    if new_full is None:
        raise ValueError(f"Decision '{new_decision_id}' not found")

    if old_full == new_full:
        raise ValueError("A decision cannot supersede itself")

    with transaction(conn):
        probe_id: str | None = new_full
        visited: set[str] = {old_full}
        while probe_id is not None:
            if probe_id in visited:
                raise ValueError(
                    f"Supersession would create a cycle: decision '{old_full}' already appears in the successor chain of '{new_full}'"
                )
            visited.add(probe_id)
            row = conn.execute("SELECT superseded_by_id FROM decisions WHERE id = ?", (probe_id,)).fetchone()
            probe_id = row["superseded_by_id"] if row else None

        now = _now_iso()
        conn.execute(
            "UPDATE decisions SET staleness_status = 'superseded', superseded_by_id = ?, updated_at = ? WHERE id = ?",
            (new_full, now, old_full),
        )
    return get_decision(conn, old_full) or {}


def unlink_decision_from_file(conn, decision_id: str, file_path: str) -> bool:
    full_id = _resolve_decision_id(conn, decision_id)
    if full_id is None:
        return False
    cursor = conn.execute("DELETE FROM decision_files WHERE decision_id = ? AND file_path = ?", (full_id, file_path))
    conn.commit()
    return cursor.rowcount > 0


def unlink_decision_from_commit(conn, decision_id: str, commit_sha: str) -> bool:
    full_id = _resolve_decision_id(conn, decision_id)
    if full_id is None:
        return False
    cursor = conn.execute(
        "DELETE FROM decision_commits WHERE decision_id = ? AND commit_sha = ?", (full_id, commit_sha)
    )
    conn.commit()
    return cursor.rowcount > 0


def unlink_decision_from_assessment(
    conn, decision_id: str, assessment_id: str, relation_type: str = "supports"
) -> bool:
    full_decision_id = _resolve_decision_id(conn, decision_id)
    full_assessment_id = _resolve_assessment_id(conn, assessment_id)
    if full_decision_id is None or full_assessment_id is None:
        return False
    cursor = conn.execute(
        "DELETE FROM decision_assessments WHERE decision_id = ? AND assessment_id = ? AND relation_type = ?",
        (full_decision_id, full_assessment_id, relation_type),
    )
    conn.commit()
    return cursor.rowcount > 0


def unlink_decision_from_checkpoint(conn, decision_id: str, checkpoint_id: str) -> bool:
    full_decision_id = _resolve_decision_id(conn, decision_id)
    full_checkpoint_id = _resolve_checkpoint_id(conn, checkpoint_id)
    if full_decision_id is None or full_checkpoint_id is None:
        return False
    cursor = conn.execute(
        "DELETE FROM decision_checkpoints WHERE decision_id = ? AND checkpoint_id = ?",
        (full_decision_id, full_checkpoint_id),
    )
    conn.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Ranking helpers
# ---------------------------------------------------------------------------

_STALENESS_FACTORS: dict[str, float] = {
    "fresh": 1.0,
    "stale": 0.85,
    "superseded": 0.5,
    "contradicted": 0.25,
}

_ASSESSMENT_RELATION_WEIGHTS: dict[str, float] = {
    "supports": 4.0,
    "informed_by": 4.0,
    "contradicts": 5.0,
    "supersedes": 3.0,
}


@dataclass(frozen=True)
class RankingWeights:
    """Weights consumed by ``rank_related_decisions``.

    ``[decisions.ranking]`` config overrides merge into these defaults.
    """

    staleness_factors: dict[str, float] = field(default_factory=lambda: dict(_STALENESS_FACTORS))
    assessment_relation_weights: dict[str, float] = field(default_factory=lambda: dict(_ASSESSMENT_RELATION_WEIGHTS))
    file_exact_weight: float = 3.0
    git_commit_weight: float = 3.0
    directory_proximity_cap_levels: int = 3


_DEFAULT_RANKING_WEIGHTS = RankingWeights()


def _coerce_ranking_float(section: dict, key: str, default: float) -> float:
    raw = section.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"decisions.ranking.{key} must be a number, got {raw!r}") from exc


def _coerce_ranking_int(section: dict, key: str, default: int) -> int:
    raw = section.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"decisions.ranking.{key} must be an integer, got {raw!r}") from exc


def _coerce_ranking_weight_map(
    section_name: str, override: dict | None, defaults: dict[str, float]
) -> dict[str, float]:
    """Deep-merge an override map into defaults, coercing each value to ``float``.

    Catches non-numeric map values (quoted numbers, booleans reified as strings,
    lists, etc.) at config-load time with a clear ``decisions.ranking.<section>.<key>``
    error path, instead of letting them slip through and explode later inside
    ranking arithmetic.
    """
    merged = dict(defaults)
    if not override:
        return merged
    for key, raw in override.items():
        try:
            merged[key] = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"decisions.ranking.{section_name}.{key} must be a number, got {raw!r}") from exc
    return merged


def _load_ranking_weights(config: dict | None) -> RankingWeights:
    """Build :class:`RankingWeights` from an ``[decisions.ranking]`` config section.

    Always returns a fresh :class:`RankingWeights` instance — never the
    module-level ``_DEFAULT_RANKING_WEIGHTS`` singleton — so a caller that
    mutates an in-field dict (``weights.staleness_factors['fresh'] = 999``)
    cannot contaminate subsequent calls. ``frozen=True`` on the dataclass
    only protects attribute reassignment, not the referenced dict contents.
    """
    if not config:
        return RankingWeights()
    section = (config.get("decisions") or {}).get("ranking") or {}
    if not section:
        return RankingWeights()

    return RankingWeights(
        staleness_factors=_coerce_ranking_weight_map(
            "staleness_factors", section.get("staleness_factors"), _STALENESS_FACTORS
        ),
        assessment_relation_weights=_coerce_ranking_weight_map(
            "assessment_relation_weights",
            section.get("assessment_relation_weights"),
            _ASSESSMENT_RELATION_WEIGHTS,
        ),
        file_exact_weight=_coerce_ranking_float(
            section, "file_exact_weight", _DEFAULT_RANKING_WEIGHTS.file_exact_weight
        ),
        git_commit_weight=_coerce_ranking_float(
            section, "git_commit_weight", _DEFAULT_RANKING_WEIGHTS.git_commit_weight
        ),
        directory_proximity_cap_levels=_coerce_ranking_int(
            section, "directory_proximity_cap_levels", _DEFAULT_RANKING_WEIGHTS.directory_proximity_cap_levels
        ),
    )


_CODE_STOPWORDS: frozenset[str] = frozenset(
    {
        "function",
        "return",
        "class",
        "import",
        "const",
        "null",
        "true",
        "false",
        "test",
        "self",
        "def",
        "var",
        "let",
        "src",
        "none",
        "this",
        "from",
        "async",
        "await",
        "yield",
        "with",
        "elif",
        "else",
        "pass",
        "raise",
        "except",
        "finally",
        "try",
        "for",
        "while",
        "break",
        "continue",
    }
)

_FALLBACK_RECENT_COUNT = 20
_MIN_CANDIDATE_THRESHOLD = 5


def _normalize_path(path: str) -> str:
    """Normalize a file path for consistent matching."""
    p = path.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def _directory_proximity_score(path_a: str, path_b: str, cap_levels: int = 3) -> float:
    """Score directory proximity between two file paths.

    Same directory = 1.5, parent = 0.75, grandparent = 0.375 (halves per level,
    truncated to zero beyond ``cap_levels``). Returns 0.0 if paths share no
    directory components.
    """
    parts_a = PurePosixPath(_normalize_path(path_a)).parts[:-1]
    parts_b = PurePosixPath(_normalize_path(path_b)).parts[:-1]
    if not parts_a or not parts_b:
        return 0.0
    shared = 0
    for a, b in zip(parts_a, parts_b):
        if a != b:
            break
        shared += 1
    if shared == 0:
        return 0.0
    depth_from_match = max(len(parts_a), len(parts_b)) - shared
    if depth_from_match > cap_levels:
        return 0.0
    return 1.5 * (0.5**depth_from_match)


def _tokenize_diff_for_fts(diff_text: str, max_tokens: int = 30) -> str | None:
    """Extract meaningful tokens from diff text for FTS5 query.

    Only processes added/removed lines. Filters code stopwords,
    numeric-only tokens, and short tokens. Returns an FTS5 OR query
    or None if too few tokens remain.
    """
    if not diff_text:
        return None
    text = diff_text[:5000]
    tokens: dict[str, int] = {}
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped:
            continue
        # Skip diff metadata
        if stripped.startswith(("@@", "---", "+++", "diff --git")):
            continue
        # Prefer added/removed lines; fall back to all lines for plain-text input
        if stripped.startswith(("+", "-")):
            content = stripped[1:].strip()
        else:
            content = stripped
        # Split camelCase and snake_case
        parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)|[a-z]+", content)
        words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", content)
        all_tokens = {t.lower() for t in parts + words}
        for t in all_tokens:
            if len(t) < 3:
                continue
            if t in _CODE_STOPWORDS:
                continue
            if re.fullmatch(r"[0-9a-f]+", t):
                continue
            tokens[t] = tokens.get(t, 0) + 1

    if len(tokens) < 2:
        return None
    sorted_tokens = sorted(tokens, key=tokens.__getitem__, reverse=True)[:max_tokens]
    # Quote tokens that could conflict with FTS5 syntax
    safe = []
    for t in sorted_tokens:
        if t.upper() in ("AND", "OR", "NOT", "NEAR"):
            safe.append(f'"{t}"')
        else:
            safe.append(t)
    return " OR ".join(safe)


def _fts_rank_decisions_from_diff(conn, diff_text: str, limit: int = 50) -> dict[str, float]:
    """Search fts_decisions with tokenized diff text and return normalized relevance scores.

    Returns {decision_id: score} where score is in [0.0, 4.0].
    """
    fts_query = _tokenize_diff_for_fts(diff_text)
    if fts_query is None:
        return {}
    try:
        rows = conn.execute(
            "SELECT rowid, rank FROM fts_decisions WHERE fts_decisions MATCH ? ORDER BY rank LIMIT ?",
            (fts_query, limit),
        ).fetchall()
    except Exception:
        return {}
    if not rows:
        return {}
    # Map rowid back to decision id
    rowids = [r["rowid"] for r in rows]
    placeholders = ",".join("?" for _ in rowids)
    id_rows = conn.execute(
        f"SELECT rowid, id FROM decisions WHERE rowid IN ({placeholders})",  # noqa: S608
        rowids,
    ).fetchall()
    rowid_to_id = {r["rowid"]: r["id"] for r in id_rows}

    # FTS5 rank is negative (more negative = better match); normalize to [0, 4]
    raw_scores = {r["rowid"]: -r["rank"] for r in rows}
    max_score = max(raw_scores.values()) if raw_scores else 1.0
    min_score = min(raw_scores.values()) if raw_scores else 0.0

    result: dict[str, float] = {}
    if max_score == min_score:
        for rowid in raw_scores:
            did = rowid_to_id.get(rowid)
            if did:
                result[did] = 2.0
    else:
        score_range = max_score - min_score
        for rowid, raw in raw_scores.items():
            did = rowid_to_id.get(rowid)
            if did:
                # Floor at 0.5 so the weakest FTS hit still contributes signal
                result[did] = 0.5 + 3.5 * (raw - min_score) / score_range
    return result


def _gather_candidates_by_files(conn, file_paths: list[str], cap_levels: int = 3) -> set[str]:
    """Find decision IDs linked to the given files or sharing a parent directory.

    ``cap_levels`` mirrors :func:`_directory_proximity_score`'s cap so candidate
    collection scales with the configured ``directory_proximity_cap_levels``.
    Passing a value larger than 3 only matters if the scorer cap is also raised.
    """
    if not file_paths:
        return set()
    candidates: set[str] = set()
    normalized = [_normalize_path(p) for p in file_paths]

    # Exact file matches — normalize stored paths at query time to handle ./prefix and backslashes
    # so stored values like "./src/foo.py" or "src\foo.py" match normalized inputs.
    placeholders = ",".join("?" for _ in normalized)
    rows = conn.execute(
        f"SELECT DISTINCT decision_id FROM decision_files"  # noqa: S608
        f" WHERE REPLACE(CASE WHEN file_path LIKE './%' THEN SUBSTR(file_path, 3) ELSE file_path END, '\\', '/') IN ({placeholders})",
        normalized,
    ).fetchall()
    candidates.update(r["decision_id"] for r in rows)

    # Ancestor directory matches — must match the scorer's proximity cap so a
    # configured higher cap actually pulls deeper siblings into the candidate
    # pool rather than silently filtering them.
    ancestor_levels = max(0, cap_levels) + 1
    ancestor_dirs: set[str] = set()
    for p in normalized:
        parts = PurePosixPath(p).parts[:-1]  # directory components, excluding filename
        for depth in range(min(len(parts), ancestor_levels)):
            ancestor_parts = parts[: len(parts) - depth]
            ancestor = str(PurePosixPath(*ancestor_parts))
            if ancestor and ancestor != ".":
                ancestor_dirs.add(ancestor)
    for ancestor_dir in ancestor_dirs:
        escaped = _escape_like(ancestor_dir)
        rows = conn.execute(
            "SELECT DISTINCT decision_id FROM decision_files"
            " WHERE REPLACE(CASE WHEN file_path LIKE './%' THEN SUBSTR(file_path, 3)"
            " ELSE file_path END, '\\', '/') LIKE ? ESCAPE '\\'",
            (f"{escaped}/%",),
        ).fetchall()
        candidates.update(r["decision_id"] for r in rows)
    return candidates


def _gather_candidates_by_commits(conn, commit_shas: list[str]) -> set[str]:
    """Find decision IDs linked to the given commit SHAs."""
    if not commit_shas:
        return set()
    placeholders = ",".join("?" for _ in commit_shas)
    rows = conn.execute(
        f"SELECT DISTINCT decision_id FROM decision_commits WHERE commit_sha IN ({placeholders})",  # noqa: S608
        commit_shas,
    ).fetchall()
    return {r["decision_id"] for r in rows}


def rank_related_decisions(
    conn,
    *,
    file_paths: list[str] | None = None,
    assessment_ids: list[str] | None = None,
    diff_text: str | None = None,
    commit_shas: list[str] | None = None,
    limit: int = 10,
    include_stale: bool = True,
    include_superseded: bool = False,
    include_contradicted: bool = False,
    ranking: RankingWeights | None = None,
    _return_stats: bool = False,
) -> list[dict] | tuple[list[dict], dict]:
    """Rank decisions by current-change relevance using multi-signal scoring.

    Candidate-first architecture: gathers candidate decisions from each signal
    source (files, assessments, diff FTS5, commits), then scores the union.

    Signals:
    - file_exact: +3.0 per exact file match
    - file_proximity: +1.5/0.75/0.375 for directory proximity (same/parent/grandparent)
    - assessment: +3.0 to +5.0 per assessment match (max weight per assessment_id)
    - diff_relevance: 0.0-4.0 from FTS5 match of diff text against title/rationale
    - git_commit: +3.0 per matching commit SHA
    - quality: from outcome tracking (accepted/ignored/contradicted), capped [-4, +4]
    - staleness_factor: multiplicative on base_score only (fresh=1.0, stale=0.85, etc.)

    Score formula: score = base_score * staleness_factor + quality_score

    Staleness policy:
    - By default, excludes superseded and contradicted decisions. Stale passes through
      (with multiplicative demotion via _STALENESS_FACTORS).
    - Superseded candidates are collapsed to their terminal successor when that
      successor passes the filter; otherwise the entire chain is dropped.
    - Set _return_stats=True to get (results, filter_stats).
    """
    weights = ranking if ranking is not None else _DEFAULT_RANKING_WEIGHTS
    file_paths = [_normalize_path(p) for p in (file_paths or [])]
    assessment_ids = assessment_ids or []
    commit_shas = commit_shas or []

    # --- 1. Gather candidates from each signal source ---
    candidate_ids: set[str] = set()
    candidate_ids |= _gather_candidates_by_files(conn, file_paths, cap_levels=weights.directory_proximity_cap_levels)
    candidate_ids |= _gather_candidates_by_commits(conn, commit_shas)

    resolved_assessment_ids: set[str] = set()
    for aid in assessment_ids:
        full_id = _resolve_assessment_id(conn, aid)
        if full_id:
            resolved_assessment_ids.add(full_id)
    if resolved_assessment_ids:
        placeholders = ",".join("?" for _ in resolved_assessment_ids)
        rows = conn.execute(
            f"SELECT DISTINCT decision_id FROM decision_assessments WHERE assessment_id IN ({placeholders})",  # noqa: S608
            list(resolved_assessment_ids),
        ).fetchall()
        candidate_ids.update(r["decision_id"] for r in rows)

    diff_fts_scores: dict[str, float] = {}
    if diff_text:
        diff_fts_scores = _fts_rank_decisions_from_diff(conn, diff_text)
        candidate_ids.update(diff_fts_scores.keys())

    # Fallback: if too few candidates, pad with recent decisions.
    # Apply staleness predicate at the SQL level so the padding path can't smuggle in
    # superseded/contradicted entries.
    if len(candidate_ids) < _MIN_CANDIDATE_THRESHOLD:
        pad_predicate, pad_params = _staleness_sql_predicate(
            include_stale=include_stale,
            include_superseded=include_superseded,
            include_contradicted=include_contradicted,
        )
        pad_where = f"WHERE {pad_predicate}" if pad_predicate else ""
        pad_sql = f"SELECT id FROM decisions {pad_where} ORDER BY updated_at DESC LIMIT ?"  # noqa: S608
        recent = conn.execute(pad_sql, [*pad_params, _FALLBACK_RECENT_COUNT]).fetchall()
        candidate_ids.update(r["id"] for r in recent)

    filter_stats: dict[str, Any] = {"filtered_count": 0, "by_reason": {}}

    def _bump_stat(reason: str, n: int = 1) -> None:
        filter_stats["by_reason"][reason] = filter_stats["by_reason"].get(reason, 0) + n
        filter_stats["filtered_count"] += n

    if not candidate_ids:
        return ([], filter_stats) if _return_stats else []

    # --- 2. Bulk-fetch decision data ---
    id_list = list(candidate_ids)
    placeholders = ",".join("?" for _ in id_list)
    decisions_raw = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM decisions WHERE id IN ({placeholders})",  # noqa: S608
            id_list,
        ).fetchall()
    ]
    if not decisions_raw:
        return ([], filter_stats) if _return_stats else []

    # --- 2a. Apply central staleness policy + chain collapse ---
    decisions_by_id = {d["id"]: d for d in decisions_raw}
    # Map each surviving terminal to the set of ancestor ids that collapsed into it.
    # Signals (file/assessment/commit/diff) from ancestors are later unioned onto the
    # terminal so an A→B collapse doesn't drop A's matched file/assessment evidence
    # when B has not yet been relinked. Fixes #55 review P1.
    chain_ancestors: dict[str, set[str]] = {}

    # First pass: apply filter, track what was removed
    kept_ids: set[str] = set()
    for d in decisions_raw:
        status = d.get("staleness_status") or "fresh"
        if status == "superseded":
            # Explicit opt-in keeps the original (no chain collapse).
            if include_superseded:
                kept_ids.add(d["id"])
                continue
            # Default path: try chain collapse when a successor pointer exists.
            successor_ptr = d.get("superseded_by_id")
            if not successor_ptr:
                _bump_stat("superseded")
                continue
            terminal_id, terminal_status = resolve_successor_chain(conn, d["id"])
            if terminal_id == d["id"]:
                # Unresolved (cycle or missing chain link)
                _bump_stat("superseded")
                continue
            if terminal_status == "contradicted" and not include_contradicted:
                _bump_stat("chain_terminal_contradicted")
                continue
            if terminal_status == "superseded":
                # Terminal itself is marked superseded without a forward pointer — policy filter.
                _bump_stat("chain_terminal_superseded")
                continue
            if terminal_status == "stale" and not include_stale:
                _bump_stat("chain_terminal_stale")
                continue
            # Fetch the terminal if not already in our candidate set
            if terminal_id not in decisions_by_id:
                row = conn.execute("SELECT * FROM decisions WHERE id = ?", (terminal_id,)).fetchone()
                if row is None:
                    _bump_stat("chain_terminal_missing")
                    continue
                decisions_by_id[terminal_id] = dict(row)
            kept_ids.add(terminal_id)
            chain_ancestors.setdefault(terminal_id, set()).add(d["id"])
            continue
        if status == "contradicted" and not include_contradicted:
            _bump_stat("contradicted")
            continue
        if status == "stale" and not include_stale:
            _bump_stat("stale")
            continue
        kept_ids.add(d["id"])

    if not kept_ids:
        return ([], filter_stats) if _return_stats else []

    decisions = [decisions_by_id[did] for did in kept_ids]

    decision_ids = [d["id"] for d in decisions]
    # Signal queries must include ancestors so their matched evidence reaches the
    # substituted terminal. Ancestors may not be in kept_ids but still need their
    # decision_files / decision_assessments / decision_commits fetched.
    signal_query_ids: set[str] = set(decision_ids)
    for ancestor_ids in chain_ancestors.values():
        signal_query_ids |= ancestor_ids
    signal_id_list = list(signal_query_ids)
    ph = ",".join("?" for _ in signal_id_list)

    # File links
    file_links_by_decision: dict[str, set[str]] = {did: set() for did in signal_id_list}
    for row in conn.execute(
        f"SELECT decision_id, file_path FROM decision_files WHERE decision_id IN ({ph})",  # noqa: S608
        signal_id_list,
    ).fetchall():
        file_links_by_decision[row["decision_id"]].add(row["file_path"])

    # Assessment links (with relation_type for weighted scoring)
    assessment_links_by_decision: dict[str, dict[str, str]] = {did: {} for did in signal_id_list}
    for row in conn.execute(
        f"SELECT decision_id, assessment_id, relation_type FROM decision_assessments WHERE decision_id IN ({ph})",  # noqa: S608
        signal_id_list,
    ).fetchall():
        existing = assessment_links_by_decision[row["decision_id"]]
        aid = row["assessment_id"]
        rtype = row["relation_type"]
        # Keep max weight per assessment_id
        if aid not in existing or weights.assessment_relation_weights.get(
            rtype, 0
        ) > weights.assessment_relation_weights.get(existing[aid], 0):
            existing[aid] = rtype

    # Commit links
    commit_links_by_decision: dict[str, set[str]] = {did: set() for did in signal_id_list}
    if commit_shas:
        for row in conn.execute(
            f"SELECT decision_id, commit_sha FROM decision_commits WHERE decision_id IN ({ph})",  # noqa: S608
            signal_id_list,
        ).fetchall():
            commit_links_by_decision[row["decision_id"]].add(row["commit_sha"])

    # Merge ancestor signals onto their terminal so scoring sees the collapsed evidence.
    for terminal_id, ancestor_ids in chain_ancestors.items():
        merged_files = set(file_links_by_decision.get(terminal_id, set()))
        merged_assessments = dict(assessment_links_by_decision.get(terminal_id, {}))
        merged_commits = set(commit_links_by_decision.get(terminal_id, set()))
        for anc_id in ancestor_ids:
            merged_files |= file_links_by_decision.get(anc_id, set())
            for aid, rtype in assessment_links_by_decision.get(anc_id, {}).items():
                if aid not in merged_assessments or weights.assessment_relation_weights.get(
                    rtype, 0
                ) > weights.assessment_relation_weights.get(merged_assessments[aid], 0):
                    merged_assessments[aid] = rtype
            merged_commits |= commit_links_by_decision.get(anc_id, set())
        file_links_by_decision[terminal_id] = merged_files
        assessment_links_by_decision[terminal_id] = merged_assessments
        commit_links_by_decision[terminal_id] = merged_commits

    # Propagate ancestor diff FTS scores onto the terminal (max).
    for terminal_id, ancestor_ids in chain_ancestors.items():
        best = diff_fts_scores.get(terminal_id, 0.0)
        for anc_id in ancestor_ids:
            best = max(best, diff_fts_scores.get(anc_id, 0.0))
        if best > 0.0:
            diff_fts_scores[terminal_id] = best

    # Outcome counts — scored against terminal only (ancestor outcomes are a
    # separate signal chain and not transferred to successors).
    outcome_counts_by_decision: dict[str, dict[str, int]] = {did: {} for did in decision_ids}
    ph_kept = ",".join("?" for _ in decision_ids)
    for row in conn.execute(
        f"SELECT decision_id, outcome_type, COUNT(*) AS total FROM decision_outcomes WHERE decision_id IN ({ph_kept}) GROUP BY decision_id, outcome_type",  # noqa: S608
        decision_ids,
    ).fetchall():
        outcome_counts_by_decision.setdefault(row["decision_id"], {})[row["outcome_type"]] = row["total"] or 0

    # --- 3. Score each candidate ---
    commit_set = set(commit_shas)
    scored: list[dict] = []
    for d in decisions:
        did = d["id"]
        file_exact = 0.0
        file_proximity = 0.0
        assessment_score = 0.0
        diff_relevance = diff_fts_scores.get(did, 0.0)
        git_commit = 0.0

        # File signals
        if file_paths:
            linked_files = file_links_by_decision.get(did, set())
            for fp in file_paths:
                exact_matched = False
                for linked in linked_files:
                    if _normalize_path(linked) == fp:
                        file_exact += weights.file_exact_weight
                        exact_matched = True
                        break
                if not exact_matched:
                    best_prox = 0.0
                    for linked in linked_files:
                        prox = _directory_proximity_score(fp, linked, cap_levels=weights.directory_proximity_cap_levels)
                        if prox > best_prox:
                            best_prox = prox
                    file_proximity += best_prox

        # Assessment signal (deduplicated by assessment_id, max weight)
        if resolved_assessment_ids:
            links = assessment_links_by_decision.get(did, {})
            for aid, rtype in links.items():
                if aid in resolved_assessment_ids:
                    assessment_score += weights.assessment_relation_weights.get(rtype, 4.0)

        # Git commit signal
        if commit_set:
            linked_commits = commit_links_by_decision.get(did, set())
            git_commit = weights.git_commit_weight * len(linked_commits & commit_set)

        base_score = file_exact + file_proximity + assessment_score + diff_relevance + git_commit
        if base_score <= 0:
            continue

        quality_score = calculate_decision_quality_score(outcome_counts_by_decision.get(did, {}))
        staleness_factor = weights.staleness_factors.get(d.get("staleness_status", "fresh"), 1.0)
        score = base_score * staleness_factor + quality_score

        scored.append(
            {
                "id": did,
                "title": d.get("title"),
                "staleness_status": d.get("staleness_status"),
                "updated_at": d.get("updated_at"),
                "base_score": round(base_score, 3),
                "quality_score": round(quality_score, 3),
                "score": round(score, 3),
                "score_breakdown": {
                    "file_exact": round(file_exact, 3),
                    "file_proximity": round(file_proximity, 3),
                    "assessment": round(assessment_score, 3),
                    "diff_relevance": round(diff_relevance, 3),
                    "git_commit": round(git_commit, 3),
                    "quality": round(quality_score, 3),
                    "staleness_factor": round(staleness_factor, 3),
                },
            }
        )

    scored.sort(key=lambda item: (item["score"], item.get("updated_at", "")), reverse=True)
    top = scored[:limit]
    if _return_stats:
        return top, filter_stats
    return top


def check_staleness(conn, decision_id: str, repo_path: str) -> dict:
    """Check if linked files changed since decision creation.

    Requires git >= 2.x for reliable ISO 8601 timestamp parsing in --since.
    """
    full_id = _resolve_decision_id(conn, decision_id)
    if full_id is None:
        raise ValueError(f"Decision '{decision_id}' not found")

    decision = get_decision(conn, full_id)
    linked_files = decision.get("files", []) if decision else []
    not_stale = {"stale": False, "changed_files": [], "decision_id": full_id}

    if not linked_files:
        return not_stale

    since = decision.get("created_at") if decision else None
    if since and since.endswith("+00:00"):
        since = since[:-6] + "Z"
    since_arg = f"--since={since}" if since else "--since=3 months ago"

    try:
        result = subprocess.run(
            ["git", "log", since_arg, "--name-only", "--pretty=format:"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return not_stale
        recently_changed = {line for line in result.stdout.strip().split("\n") if line}
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return not_stale

    changed_in_scope = sorted(set(linked_files) & recently_changed)
    return {"stale": len(changed_in_scope) > 0, "changed_files": changed_in_scope, "decision_id": full_id}


# ---------------------------------------------------------------------------
# FTS / Hybrid keyword search for decisions
# ---------------------------------------------------------------------------


def fts_search_decisions(
    conn,
    query: str,
    *,
    since: str | None = None,
    limit: int = 20,
    include_stale: bool = True,
    include_superseded: bool = False,
    include_contradicted: bool = False,
) -> list[dict]:
    """FTS5 full-text search over decision title and rationale.

    Staleness policy (issue #39):
    - Superseded is excluded by default; set include_superseded=True to include.
    - Contradicted is excluded by default; set include_contradicted=True to include.
    - Stale decisions are included by default.
    """
    staleness_predicate, staleness_params = _staleness_sql_predicate(
        include_stale=include_stale,
        include_superseded=include_superseded,
        include_contradicted=include_contradicted,
        column="d.staleness_status",
    )
    where_clauses = ["fts_decisions MATCH ?", "(? IS NULL OR d.updated_at >= ?)"]
    if staleness_predicate:
        where_clauses.append(staleness_predicate)
    where_sql = " AND ".join(where_clauses)
    sql = (
        "SELECT d.id, d.title, d.rationale, d.scope, d.staleness_status, "
        "d.updated_at, d.created_at, rank, -rank AS relevance_score "
        "FROM fts_decisions fd JOIN decisions d ON fd.rowid = d.rowid "
        f"WHERE {where_sql} ORDER BY rank LIMIT ?"  # noqa: S608
    )
    params: list[Any] = [query, since, since, *staleness_params, limit]

    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception as exc:
        from .search import _raise_fts_query_error

        _raise_fts_query_error(exc)
        raise

    return [dict(r) for r in rows]


def hybrid_search_decisions(
    conn,
    query: str,
    *,
    since: str | None = None,
    limit: int = 20,
    k: int = 60,
    include_stale: bool = True,
    include_superseded: bool = False,
    include_contradicted: bool = False,
) -> list[dict]:
    """Hybrid search combining FTS5 relevance and recency via RRF.

    Staleness flags are passed through to fts_search_decisions so the RRF
    baseline is already filtered — preventing stale content from boosting
    to the top through recency.
    """
    from .search import rrf_fuse

    fts_results = fts_search_decisions(
        conn,
        query,
        since=since,
        limit=limit * 3,
        include_stale=include_stale,
        include_superseded=include_superseded,
        include_contradicted=include_contradicted,
    )
    if not fts_results:
        return []

    fts_rank_list = [r["id"] for r in fts_results]
    id_to_ts = {r["id"]: (r.get("updated_at") or "") for r in fts_results}
    recency_rank_list = sorted(fts_rank_list, key=lambda rid: id_to_ts.get(rid, ""), reverse=True)

    scores = rrf_fuse([fts_rank_list, recency_rank_list], k=k)
    sorted_ids = sorted(scores, key=scores.__getitem__, reverse=True)[:limit]

    id_to_doc = {r["id"]: r for r in fts_results}
    results: list[dict] = []
    for rid in sorted_ids:
        if rid in id_to_doc:
            doc = dict(id_to_doc[rid])
            doc["hybrid_score"] = round(scores[rid], 6)
            results.append(doc)
    return results
