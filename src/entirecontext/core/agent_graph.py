"""Multi-agent session graph — agent hierarchy traversal.

Provides functions to build and query the graph of agent relationships
(parent→child spawning) along with their associated sessions.

Typical usage:
    graph = build_agent_graph(conn, root_agent_id="agent-abc", depth=3)
    # graph["nodes"] — list of agent dicts with session_count
    # graph["edges"] — list of {"source", "target", "relation"} dicts

Agent hierarchy is derived from the ``agents.parent_agent_id`` FK.
Sessions are linked via ``sessions.agent_id``.
"""

from __future__ import annotations

from collections import deque
from uuid import uuid4


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_agent(
    conn,
    agent_type: str,
    *,
    agent_id: str | None = None,
    parent_agent_id: str | None = None,
    role: str | None = None,
    name: str | None = None,
    spawn_context: str | None = None,
) -> dict:
    """Create a new agent record and return it as a dict.

    Args:
        conn: SQLite connection.
        agent_type: Classifier string (e.g. ``"claude"``, ``"orchestrator"``).
        agent_id: Explicit ID; auto-generated UUID if omitted.
        parent_agent_id: FK to the spawning parent agent (optional).
        role: Descriptive role label (e.g. ``"coder"``, ``"reviewer"``).
        name: Human-readable display name.
        spawn_context: Free-form text describing why this agent was created.

    Returns:
        Dict with keys ``id``, ``parent_agent_id``, ``agent_type``, ``role``,
        ``name``, ``spawn_context``.
    """
    if agent_id is None:
        agent_id = str(uuid4())

    conn.execute(
        """INSERT INTO agents (id, parent_agent_id, agent_type, role, name, spawn_context)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (agent_id, parent_agent_id, agent_type, role, name, spawn_context),
    )
    conn.commit()
    return {
        "id": agent_id,
        "parent_agent_id": parent_agent_id,
        "agent_type": agent_type,
        "role": role,
        "name": name,
        "spawn_context": spawn_context,
    }


def get_agent(conn, agent_id: str) -> dict | None:
    """Retrieve an agent by exact or prefix ID.

    Returns the agent dict or ``None`` if not found.
    """
    row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if row is None:
        # Escape SQLite LIKE wildcards so prefix matching is literal
        escaped = agent_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        row = conn.execute(
            "SELECT * FROM agents WHERE id LIKE ? ESCAPE '\\'",
            (f"{escaped}%",),
        ).fetchone()
    return dict(row) if row else None


def get_agent_sessions(conn, agent_id: str) -> list[dict]:
    """Return all sessions associated with *agent_id*.

    Returns an empty list if the agent has no sessions or does not exist.
    """
    rows = conn.execute(
        "SELECT * FROM sessions WHERE agent_id = ? ORDER BY started_at DESC",
        (agent_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_session_agent_chain(conn, session_id: str) -> list[dict]:
    """Return the agent ancestry chain for a session, from leaf to root.

    Walks ``agents.parent_agent_id`` upward, returning a list ordered
    ``[direct_agent, parent, grandparent, ..., root]``.

    Returns an empty list if the session has no associated agent or
    does not exist.
    """
    row = conn.execute("SELECT agent_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None or row["agent_id"] is None:
        return []

    chain: list[dict] = []
    current_id: str | None = row["agent_id"]
    visited: set[str] = set()

    while current_id and current_id not in visited:
        visited.add(current_id)
        agent_row = conn.execute("SELECT * FROM agents WHERE id = ?", (current_id,)).fetchone()
        if agent_row is None:
            break
        agent = dict(agent_row)
        chain.append(agent)
        current_id = agent.get("parent_agent_id")

    return chain


def build_agent_graph(
    conn,
    *,
    root_agent_id: str | None = None,
    session_id: str | None = None,
    depth: int = 3,
) -> dict:
    """Build a graph of the agent hierarchy rooted at *root_agent_id*.

    If *session_id* is provided instead of *root_agent_id*, the function
    resolves the session's direct agent and uses that as the root.

    The traversal follows ``agents.parent_agent_id`` edges **downward**
    (i.e. from parent to children) up to *depth* levels.

    Args:
        conn: SQLite connection.
        root_agent_id: ID of the root agent to start traversal from.
        session_id: Session ID; its agent becomes the root (alternative seed).
        depth: Maximum number of levels to traverse below the root (default 3).

    Returns:
        A dict with two keys:

        ``nodes``
            List of agent dicts, each extended with ``session_count`` (int).

        ``edges``
            List of ``{"source": parent_id, "target": child_id,
            "relation": "spawned"}`` dicts.
    """
    if root_agent_id is None and session_id is None:
        return {"nodes": [], "edges": []}

    # Resolve seed from session if needed
    if root_agent_id is None:
        row = conn.execute("SELECT agent_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None or row["agent_id"] is None:
            return {"nodes": [], "edges": []}
        root_agent_id = row["agent_id"]

    # Verify root exists
    root_row = conn.execute("SELECT * FROM agents WHERE id = ?", (root_agent_id,)).fetchone()
    if root_row is None:
        return {"nodes": [], "edges": []}

    # BFS downward through parent→children relationships
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    queue: deque[tuple[str, int]] = deque([(root_agent_id, 0)])
    visited: set[str] = {root_agent_id}

    while queue:
        current_id, current_depth = queue.popleft()

        agent_row = conn.execute("SELECT * FROM agents WHERE id = ?", (current_id,)).fetchone()
        if agent_row is None:
            continue

        # Count sessions for this agent
        session_count = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE agent_id = ?", (current_id,)
        ).fetchone()[0]

        node = dict(agent_row)
        node["session_count"] = session_count
        nodes[current_id] = node

        if current_depth < depth:
            children = conn.execute(
                "SELECT id FROM agents WHERE parent_agent_id = ?", (current_id,)
            ).fetchall()
            for child_row in children:
                child_id = child_row["id"]
                if child_id not in visited:
                    visited.add(child_id)
                    edges.append({"source": current_id, "target": child_id, "relation": "spawned"})
                    queue.append((child_id, current_depth + 1))

    return {"nodes": list(nodes.values()), "edges": edges}
