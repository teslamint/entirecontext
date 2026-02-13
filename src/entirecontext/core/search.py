"""Search engine — regex, FTS5, structured filters."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def regex_search(
    conn,
    pattern: str,
    target: str = "turn",
    file_filter: str | None = None,
    commit_filter: str | None = None,
    agent_filter: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Regex search across turns/sessions/events."""
    if target == "turn":
        return _regex_search_turns(conn, pattern, file_filter, commit_filter, agent_filter, since, limit)
    elif target == "session":
        return _regex_search_sessions(conn, pattern, since, limit)
    elif target == "event":
        return _regex_search_events(conn, pattern, since, limit)
    elif target == "content":
        return _regex_search_content(conn, pattern, limit)
    return []


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
) -> list[dict]:
    """FTS5 full-text search."""
    if target == "turn":
        return _fts_search_turns(conn, query, file_filter, commit_filter, agent_filter, since, limit)
    elif target == "session":
        return _fts_search_sessions(conn, query, since, limit)
    elif target == "event":
        return _fts_search_events(conn, query, since, limit)
    return []


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
