"""Decision domain operations."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


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


def _format_allowed(values: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted(values))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_decision_id(conn, decision_id: str) -> str | None:
    row = conn.execute("SELECT id FROM decisions WHERE id = ?", (decision_id,)).fetchone()
    if row is None:
        escaped = decision_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        row = conn.execute("SELECT id FROM decisions WHERE id LIKE ? ESCAPE '\\'", (f"{escaped}%",)).fetchone()
    return row["id"] if row else None


def _resolve_checkpoint_id(conn, checkpoint_id: str) -> str | None:
    row = conn.execute("SELECT id FROM checkpoints WHERE id = ?", (checkpoint_id,)).fetchone()
    if row is None:
        escaped = checkpoint_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        row = conn.execute("SELECT id FROM checkpoints WHERE id LIKE ? ESCAPE '\\'", (f"{escaped}%",)).fetchone()
    return row["id"] if row else None


def _resolve_assessment_id(conn, assessment_id: str) -> str | None:
    row = conn.execute("SELECT id FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
    if row is None:
        escaped = assessment_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        row = conn.execute("SELECT id FROM assessments WHERE id LIKE ? ESCAPE '\\'", (f"{escaped}%",)).fetchone()
    return row["id"] if row else None


def _escape_like_contains(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _parse_decision_json_fields(decision: dict[str, Any]) -> dict[str, Any]:
    for field in ("rejected_alternatives", "supporting_evidence"):
        raw = decision.get(field)
        try:
            decision[field] = json.loads(raw) if raw else []
        except (json.JSONDecodeError, TypeError):
            decision[field] = []
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
    return decision


def list_decisions(
    conn,
    staleness_status: str | None = None,
    file_path: str | None = None,
    limit: int = 20,
) -> list[dict]:
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

    conn.execute(
        "UPDATE decisions SET staleness_status = ?, updated_at = ? WHERE id = ?", (status, _now_iso(), full_id)
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
    conn.execute(
        """
        INSERT INTO decision_outcomes (
            id, decision_id, retrieval_selection_id, session_id, turn_id, outcome_type, note, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (outcome_id, full_decision_id, retrieval_selection_id, session_id, turn_id, outcome_type, note, now),
    )
    conn.execute("UPDATE decisions SET updated_at = ? WHERE id = ?", (now, full_decision_id))
    conn.commit()
    row = conn.execute(
        """
        SELECT id, decision_id, retrieval_selection_id, session_id, turn_id, outcome_type, note, created_at
        FROM decision_outcomes
        WHERE id = ?
        """,
        (outcome_id,),
    ).fetchone()
    return dict(row) if row else {}


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


def supersede_decision(conn, old_decision_id: str, new_decision_id: str) -> dict:
    old_full = _resolve_decision_id(conn, old_decision_id)
    if old_full is None:
        raise ValueError(f"Decision '{old_decision_id}' not found")

    new_full = _resolve_decision_id(conn, new_decision_id)
    if new_full is None:
        raise ValueError(f"Decision '{new_decision_id}' not found")

    if old_full == new_full:
        raise ValueError("A decision cannot supersede itself")

    now = _now_iso()
    conn.execute(
        "UPDATE decisions SET staleness_status = 'superseded', superseded_by_id = ?, updated_at = ? WHERE id = ?",
        (new_full, now, old_full),
    )
    conn.commit()
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
