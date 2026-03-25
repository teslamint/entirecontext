"""Search engine — regex, FTS5, structured filters."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _apply_query_redaction(results: list[dict], config: dict[str, Any] | None) -> list[dict]:
    """Apply query-time redaction to search results."""
    if not config:
        return results
    from .content_filter import redact_for_query

    redacted = []
    for r in results:
        r = dict(r)
        for field in ("user_message", "assistant_summary", "session_title", "session_summary", "title", "description"):
            if field in r and r[field]:
                r[field] = redact_for_query(r[field], config)
        redacted.append(r)
    return redacted


def regex_search(
    conn,
    pattern: str,
    target: str = "turn",
    file_filter: str | None = None,
    commit_filter: str | None = None,
    agent_filter: str | None = None,
    since: str | None = None,
    limit: int = 20,
    config: dict[str, Any] | None = None,
) -> list[dict]:
    """Regex search across turns/sessions/events."""
    if target == "turn":
        results = _regex_search_turns(conn, pattern, file_filter, commit_filter, agent_filter, since, limit)
    elif target == "session":
        results = _regex_search_sessions(conn, pattern, since, limit)
    elif target == "event":
        results = _regex_search_events(conn, pattern, since, limit)
    elif target == "content":
        results = _regex_search_content(conn, pattern, limit)
    else:
        results = []
    return _apply_query_redaction(results, config)


def _regex_search_turns(conn, pattern: str, file_filter, commit_filter, agent_filter, since, limit) -> list[dict]:
    query = """
        SELECT t.id, t.session_id, t.user_message, t.assistant_summary,
               t.timestamp, t.files_touched, t.git_commit_hash
        FROM turns t
        JOIN sessions s ON t.session_id = s.id
        WHERE 1=1
    """
    params: list[Any] = []

    if since:
        query += " AND t.timestamp >= ?"
        params.append(since)
    if commit_filter:
        query += " AND t.git_commit_hash = ?"
        params.append(commit_filter)
    if agent_filter:
        query += " AND s.session_type = ?"
        params.append(agent_filter)

    query += " ORDER BY t.timestamp DESC LIMIT ?"
    params.append(limit * 5)

    rows = conn.execute(query, params).fetchall()
    results = []
    regex = re.compile(pattern, re.IGNORECASE)

    for row in rows:
        row_dict = dict(row)
        text = f"{row_dict.get('user_message', '')} {row_dict.get('assistant_summary', '')}"

        if file_filter and row_dict.get("files_touched"):
            files = json.loads(row_dict["files_touched"])
            if not any(file_filter in f for f in files):
                continue

        if regex.search(text):
            results.append(row_dict)
            if len(results) >= limit:
                break

    return results


def _regex_search_sessions(conn, pattern: str, since, limit) -> list[dict]:
    query = "SELECT * FROM sessions WHERE 1=1"
    params: list[Any] = []
    if since:
        query += " AND started_at >= ?"
        params.append(since)
    query += " ORDER BY last_activity_at DESC LIMIT ?"
    params.append(limit * 3)

    rows = conn.execute(query, params).fetchall()
    regex = re.compile(pattern, re.IGNORECASE)
    results = []
    for row in rows:
        d = dict(row)
        text = f"{d.get('session_title', '')} {d.get('session_summary', '')}"
        if regex.search(text):
            results.append(d)
            if len(results) >= limit:
                break
    return results


def _regex_search_events(conn, pattern: str, since, limit) -> list[dict]:
    query = "SELECT * FROM events WHERE 1=1"
    params: list[Any] = []
    if since:
        query += " AND created_at >= ?"
        params.append(since)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit * 3)

    rows = conn.execute(query, params).fetchall()
    regex = re.compile(pattern, re.IGNORECASE)
    results = []
    for row in rows:
        d = dict(row)
        text = f"{d.get('title', '')} {d.get('description', '')}"
        if regex.search(text):
            results.append(d)
            if len(results) >= limit:
                break
    return results


def _regex_search_content(conn, pattern: str, limit: int) -> list[dict]:
    """Search in external content files via grep."""
    rows = conn.execute(
        "SELECT tc.turn_id, tc.content_path, t.session_id FROM turn_content tc JOIN turns t ON tc.turn_id = t.id"
    ).fetchall()

    regex = re.compile(pattern, re.IGNORECASE)
    results = []

    repo_row = conn.execute("SELECT repo_path FROM projects LIMIT 1").fetchone()
    if not repo_row:
        return []
    repo_path = repo_row[0]

    for row in rows:
        full_path = Path(repo_path) / ".entirecontext" / row["content_path"]
        if not full_path.exists():
            continue
        try:
            content = full_path.read_text(encoding="utf-8")
            if regex.search(content):
                results.append(
                    {
                        "turn_id": row["turn_id"],
                        "session_id": row["session_id"],
                        "content_path": row["content_path"],
                    }
                )
                if len(results) >= limit:
                    break
        except OSError:
            continue

    return results


def fts_search(
    conn,
    query: str,
    target: str = "turn",
    file_filter: str | None = None,
    commit_filter: str | None = None,
    agent_filter: str | None = None,
    since: str | None = None,
    limit: int = 20,
    config: dict[str, Any] | None = None,
) -> list[dict]:
    """FTS5 full-text search."""
    if target == "turn":
        results = _fts_search_turns(conn, query, file_filter, commit_filter, agent_filter, since, limit)
    elif target == "session":
        results = _fts_search_sessions(conn, query, since, limit)
    elif target == "event":
        results = _fts_search_events(conn, query, since, limit)
    else:
        results = []
    return _apply_query_redaction(results, config)


def _fts_search_turns(conn, query, file_filter, commit_filter, agent_filter, since, limit) -> list[dict]:
    sql = """
        SELECT t.id, t.session_id, t.user_message, t.assistant_summary,
               t.timestamp, t.files_touched, t.git_commit_hash,
               rank
        FROM fts_turns ft
        JOIN turns t ON ft.rowid = t.rowid
        JOIN sessions s ON t.session_id = s.id
        WHERE fts_turns MATCH ?
    """
    params: list[Any] = [query]

    if since:
        sql += " AND t.timestamp >= ?"
        params.append(since)
    if commit_filter:
        sql += " AND t.git_commit_hash = ?"
        params.append(commit_filter)
    if agent_filter:
        sql += " AND s.session_type = ?"
        params.append(agent_filter)

    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    results = [dict(r) for r in rows]

    if file_filter:
        results = [r for r in results if r.get("files_touched") and file_filter in r["files_touched"]]

    return results


def _fts_search_sessions(conn, query, since, limit) -> list[dict]:
    sql = "SELECT s.*, rank FROM fts_sessions fs JOIN sessions s ON fs.rowid = s.rowid WHERE fts_sessions MATCH ?"
    params: list[Any] = [query]
    if since:
        sql += " AND s.started_at >= ?"
        params.append(since)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _fts_search_events(conn, query, since, limit) -> list[dict]:
    sql = "SELECT e.*, rank FROM fts_events fe JOIN events e ON fe.rowid = e.rowid WHERE fts_events MATCH ?"
    params: list[Any] = [query]
    if since:
        sql += " AND e.created_at >= ?"
        params.append(since)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def rank_related_decisions(
    conn,
    *,
    file_paths: list[str] | None = None,
    assessment_ids: list[str] | None = None,
    diff_text: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Rank decisions by file overlap, assessment links, and recency.

    Scoring rules:
    - +4 per linked assessment match
    - +2 per linked file path match
    - +1 if title/rationale appears in diff text
    """
    file_paths = file_paths or []
    assessment_ids = assessment_ids or []
    diff_text_lc = (diff_text or "").lower()

    decisions = [dict(r) for r in conn.execute("SELECT * FROM decisions ORDER BY updated_at DESC LIMIT 200").fetchall()]
    if not decisions:
        return []

    resolved_assessment_ids: set[str] = set()
    for assessment_id in assessment_ids:
        row = conn.execute(
            "SELECT id FROM assessments WHERE id = ? OR id LIKE ?", (assessment_id, f"{assessment_id}%")
        ).fetchone()
        if row:
            resolved_assessment_ids.add(row["id"])

    scored: list[dict] = []
    decision_ids = [d["id"] for d in decisions]
    file_links_by_decision: dict[str, set[str]] = {decision_id: set() for decision_id in decision_ids}
    assessment_links_by_decision: dict[str, set[str]] = {decision_id: set() for decision_id in decision_ids}

    if decision_ids:
        placeholders = ",".join("?" for _ in decision_ids)
        file_rows = conn.execute(
            f"SELECT decision_id, file_path FROM decision_files WHERE decision_id IN ({placeholders})",
            decision_ids,
        ).fetchall()
        for row in file_rows:
            file_links_by_decision[row["decision_id"]].add(row["file_path"])

        assessment_rows = conn.execute(
            f"SELECT decision_id, assessment_id FROM decision_assessments WHERE decision_id IN ({placeholders})",
            decision_ids,
        ).fetchall()
        for row in assessment_rows:
            assessment_links_by_decision[row["decision_id"]].add(row["assessment_id"])

    for d in decisions:
        decision_id = d["id"]
        score = 0.0

        if file_paths:
            linked_files = file_links_by_decision.get(decision_id, set())
            for file_path in file_paths:
                if any(file_path in linked or linked in file_path for linked in linked_files):
                    score += 2

        if resolved_assessment_ids:
            linked_assessment_ids = assessment_links_by_decision.get(decision_id, set())
            score += 4 * len(linked_assessment_ids & resolved_assessment_ids)

        if diff_text_lc:
            title = (d.get("title") or "").lower()
            rationale = (d.get("rationale") or "").lower()
            if title and title in diff_text_lc:
                score += 1
            elif rationale and rationale[:80] and rationale[:80] in diff_text_lc:
                score += 1

        if score == 0:
            continue

        scored.append(
            {
                "id": decision_id,
                "title": d.get("title"),
                "staleness_status": d.get("staleness_status"),
                "updated_at": d.get("updated_at"),
                "score": round(score, 3),
            }
        )

    scored.sort(key=lambda item: (item["score"], item.get("updated_at", "")), reverse=True)
    return scored[:limit]
