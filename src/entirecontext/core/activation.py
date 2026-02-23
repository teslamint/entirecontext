"""Spreading activation — chained turn traversal through shared files and commits.

Implements a graph-based search that propagates activation from seed turns
through edges defined by shared ``files_touched`` or ``git_commit_hash``.
No external dependencies required — pure SQLite + Python.
"""

from __future__ import annotations

import json
from typing import Any


def _get_turn_signals(turn: dict[str, Any]) -> tuple[set[str], str | None]:
    """Extract file set and commit hash from a turn dict.

    Returns (file_set, commit_hash).  Both may be empty/None.
    """
    files: set[str] = set()
    raw = turn.get("files_touched")
    if raw:
        try:
            files = set(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            pass
    commit = turn.get("git_commit_hash") or None
    return files, commit


def _fetch_turn(conn, turn_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM turns WHERE id LIKE ?", (f"{turn_id}%",)).fetchone()
    return dict(row) if row else None


def _fetch_session_turns(conn, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM turns WHERE session_id = ? ORDER BY turn_number ASC", (session_id,)).fetchall()
    return [dict(r) for r in rows]


def _find_related_turns(
    conn,
    files: set[str],
    commit: str | None,
    exclude_ids: set[str],
) -> list[tuple[str, float]]:
    """Find turns related to the given files/commit.

    Returns list of (turn_id, edge_weight) pairs, where edge_weight reflects
    how strongly the turn is connected to the given signals.
    """
    related: dict[str, float] = {}

    # Find turns sharing at least one file
    if files:
        if exclude_ids:
            rows = conn.execute(
                "SELECT id, files_touched FROM turns WHERE files_touched IS NOT NULL AND id NOT IN ({})".format(
                    ",".join("?" * len(exclude_ids))
                ),
                list(exclude_ids),
            ).fetchall()
        else:
            rows = conn.execute("SELECT id, files_touched FROM turns WHERE files_touched IS NOT NULL").fetchall()
        for row in rows:
            try:
                row_files = set(json.loads(row["files_touched"]))
            except (json.JSONDecodeError, TypeError):
                continue
            overlap = len(files & row_files)
            if overlap > 0:
                # Weight by fraction of files in common relative to union
                union = len(files | row_files)
                weight = overlap / union if union else 0.0
                related[row["id"]] = related.get(row["id"], 0.0) + weight

    # Find turns sharing the same commit
    if commit:
        if exclude_ids:
            rows = conn.execute(
                "SELECT id FROM turns WHERE git_commit_hash = ? AND id NOT IN ({})".format(
                    ",".join("?" * len(exclude_ids))
                ),
                [commit] + list(exclude_ids),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM turns WHERE git_commit_hash = ?",
                [commit],
            ).fetchall()
        for row in rows:
            related[row["id"]] = related.get(row["id"], 0.0) + 1.0

    return list(related.items())


def spread_activation(
    conn,
    *,
    seed_turn_id: str | None = None,
    seed_session_id: str | None = None,
    max_hops: int = 2,
    limit: int = 20,
    decay: float = 0.5,
) -> list[dict[str, Any]]:
    """Find turns related to a seed by spreading activation through the graph.

    Activation propagates along edges formed by shared ``files_touched`` or
    ``git_commit_hash``.  Each hop multiplies the score by *decay* (default 0.5),
    so directly-connected turns score higher than 2-hop turns.

    Args:
        conn: DB connection.
        seed_turn_id: Start activation from this turn ID (prefix supported).
        seed_session_id: Start activation from all turns in this session.
        max_hops: Maximum traversal depth (default 2).
        limit: Maximum results to return.
        decay: Score multiplier per hop (0 < decay <= 1).

    Returns:
        List of turn dicts enriched with ``activation_score``, sorted descending.
        The seed turn(s) are excluded.  Returns [] if no seeds provided or found.
    """
    if seed_turn_id is None and seed_session_id is None:
        return []

    # Build the initial seed set
    seed_turns: list[dict[str, Any]] = []
    if seed_turn_id:
        t = _fetch_turn(conn, seed_turn_id)
        if t:
            seed_turns.append(t)
    if seed_session_id:
        seed_turns.extend(_fetch_session_turns(conn, seed_session_id))

    if not seed_turns:
        return []

    seed_ids = {t["id"] for t in seed_turns}

    # activation_scores: turn_id → cumulative score
    activation_scores: dict[str, float] = {}
    # visited: turn_ids we've already spread from (to avoid cycles)
    visited: set[str] = set(seed_ids)
    # frontier: list of (turn, current_score_multiplier)
    frontier: list[tuple[dict[str, Any], float]] = [(t, 1.0) for t in seed_turns]

    for hop in range(max_hops):
        next_frontier: list[tuple[dict[str, Any], float]] = []
        # Accumulate newly discovered IDs outside the inner loop so that all
        # frontier turns see the same 'visited' set for this hop.  This prevents
        # the second frontier turn from missing a shared neighbour that was added
        # to 'visited' by the first frontier turn earlier in the same iteration.
        new_visited: set[str] = set()
        for turn, multiplier in frontier:
            files, commit = _get_turn_signals(turn)
            if not files and not commit:
                continue

            related = _find_related_turns(conn, files, commit, exclude_ids=visited)

            for rid, edge_weight in related:
                score_contribution = multiplier * decay * edge_weight
                activation_scores[rid] = activation_scores.get(rid, 0.0) + score_contribution

            # Collect newly discovered turns to build the next frontier
            if hop < max_hops - 1:
                for rid, _ in related:
                    if rid not in visited and rid not in new_visited:
                        new_visited.add(rid)
                        row = conn.execute("SELECT * FROM turns WHERE id = ?", (rid,)).fetchone()
                        if row:
                            next_frontier.append((dict(row), multiplier * decay))

        visited |= new_visited
        frontier = next_frontier

    if not activation_scores:
        return []

    # Fetch full turn dicts for the activated turns and attach scores
    sorted_ids = sorted(activation_scores, key=activation_scores.__getitem__, reverse=True)
    results: list[dict[str, Any]] = []
    for turn_id in sorted_ids[:limit]:
        row = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        if row:
            t = dict(row)
            t["activation_score"] = round(activation_scores[turn_id], 6)
            results.append(t)

    return results
