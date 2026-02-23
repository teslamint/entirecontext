"""Knowledge graph layer — git entities as nodes, relations as edges.

Builds an in-memory graph from data already captured in the EntireContext DB
(sessions, turns, commits, files, agents, checkpoints).  No new subprocess
calls are made; all information is derived from existing tables.

Node types:
    ``session``   — a Claude Code session (sessions table)
    ``turn``      — a single prompt/response turn (turns table)
    ``commit``    — a git commit hash referenced by a turn or checkpoint
    ``file``      — a file path touched by one or more turns
    ``agent``     — an agent that ran one or more sessions (agents table)
    ``checkpoint``— a session checkpoint anchoring a git commit

Edge relations:
    ``contains``       session → turn   (session contains this turn)
    ``committed_via``  turn → commit    (turn's git_commit_hash)
    ``touched``        turn → file      (turn's files_touched list)
    ``ran_session``    agent → session  (agent that ran the session)
    ``anchors_commit`` checkpoint → commit
    ``has_checkpoint`` session → checkpoint

Typical usage::

    graph = build_knowledge_graph(conn)
    stats = get_graph_stats(graph)
    print(stats["nodes_by_type"])
"""

from __future__ import annotations

import json


def build_knowledge_graph(
    conn,
    *,
    session_id: str | None = None,
    since: str | None = None,
    limit: int = 200,
) -> dict:
    """Build a knowledge graph from existing DB entities.

    Args:
        conn: SQLite connection.
        session_id: Restrict graph to a single session and its entities.
        since: ISO date string; only include turns created on or after this date (inclusive).
        limit: Maximum number of turns to include (applied before deriving
            file/commit nodes).  Default 200.

    Returns:
        A dict with two keys:

        ``nodes``
            List of dicts, each with ``id``, ``type``, ``label``, and
            optional ``properties``.

        ``edges``
            List of dicts with ``source``, ``relation``, ``target``.
    """
    nodes: dict[str, dict] = {}  # id → node dict (deduplicates automatically)
    edges: list[dict] = []
    edges_seen: set[tuple[str, str, str]] = set()  # (source, relation, target) dedup

    def _add_node(nid: str, ntype: str, label: str, **props) -> None:
        if nid not in nodes:
            node = {"id": nid, "type": ntype, "label": label}
            if props:
                node["properties"] = props
            nodes[nid] = node

    def _add_edge(source: str, relation: str, target: str) -> None:
        if source != target:
            key = (source, relation, target)
            if key not in edges_seen:
                edges_seen.add(key)
                edges.append({"source": source, "relation": relation, "target": target})

    # ------------------------------------------------------------------
    # 1. Sessions
    # ------------------------------------------------------------------
    if session_id:
        session_rows = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchall()
    else:
        session_rows = conn.execute("SELECT * FROM sessions").fetchall()

    session_ids_in_graph: set[str] = set()
    for row in session_rows:
        s = dict(row)
        label = s.get("session_title") or s["id"][:12]
        _add_node(s["id"], "session", label, session_type=s.get("session_type"))
        session_ids_in_graph.add(s["id"])

    if not session_ids_in_graph:
        return {"nodes": [], "edges": []}

    # ------------------------------------------------------------------
    # 2. Agents (only those linked to included sessions)
    # ------------------------------------------------------------------
    placeholders = ",".join("?" * len(session_ids_in_graph))
    agent_rows = conn.execute(
        f"SELECT DISTINCT s.agent_id, a.agent_type, a.name, a.role "
        f"FROM sessions s JOIN agents a ON a.id = s.agent_id "
        f"WHERE s.id IN ({placeholders}) AND s.agent_id IS NOT NULL",
        list(session_ids_in_graph),
    ).fetchall()

    for row in agent_rows:
        a = dict(row)
        label = a.get("name") or a["agent_id"][:12]
        _add_node(a["agent_id"], "agent", label, agent_type=a.get("agent_type"), role=a.get("role"))

    # ------------------------------------------------------------------
    # 3. Turns (limited, filtered by session / since)
    # ------------------------------------------------------------------
    params: list = list(session_ids_in_graph)
    where_clauses = [f"session_id IN ({placeholders})"]

    if since:
        where_clauses.append("timestamp >= ?")
        params.append(since)

    where_sql = " AND ".join(where_clauses)
    turn_rows = conn.execute(
        f"SELECT * FROM turns WHERE {where_sql} ORDER BY timestamp DESC LIMIT ?",
        params + [limit],
    ).fetchall()

    for row in turn_rows:
        t = dict(row)
        label = (t.get("user_message") or t["id"])[:50]
        _add_node(t["id"], "turn", label)

    # ------------------------------------------------------------------
    # 4. Checkpoints (for included sessions)
    # ------------------------------------------------------------------
    chk_rows = conn.execute(
        f"SELECT * FROM checkpoints WHERE session_id IN ({placeholders})",
        list(session_ids_in_graph),
    ).fetchall()

    for row in chk_rows:
        c = dict(row)
        _add_node(c["id"], "checkpoint", c["id"][:12], git_branch=c.get("git_branch"))

    # ------------------------------------------------------------------
    # 5. Build edges and derive commit/file nodes from turns
    # ------------------------------------------------------------------
    # Session → turn (contains)
    for row in turn_rows:
        t = dict(row)
        _add_edge(t["session_id"], "contains", t["id"])

        # Turn → commit
        commit_hash = t.get("git_commit_hash")
        if commit_hash:
            _add_node(commit_hash, "commit", commit_hash[:8])
            _add_edge(t["id"], "committed_via", commit_hash)

        # Turn → files
        files_json = t.get("files_touched")
        if files_json:
            try:
                files = json.loads(files_json)
                if isinstance(files, list):
                    for fpath in files:
                        if isinstance(fpath, str):
                            _add_node(fpath, "file", fpath.split("/")[-1])
                            _add_edge(t["id"], "touched", fpath)
            except (json.JSONDecodeError, TypeError):
                pass

    # Agent → session (ran_session) — O(n) using the agent_id already on each session row
    for s_row in session_rows:
        s = dict(s_row)
        if s.get("agent_id") and s["agent_id"] in nodes:
            _add_edge(s["agent_id"], "ran_session", s["id"])

    # Checkpoint → commit and session → checkpoint
    for row in chk_rows:
        c = dict(row)
        commit_hash = c.get("git_commit_hash")
        if commit_hash:
            _add_node(commit_hash, "commit", commit_hash[:8])
            _add_edge(c["id"], "anchors_commit", commit_hash)
        _add_edge(c["session_id"], "has_checkpoint", c["id"])

    return {"nodes": list(nodes.values()), "edges": edges}


def get_graph_stats(graph: dict) -> dict:
    """Compute summary statistics for a knowledge graph.

    Args:
        graph: Dict with ``nodes`` and ``edges`` lists as returned by
            :func:`build_knowledge_graph`.

    Returns:
        Dict with keys:

        ``total_nodes`` (int)
            Total node count.

        ``total_edges`` (int)
            Total edge count.

        ``nodes_by_type`` (dict[str, int])
            Node counts keyed by ``type`` string.

        ``edges_by_relation`` (dict[str, int])
            Edge counts keyed by ``relation`` string.
    """
    nodes_by_type: dict[str, int] = {}
    for node in graph.get("nodes", []):
        ntype = node.get("type", "unknown")
        nodes_by_type[ntype] = nodes_by_type.get(ntype, 0) + 1

    edges_by_relation: dict[str, int] = {}
    for edge in graph.get("edges", []):
        rel = edge.get("relation", "unknown")
        edges_by_relation[rel] = edges_by_relation.get(rel, 0) + 1

    return {
        "total_nodes": len(graph.get("nodes", [])),
        "total_edges": len(graph.get("edges", [])),
        "nodes_by_type": nodes_by_type,
        "edges_by_relation": edges_by_relation,
    }
