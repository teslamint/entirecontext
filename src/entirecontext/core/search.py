"""Search engine — regex, FTS5, hybrid (RRF), and structured filters.

Hybrid search (formerly in hybrid_search.py) combines FTS5 relevance with
recency via Reciprocal Rank Fusion (RRF).  Algorithm:
1. Run FTS5 full-text search to retrieve an expanded candidate set.
2. Re-rank the *same* candidates by recency (timestamp DESC).
3. Fuse both ranked lists with RRF: score(d) = Σᵢ [ wᵢ / (k + rankᵢ(d)) ]
4. Return top ``limit`` by fused score, each enriched with ``hybrid_score``.
"""

from __future__ import annotations

import json
import re
import sqlite3
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


class FTSQueryError(ValueError):
    """Raised when an FTS5 query has invalid syntax."""


_FTS5_ERROR_PATTERNS = ("fts5: syntax error", "no such column", "unterminated string", "parse error")


def _raise_fts_query_error(exc: sqlite3.OperationalError) -> None:
    """Convert FTS5 query-related OperationalError to FTSQueryError with actionable message."""
    msg = str(exc).lower()
    if any(p in msg for p in _FTS5_ERROR_PATTERNS):
        raise FTSQueryError(
            f"Invalid FTS query: {exc}. Wrap punctuation in double-quotes or simplify the query."
        ) from exc


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

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        _raise_fts_query_error(exc)
        raise
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
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        _raise_fts_query_error(exc)
        raise
    return [dict(r) for r in rows]


def _fts_search_events(conn, query, since, limit) -> list[dict]:
    sql = "SELECT e.*, rank FROM fts_events fe JOIN events e ON fe.rowid = e.rowid WHERE fts_events MATCH ?"
    params: list[Any] = [query]
    if since:
        sql += " AND e.created_at >= ?"
        params.append(since)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        _raise_fts_query_error(exc)
        raise
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Hybrid search — FTS5 + recency via Reciprocal Rank Fusion (RRF)
# ---------------------------------------------------------------------------


def rrf_fuse(
    rank_lists: list[list[str]],
    weights: list[float] | None = None,
    k: int = 60,
) -> dict[str, float]:
    """Reciprocal Rank Fusion over multiple ranked ID lists.

    Standard RRF formula (Cormack et al., 2009):
        score(d) = Σᵢ [ wᵢ / (k + rankᵢ(d)) ]
    """
    if weights is None:
        weights = [1.0] * len(rank_lists)

    scores: dict[str, float] = {}
    for rank_list, w in zip(rank_lists, weights):
        for rank_1based, doc_id in enumerate(rank_list, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + w / (k + rank_1based)
    return scores


def hybrid_search(
    conn,
    query: str,
    target: str = "turn",
    file_filter: str | None = None,
    commit_filter: str | None = None,
    agent_filter: str | None = None,
    since: str | None = None,
    limit: int = 20,
    k: int = 60,
    config: dict[str, Any] | None = None,
) -> list[dict]:
    """Hybrid search combining FTS5 relevance and recency via RRF."""
    if target == "turn":
        results = _hybrid_search_turns(conn, query, file_filter, commit_filter, agent_filter, since, limit, k)
    elif target == "session":
        results = _hybrid_search_sessions(conn, query, since, limit, k)
    elif target == "event":
        results = _hybrid_search_events(conn, query, since, limit, k)
    else:
        results = []
    return _apply_query_redaction(results, config)


def _fuse_and_rank(fts_results: list[dict], ts_key: str, limit: int, k: int) -> list[dict]:
    """Common RRF fusion step shared by all target types."""
    fts_rank_list = [r["id"] for r in fts_results]
    id_to_ts = {r["id"]: (r.get(ts_key) or "") for r in fts_results}
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


def _hybrid_search_turns(conn, query, file_filter, commit_filter, agent_filter, since, limit, k) -> list[dict]:
    fetch_multiplier = 10 if file_filter else 3
    fts_results = _fts_search_turns(
        conn, query, file_filter, commit_filter, agent_filter, since, limit * fetch_multiplier
    )
    if not fts_results:
        return []
    return _fuse_and_rank(fts_results, ts_key="timestamp", limit=limit, k=k)


def _hybrid_search_sessions(conn, query, since, limit, k) -> list[dict]:
    fts_results = _fts_search_sessions(conn, query, since, limit * 3)
    if not fts_results:
        return []
    return _fuse_and_rank(fts_results, ts_key="last_activity_at", limit=limit, k=k)


def _hybrid_search_events(conn, query, since, limit, k) -> list[dict]:
    fts_results = _fts_search_events(conn, query, since, limit * 3)
    if not fts_results:
        return []
    return _fuse_and_rank(fts_results, ts_key="created_at", limit=limit, k=k)


# ---------------------------------------------------------------------------
# FTS index maintenance (formerly in indexing.py)
# ---------------------------------------------------------------------------


def rebuild_fts_indexes(conn: sqlite3.Connection) -> dict:
    """Rebuild FTS5 content-sync tables using the FTS5 'rebuild' command."""
    counts = {}

    conn.execute("INSERT INTO fts_turns(fts_turns) VALUES('rebuild')")
    counts["fts_turns"] = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]

    conn.execute("INSERT INTO fts_events(fts_events) VALUES('rebuild')")
    counts["fts_events"] = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    conn.execute("INSERT INTO fts_sessions(fts_sessions) VALUES('rebuild')")
    counts["fts_sessions"] = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    conn.commit()
    return counts
