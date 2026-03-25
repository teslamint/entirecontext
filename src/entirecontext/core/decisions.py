"""Decision domain operations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

VALID_STALENESS = ("fresh", "stale", "superseded", "contradicted")
# relation_type is part of identity so one decision-assessment pair can keep
# multiple typed links (e.g. informed_by + contradicts) when historically true.
VALID_DECISION_ASSESSMENT_RELATION_TYPES = ("supports", "informed_by", "contradicts", "supersedes")


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
        raise ValueError(f"Invalid staleness_status '{staleness_status}'. Must be one of: {VALID_STALENESS}")

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
            "SELECT assessment_id, relation_type, added_at FROM decision_assessments WHERE decision_id = ? ORDER BY added_at DESC",
            (full_id,),
        )
    ]
    return decision


def list_decisions(
    conn,
    staleness_status: str | None = None,
    file_path: str | None = None,
    limit: int = 20,
) -> list[dict]:
    if staleness_status and staleness_status not in VALID_STALENESS:
        raise ValueError(f"Invalid staleness_status '{staleness_status}'. Must be one of: {VALID_STALENESS}")

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
        raise ValueError(f"Invalid status '{status}'. Must be one of: {VALID_STALENESS}")

    full_id = _resolve_decision_id(conn, decision_id)
    if full_id is None:
        raise ValueError(f"Decision '{decision_id}' not found")

    conn.execute(
        "UPDATE decisions SET staleness_status = ?, updated_at = ? WHERE id = ?", (status, _now_iso(), full_id)
    )
    conn.commit()
    return get_decision(conn, full_id) or {}


def link_decision_to_assessment(conn, decision_id: str, assessment_id: str, relation_type: str = "supports") -> dict:
    if relation_type not in VALID_DECISION_ASSESSMENT_RELATION_TYPES:
        raise ValueError(
            f"Invalid relation_type '{relation_type}'. Must be one of: {VALID_DECISION_ASSESSMENT_RELATION_TYPES}"
        )

    full_decision_id = _resolve_decision_id(conn, decision_id)
    if full_decision_id is None:
        raise ValueError(f"Decision '{decision_id}' not found")

    full_assessment_id = _resolve_assessment_id(conn, assessment_id)
    if full_assessment_id is None:
        raise ValueError(f"Assessment '{assessment_id}' not found")

    conn.execute(
        """INSERT OR IGNORE INTO decision_assessments (decision_id, assessment_id, relation_type)
        VALUES (?, ?, ?)""",
        (full_decision_id, full_assessment_id, relation_type),
    )
    conn.execute("UPDATE decisions SET updated_at = ? WHERE id = ?", (_now_iso(), full_decision_id))
    conn.commit()
    row = conn.execute(
        "SELECT decision_id, assessment_id, relation_type, added_at FROM decision_assessments WHERE decision_id = ? AND assessment_id = ? AND relation_type = ?",
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
        "SELECT decision_id, checkpoint_id, added_at FROM decision_checkpoints WHERE decision_id = ? AND checkpoint_id = ?",
        (full_decision_id, full_checkpoint_id),
    ).fetchone()
    return dict(row) if row else {}
