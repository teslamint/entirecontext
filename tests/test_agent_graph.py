"""Tests for multi-agent session graph — agent hierarchy traversal."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.agent_graph import (
    build_agent_graph,
    create_agent,
    get_agent,
    get_agent_sessions,
    get_session_agent_chain,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _insert_agent(
    conn,
    agent_id: str,
    agent_type: str = "claude",
    *,
    parent_agent_id: str | None = None,
    role: str | None = None,
    name: str | None = None,
    spawn_context: str | None = None,
) -> dict:
    """Insert an agent record directly and return it as a dict."""
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
    }


def _seed_agent_graph(ec_repo, ec_db):
    """Seed a 3-level agent hierarchy with associated sessions.

    root_agent (orchestrator)
    ├── child_a (coder)   ← 2 sessions
    │   └── grandchild_a1 (reviewer)  ← 1 session
    └── child_b (tester)  ← 1 session

    orphan_agent has no sessions and is not in the hierarchy.
    """
    from entirecontext.core.project import get_project
    from entirecontext.core.session import create_session

    project = get_project(str(ec_repo))

    root = _insert_agent(ec_db, "root-agent", "orchestrator", name="Root")
    child_a = _insert_agent(ec_db, "child-a", "coder", parent_agent_id="root-agent", name="Coder A")
    child_b = _insert_agent(ec_db, "child-b", "tester", parent_agent_id="root-agent", name="Tester B")
    grandchild = _insert_agent(ec_db, "grandchild-a1", "reviewer", parent_agent_id="child-a", name="Reviewer A1")
    orphan = _insert_agent(ec_db, "orphan-agent", "utility", name="Orphan")

    s1 = create_session(ec_db, project["id"], session_id="sess-1", agent_id="child-a")
    s2 = create_session(ec_db, project["id"], session_id="sess-2", agent_id="child-a")
    s3 = create_session(ec_db, project["id"], session_id="sess-3", agent_id="child-b")
    s4 = create_session(ec_db, project["id"], session_id="sess-4", agent_id="grandchild-a1")
    # root_agent has no sessions directly

    return {
        "root": root["id"],
        "child_a": child_a["id"],
        "child_b": child_b["id"],
        "grandchild": grandchild["id"],
        "orphan": orphan["id"],
        "s1": s1["id"],
        "s2": s2["id"],
        "s3": s3["id"],
        "s4": s4["id"],
    }


# ---------------------------------------------------------------------------
# create_agent
# ---------------------------------------------------------------------------


class TestCreateAgent:
    def test_returns_dict_with_id(self, ec_repo, ec_db):
        agent = create_agent(ec_db, "claude", name="Test Agent")
        assert isinstance(agent, dict)
        assert "id" in agent
        assert len(agent["id"]) > 0

    def test_stores_agent_type(self, ec_repo, ec_db):
        agent = create_agent(ec_db, "codex", name="Codex Agent")
        row = ec_db.execute("SELECT agent_type FROM agents WHERE id=?", (agent["id"],)).fetchone()
        assert row["agent_type"] == "codex"

    def test_custom_id(self, ec_repo, ec_db):
        agent = create_agent(ec_db, "claude", agent_id="custom-id-001")
        assert agent["id"] == "custom-id-001"

    def test_parent_agent_id(self, ec_repo, ec_db):
        create_agent(ec_db, "orchestrator", agent_id="parent-001")
        child = create_agent(ec_db, "claude", agent_id="child-001", parent_agent_id="parent-001")
        row = ec_db.execute("SELECT parent_agent_id FROM agents WHERE id=?", (child["id"],)).fetchone()
        assert row["parent_agent_id"] == "parent-001"

    def test_optional_fields_stored(self, ec_repo, ec_db):
        agent = create_agent(ec_db, "claude", role="coder", name="My Agent", spawn_context="test context")
        row = ec_db.execute(
            "SELECT role, name, spawn_context FROM agents WHERE id=?", (agent["id"],)
        ).fetchone()
        assert row["role"] == "coder"
        assert row["name"] == "My Agent"
        assert row["spawn_context"] == "test context"


# ---------------------------------------------------------------------------
# get_agent
# ---------------------------------------------------------------------------


class TestGetAgent:
    def test_returns_agent_by_id(self, ec_repo, ec_db):
        _insert_agent(ec_db, "get-test-001", "claude", name="Get Test")
        agent = get_agent(ec_db, "get-test-001")
        assert agent is not None
        assert agent["id"] == "get-test-001"
        assert agent["name"] == "Get Test"

    def test_returns_none_for_missing_id(self, ec_repo, ec_db):
        assert get_agent(ec_db, "nonexistent-agent") is None

    def test_prefix_lookup(self, ec_repo, ec_db):
        _insert_agent(ec_db, "prefix-test-abcdef", "claude")
        agent = get_agent(ec_db, "prefix-test-a")
        assert agent is not None
        assert agent["id"] == "prefix-test-abcdef"

    def test_prefix_lookup_with_underscore_in_id(self, ec_repo, ec_db):
        """Underscore in agent ID must be treated as literal, not LIKE wildcard."""
        _insert_agent(ec_db, "agent_foo_bar", "claude")
        _insert_agent(ec_db, "agentXfooXbar", "claude")
        agent = get_agent(ec_db, "agent_foo_bar")
        assert agent is not None
        # Exact match should be returned, not the wildcard match
        assert agent["id"] == "agent_foo_bar"

    def test_prefix_lookup_with_percent_in_id(self, ec_repo, ec_db):
        """Percent in agent ID must be treated as literal, not LIKE wildcard."""
        _insert_agent(ec_db, "agent%001", "claude")
        _insert_agent(ec_db, "agentXXX001", "claude")
        agent = get_agent(ec_db, "agent%001")
        assert agent is not None
        assert agent["id"] == "agent%001"


# ---------------------------------------------------------------------------
# get_agent_sessions
# ---------------------------------------------------------------------------


class TestGetAgentSessions:
    def test_returns_sessions_for_agent(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        sessions = get_agent_sessions(ec_db, ids["child_a"])
        session_ids = [s["id"] for s in sessions]
        assert ids["s1"] in session_ids
        assert ids["s2"] in session_ids

    def test_does_not_return_other_agents_sessions(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        sessions = get_agent_sessions(ec_db, ids["child_a"])
        session_ids = [s["id"] for s in sessions]
        assert ids["s3"] not in session_ids

    def test_returns_empty_for_agent_with_no_sessions(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        sessions = get_agent_sessions(ec_db, ids["root"])
        assert sessions == []

    def test_returns_empty_for_nonexistent_agent(self, ec_repo, ec_db):
        sessions = get_agent_sessions(ec_db, "no-such-agent")
        assert sessions == []


# ---------------------------------------------------------------------------
# get_session_agent_chain
# ---------------------------------------------------------------------------


class TestGetSessionAgentChain:
    def test_returns_list(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        chain = get_session_agent_chain(ec_db, ids["s4"])
        assert isinstance(chain, list)

    def test_chain_starts_with_direct_agent(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        chain = get_session_agent_chain(ec_db, ids["s4"])
        # s4 belongs to grandchild-a1
        assert chain[0]["id"] == ids["grandchild"]

    def test_chain_includes_parent_agents(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        chain = get_session_agent_chain(ec_db, ids["s4"])
        chain_ids = [a["id"] for a in chain]
        # grandchild → child_a → root
        assert ids["child_a"] in chain_ids
        assert ids["root"] in chain_ids

    def test_chain_ordered_child_to_root(self, ec_repo, ec_db):
        """Chain should be ordered from direct (leaf) agent up to root."""
        ids = _seed_agent_graph(ec_repo, ec_db)
        chain = get_session_agent_chain(ec_db, ids["s4"])
        assert chain[0]["id"] == ids["grandchild"]
        assert chain[-1]["id"] == ids["root"]

    def test_session_with_no_agent(self, ec_repo, ec_db):
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session

        project = get_project(str(ec_repo))
        create_session(ec_db, project["id"], session_id="sess-no-agent")
        chain = get_session_agent_chain(ec_db, "sess-no-agent")
        assert chain == []

    def test_nonexistent_session_returns_empty(self, ec_repo, ec_db):
        chain = get_session_agent_chain(ec_db, "nonexistent-session")
        assert chain == []


# ---------------------------------------------------------------------------
# build_agent_graph
# ---------------------------------------------------------------------------


class TestBuildAgentGraph:
    def test_returns_nodes_and_edges(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        graph = build_agent_graph(ec_db, root_agent_id=ids["root"])
        assert "nodes" in graph
        assert "edges" in graph

    def test_root_agent_included(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        graph = build_agent_graph(ec_db, root_agent_id=ids["root"])
        node_ids = [n["id"] for n in graph["nodes"]]
        assert ids["root"] in node_ids

    def test_direct_children_included(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        graph = build_agent_graph(ec_db, root_agent_id=ids["root"])
        node_ids = [n["id"] for n in graph["nodes"]]
        assert ids["child_a"] in node_ids
        assert ids["child_b"] in node_ids

    def test_grandchildren_included_at_depth_2(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        graph = build_agent_graph(ec_db, root_agent_id=ids["root"], depth=2)
        node_ids = [n["id"] for n in graph["nodes"]]
        assert ids["grandchild"] in node_ids

    def test_depth_1_excludes_grandchildren(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        graph = build_agent_graph(ec_db, root_agent_id=ids["root"], depth=1)
        node_ids = [n["id"] for n in graph["nodes"]]
        assert ids["grandchild"] not in node_ids

    def test_orphan_not_in_root_graph(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        graph = build_agent_graph(ec_db, root_agent_id=ids["root"])
        node_ids = [n["id"] for n in graph["nodes"]]
        assert ids["orphan"] not in node_ids

    def test_edges_connect_parent_to_child(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        graph = build_agent_graph(ec_db, root_agent_id=ids["root"])
        edges = graph["edges"]
        # Should have root→child_a and root→child_b edges
        edge_pairs = {(e["source"], e["target"]) for e in edges}
        assert (ids["root"], ids["child_a"]) in edge_pairs
        assert (ids["root"], ids["child_b"]) in edge_pairs

    def test_edge_includes_relation_field(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        graph = build_agent_graph(ec_db, root_agent_id=ids["root"])
        for edge in graph["edges"]:
            assert "relation" in edge
            assert edge["relation"] == "spawned"

    def test_nodes_include_session_count(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        graph = build_agent_graph(ec_db, root_agent_id=ids["root"])
        node_map = {n["id"]: n for n in graph["nodes"]}
        # child_a has 2 sessions
        assert node_map[ids["child_a"]]["session_count"] == 2
        # root has 0 direct sessions
        assert node_map[ids["root"]]["session_count"] == 0

    def test_nodes_include_agent_metadata(self, ec_repo, ec_db):
        ids = _seed_agent_graph(ec_repo, ec_db)
        graph = build_agent_graph(ec_db, root_agent_id=ids["root"])
        node_map = {n["id"]: n for n in graph["nodes"]}
        root_node = node_map[ids["root"]]
        assert "agent_type" in root_node
        assert "name" in root_node

    def test_seed_by_session_id(self, ec_repo, ec_db):
        """Seeding by session_id should find the agent and build its sub-graph."""
        ids = _seed_agent_graph(ec_repo, ec_db)
        # s1 belongs to child_a; graph should include child_a and its sub-tree
        graph = build_agent_graph(ec_db, session_id=ids["s1"])
        node_ids = [n["id"] for n in graph["nodes"]]
        assert ids["child_a"] in node_ids

    def test_empty_graph_for_nonexistent_agent(self, ec_repo, ec_db):
        graph = build_agent_graph(ec_db, root_agent_id="nonexistent")
        assert graph["nodes"] == []
        assert graph["edges"] == []

    def test_no_seed_returns_empty(self, ec_repo, ec_db):
        graph = build_agent_graph(ec_db)
        assert graph["nodes"] == []
        assert graph["edges"] == []


# ---------------------------------------------------------------------------
# CLI: ec session graph
# ---------------------------------------------------------------------------


class TestSessionGraphCLI:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["session", "graph", "--agent", "abc"])
        assert result.exit_code == 1

    def test_no_seed_exits_nonzero(self):
        with patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"):
            result = runner.invoke(app, ["session", "graph"])
        assert result.exit_code == 1

    def test_output_with_graph(self):
        mock_conn = MagicMock()
        graph = {
            "nodes": [
                {"id": "agent-001", "agent_type": "orchestrator", "name": "Root", "role": None, "session_count": 0},
                {"id": "agent-002", "agent_type": "coder", "name": "Coder", "role": "coder", "session_count": 3},
            ],
            "edges": [{"source": "agent-001", "target": "agent-002", "relation": "spawned"}],
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.agent_graph.build_agent_graph", return_value=graph),
        ):
            result = runner.invoke(app, ["session", "graph", "--agent", "agent-001"])
        assert result.exit_code == 0
        assert "agent-001" in result.output or "Root" in result.output

    def test_empty_graph_message(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.agent_graph.build_agent_graph", return_value={"nodes": [], "edges": []}),
        ):
            result = runner.invoke(app, ["session", "graph", "--agent", "no-such"])
        assert result.exit_code == 0
        assert "no" in result.output.lower() or "0" in result.output

    def test_session_seed_calls_build(self):
        mock_conn = MagicMock()
        graph = {"nodes": [], "edges": []}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.agent_graph.build_agent_graph", return_value=graph) as mock_build,
        ):
            runner.invoke(app, ["session", "graph", "--session", "sess-001"])
        mock_build.assert_called_once()
        assert mock_build.call_args.kwargs.get("session_id") == "sess-001"

    def test_depth_option_passed(self):
        mock_conn = MagicMock()
        graph = {"nodes": [], "edges": []}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.agent_graph.build_agent_graph", return_value=graph) as mock_build,
        ):
            runner.invoke(app, ["session", "graph", "--agent", "root", "--depth", "4"])
        assert mock_build.call_args.kwargs.get("depth") == 4
