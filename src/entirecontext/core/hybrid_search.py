"""Hybrid search — combines FTS5 relevance with recency via Reciprocal Rank Fusion (RRF).

No external dependencies required — pure SQLite + Python.

Algorithm
---------
1. Run FTS5 full-text search to retrieve an expanded candidate set.
2. Re-rank the *same* candidates by recency (timestamp DESC).
3. Fuse both ranked lists with RRF: score(d) = Σᵢ [ wᵢ / (k + rankᵢ(d)) ]
4. Return top ``limit`` by fused score, each enriched with ``hybrid_score``.

Because the recency ranking is drawn from the FTS5 hit set rather than
all turns, only relevance-matched turns can ever appear in the output.
"""

from __future__ import annotations

from typing import Any

from .search import _apply_query_redaction


def rrf_fuse(
    rank_lists: list[list[str]],
    weights: list[float] | None = None,
    k: int = 60,
) -> dict[str, float]:
    """Reciprocal Rank Fusion over multiple ranked ID lists.

    Standard RRF formula (Cormack et al., 2009):
        score(d) = Σᵢ [ wᵢ / (k + rankᵢ(d)) ]

    Documents that appear in only a subset of lists contribute only from
    those lists; missing-list contribution is implicitly zero.

    Args:
        rank_lists: Ordered lists of document IDs (index 0 = rank 1 = best).
        weights: Per-list multipliers; defaults to 1.0 for every list.
        k: RRF smoothing constant (default 60, as in the original paper).

    Returns:
        Dict mapping doc_id → RRF score (higher = better).
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
    """Hybrid search combining FTS5 relevance and recency via RRF.

    Runs FTS5 full-text search to retrieve candidates, then re-ranks them
    using Reciprocal Rank Fusion (RRF) over two signals:

    1. **FTS5 relevance** — the order FTS5 returns results (BM25-like rank).
    2. **Recency** — most recently updated candidates ranked first.

    Turns that rank well on *both* signals receive the highest ``hybrid_score``.

    Args:
        conn: DB connection.
        query: FTS5 query string (standard FTS5 syntax supported).
        target: Search target — ``"turn"``, ``"session"``, or ``"event"``.
            Unsupported targets return an empty list.
        file_filter: Optional file-path substring filter (applied by FTS layer).
        commit_filter: Optional exact commit hash filter.
        agent_filter: Optional session-type filter.
        since: Optional ISO date lower bound for turn/session/event timestamp.
        limit: Maximum results to return.
        k: RRF smoothing constant (default 60).
        config: Optional config dict for query-time field redaction.

    Returns:
        List of dicts enriched with ``hybrid_score`` (float), sorted descending.
        Returns ``[]`` when no FTS5 candidates are found or target is unsupported.
    """
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
    """Common RRF fusion step shared by all target types.

    1. Build FTS rank list (already ordered by FTS5 relevance).
    2. Build recency rank list by sorting the same IDs by ``ts_key`` DESC.
    3. Fuse with equal weights.
    4. Return top ``limit`` dicts enriched with ``hybrid_score``.
    """
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
    from .search import _fts_search_turns

    # When file_filter is active, _fts_search_turns applies it *after* the SQL LIMIT,
    # so the actual candidate pool can be smaller than requested.  Use a larger multiplier
    # to compensate and give RRF more candidates to work with.
    fetch_multiplier = 10 if file_filter else 3
    fts_results = _fts_search_turns(
        conn, query, file_filter, commit_filter, agent_filter, since, limit * fetch_multiplier
    )
    if not fts_results:
        return []
    return _fuse_and_rank(fts_results, ts_key="timestamp", limit=limit, k=k)


def _hybrid_search_sessions(conn, query, since, limit, k) -> list[dict]:
    from .search import _fts_search_sessions

    fts_results = _fts_search_sessions(conn, query, since, limit * 3)
    if not fts_results:
        return []
    return _fuse_and_rank(fts_results, ts_key="last_activity_at", limit=limit, k=k)


def _hybrid_search_events(conn, query, since, limit, k) -> list[dict]:
    from .search import _fts_search_events

    fts_results = _fts_search_events(conn, query, since, limit * 3)
    if not fts_results:
        return []
    return _fuse_and_rank(fts_results, ts_key="created_at", limit=limit, k=k)
