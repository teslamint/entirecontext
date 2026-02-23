"""Tests for knowledge graph layer — git entities as nodes, relations as edges."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.knowledge_graph import (
    build_knowledge_graph,
    get_graph_stats,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _seed_graph_db(ec_repo, ec_db):
    """Seed DB with sessions, turns, checkpoints, agents to form a knowledge graph.

    Topology:
        agent-1 ran session-1
            session-1 contains turn-1 (commit abc123, files: auth.py, utils.py)
            session-1 contains turn-2 (commit def456, files: auth.py)
            session-1 has checkpoint chk-1 (commit abc123, branch: main)

        agent-2 ran session-2
            session-2 contains turn-3 (commit def456, files: README.md)
    """
    from entirecontext.core.agent_graph import create_agent
    from entirecontext.core.project import get_project
    from entirecontext.core.session import create_session
    from entirecontext.core.turn import create_turn

    project = get_project(str(ec_repo))

    agent1 = create_agent(ec_db, "orchestrator", agent_id="agent-1", name="Agent One")
    agent2 = create_agent(ec_db, "coder", agent_id="agent-2", name="Agent Two")

    s1 = create_session(ec_db, project["id"], session_id="session-1", agent_id="agent-1")
    s2 = create_session(ec_db, project["id"], session_id="session-2", agent_id="agent-2")

    t1 = create_turn(
        ec_db,
        "session-1",
        1,
        user_message="add auth",
        assistant_summary="added auth module",
        git_commit_hash="abc123",
        files_touched=json.dumps(["auth.py", "utils.py"]),
    )
    t2 = create_turn(
        ec_db,
        "session-1",
        2,
        user_message="fix auth",
        assistant_summary="patched auth",
        git_commit_hash="def456",
        files_touched=json.dumps(["auth.py"]),
    )
    t3 = create_turn(
        ec_db,
        "session-2",
        1,
        user_message="update readme",
        assistant_summary="updated docs",
        git_commit_hash="def456",
        files_touched=json.dumps(["README.md"]),
    )

    # Checkpoint for session-1
    ec_db.execute(
        """INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch, created_at)
           VALUES (?, ?, ?, ?, datetime('now'))""",
        ("chk-1", "session-1", "abc123", "main"),
    )
    ec_db.commit()

    return {
        "agent1": agent1["id"],
        "agent2": agent2["id"],
        "s1": s1["id"],
        "s2": s2["id"],
        "t1": t1["id"],
        "t2": t2["id"],
        "t3": t3["id"],
    }


# ---------------------------------------------------------------------------
# build_knowledge_graph — node types
# ---------------------------------------------------------------------------


class TestBuildKnowledgeGraphNodes:
    def test_returns_nodes_and_edges(self, ec_repo, ec_db):
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        assert "nodes" in graph
        assert "edges" in graph

    def test_session_nodes_present(self, ec_repo, ec_db):
        ids = _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        session_nodes = [n for n in graph["nodes"] if n["type"] == "session"]
        session_ids = [n["id"] for n in session_nodes]
        assert ids["s1"] in session_ids
        assert ids["s2"] in session_ids

    def test_commit_nodes_present(self, ec_repo, ec_db):
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        commit_nodes = [n for n in graph["nodes"] if n["type"] == "commit"]
        commit_ids = [n["id"] for n in commit_nodes]
        assert "abc123" in commit_ids
        assert "def456" in commit_ids

    def test_commit_nodes_deduplicated(self, ec_repo, ec_db):
        """def456 appears in 2 turns — only one commit node should exist."""
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        commit_nodes = [n for n in graph["nodes"] if n["type"] == "commit"]
        commit_ids = [n["id"] for n in commit_nodes]
        assert commit_ids.count("def456") == 1

    def test_file_nodes_present(self, ec_repo, ec_db):
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        file_nodes = [n for n in graph["nodes"] if n["type"] == "file"]
        file_ids = [n["id"] for n in file_nodes]
        assert "auth.py" in file_ids
        assert "utils.py" in file_ids
        assert "README.md" in file_ids

    def test_file_nodes_deduplicated(self, ec_repo, ec_db):
        """auth.py appears in 2 turns — only one file node should exist."""
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        file_nodes = [n for n in graph["nodes"] if n["type"] == "file"]
        file_ids = [n["id"] for n in file_nodes]
        assert file_ids.count("auth.py") == 1

    def test_agent_nodes_present(self, ec_repo, ec_db):
        ids = _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        agent_nodes = [n for n in graph["nodes"] if n["type"] == "agent"]
        agent_ids = [n["id"] for n in agent_nodes]
        assert ids["agent1"] in agent_ids
        assert ids["agent2"] in agent_ids

    def test_nodes_have_required_fields(self, ec_repo, ec_db):
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        for node in graph["nodes"]:
            assert "id" in node
            assert "type" in node
            assert "label" in node

    def test_node_ids_are_unique(self, ec_repo, ec_db):
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        ids = [n["id"] for n in graph["nodes"]]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# build_knowledge_graph — edge types
# ---------------------------------------------------------------------------


class TestBuildKnowledgeGraphEdges:
    def test_session_contains_turn_edge(self, ec_repo, ec_db):
        ids = _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        edges = {(e["source"], e["relation"], e["target"]) for e in graph["edges"]}
        assert (ids["s1"], "contains", ids["t1"]) in edges

    def test_turn_committed_edge(self, ec_repo, ec_db):
        ids = _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        edges = {(e["source"], e["relation"], e["target"]) for e in graph["edges"]}
        assert (ids["t1"], "committed_via", "abc123") in edges

    def test_turn_touched_file_edge(self, ec_repo, ec_db):
        ids = _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        edges = {(e["source"], e["relation"], e["target"]) for e in graph["edges"]}
        assert (ids["t1"], "touched", "auth.py") in edges
        assert (ids["t1"], "touched", "utils.py") in edges

    def test_agent_ran_session_edge(self, ec_repo, ec_db):
        ids = _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        edges = {(e["source"], e["relation"], e["target"]) for e in graph["edges"]}
        assert (ids["agent1"], "ran_session", ids["s1"]) in edges
        assert (ids["agent2"], "ran_session", ids["s2"]) in edges

    def test_checkpoint_anchors_commit_edge(self, ec_repo, ec_db):
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        edges = {(e["source"], e["relation"], e["target"]) for e in graph["edges"]}
        assert ("chk-1", "anchors_commit", "abc123") in edges

    def test_session_has_checkpoint_edge(self, ec_repo, ec_db):
        ids = _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        edges = {(e["source"], e["relation"], e["target"]) for e in graph["edges"]}
        assert (ids["s1"], "has_checkpoint", "chk-1") in edges

    def test_edges_have_required_fields(self, ec_repo, ec_db):
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        for edge in graph["edges"]:
            assert "source" in edge
            assert "relation" in edge
            assert "target" in edge

    def test_no_self_loop_edges(self, ec_repo, ec_db):
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        for edge in graph["edges"]:
            assert edge["source"] != edge["target"]

    def test_edges_reference_existing_nodes(self, ec_repo, ec_db):
        """Every edge endpoint should reference a node in the graph."""
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        node_ids = {n["id"] for n in graph["nodes"]}
        for edge in graph["edges"]:
            assert edge["source"] in node_ids, f"edge source {edge['source']!r} not in nodes"
            assert edge["target"] in node_ids, f"edge target {edge['target']!r} not in nodes"


# ---------------------------------------------------------------------------
# build_knowledge_graph — filtering
# ---------------------------------------------------------------------------


class TestBuildKnowledgeGraphFilters:
    def test_session_filter_restricts_turns(self, ec_repo, ec_db):
        ids = _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db, session_id=ids["s1"])
        turn_nodes = [n for n in graph["nodes"] if n["type"] == "turn"]
        turn_ids = [n["id"] for n in turn_nodes]
        # Only turns from session-1
        assert ids["t1"] in turn_ids
        assert ids["t2"] in turn_ids
        assert ids["t3"] not in turn_ids

    def test_session_filter_restricts_sessions(self, ec_repo, ec_db):
        ids = _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db, session_id=ids["s1"])
        session_ids = [n["id"] for n in graph["nodes"] if n["type"] == "session"]
        assert ids["s1"] in session_ids
        assert ids["s2"] not in session_ids

    def test_limit_caps_total_turns(self, ec_repo, ec_db):
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db, limit=1)
        turn_nodes = [n for n in graph["nodes"] if n["type"] == "turn"]
        assert len(turn_nodes) <= 1

    def test_since_filter_excludes_old_turns(self, ec_repo, ec_db):
        """Turns with timestamps before `since` should not appear as turn nodes."""
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session
        from entirecontext.core.turn import create_turn

        project = get_project(str(ec_repo))
        s = create_session(ec_db, session_id="sess-since-test", project_id=project["id"])

        # Create a turn and then manually set its timestamp to a known old date
        t_old = create_turn(
            ec_db, "sess-since-test", 1,
            user_message="old turn",
            assistant_summary="old",
        )
        ec_db.execute("UPDATE turns SET timestamp = '2020-01-01T00:00:00' WHERE id = ?", (t_old["id"],))
        ec_db.commit()

        t_new = create_turn(
            ec_db, "sess-since-test", 2,
            user_message="new turn",
            assistant_summary="new",
        )
        ec_db.execute("UPDATE turns SET timestamp = '2025-06-01T00:00:00' WHERE id = ?", (t_new["id"],))
        ec_db.commit()

        graph = build_knowledge_graph(ec_db, session_id="sess-since-test", since="2025-01-01")
        turn_ids = [n["id"] for n in graph["nodes"] if n["type"] == "turn"]
        assert t_old["id"] not in turn_ids
        assert t_new["id"] in turn_ids

    def test_empty_db_returns_empty_graph(self, ec_repo, ec_db):
        graph = build_knowledge_graph(ec_db)
        # no sessions → no nodes/edges except possibly empty lists
        assert graph["nodes"] == []
        assert graph["edges"] == []


# ---------------------------------------------------------------------------
# get_graph_stats
# ---------------------------------------------------------------------------


class TestGetGraphStats:
    def test_returns_dict(self, ec_repo, ec_db):
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        stats = get_graph_stats(graph)
        assert isinstance(stats, dict)

    def test_total_nodes(self, ec_repo, ec_db):
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        stats = get_graph_stats(graph)
        assert stats["total_nodes"] == len(graph["nodes"])

    def test_total_edges(self, ec_repo, ec_db):
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        stats = get_graph_stats(graph)
        assert stats["total_edges"] == len(graph["edges"])

    def test_nodes_by_type_counts(self, ec_repo, ec_db):
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        stats = get_graph_stats(graph)
        by_type = stats["nodes_by_type"]
        assert by_type.get("session", 0) == 2
        assert by_type.get("commit", 0) == 2  # abc123, def456
        assert by_type.get("file", 0) == 3  # auth.py, utils.py, README.md
        assert by_type.get("agent", 0) == 2

    def test_edges_by_relation_counts(self, ec_repo, ec_db):
        _seed_graph_db(ec_repo, ec_db)
        graph = build_knowledge_graph(ec_db)
        stats = get_graph_stats(graph)
        by_rel = stats["edges_by_relation"]
        assert by_rel.get("contains", 0) >= 3  # 3 turns
        assert by_rel.get("committed_via", 0) >= 3
        assert by_rel.get("touched", 0) >= 4  # t1:2 + t2:1 + t3:1
        assert by_rel.get("ran_session", 0) == 2

    def test_empty_graph_stats(self, ec_repo, ec_db):
        graph = {"nodes": [], "edges": []}
        stats = get_graph_stats(graph)
        assert stats["total_nodes"] == 0
        assert stats["total_edges"] == 0


# ---------------------------------------------------------------------------
# CLI: ec graph
# ---------------------------------------------------------------------------


class TestGraphCLI:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["graph"])
        assert result.exit_code == 1

    def test_basic_output(self):
        mock_conn = MagicMock()
        graph = {
            "nodes": [
                {"id": "s1", "type": "session", "label": "sess-1"},
                {"id": "abc123", "type": "commit", "label": "abc123"},
            ],
            "edges": [
                {"source": "s1", "relation": "has_checkpoint", "target": "abc123"}
            ],
        }
        stats = {
            "total_nodes": 2,
            "total_edges": 1,
            "nodes_by_type": {"session": 1, "commit": 1},
            "edges_by_relation": {"has_checkpoint": 1},
        }
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.knowledge_graph.build_knowledge_graph", return_value=graph),
            patch("entirecontext.core.knowledge_graph.get_graph_stats", return_value=stats),
        ):
            result = runner.invoke(app, ["graph"])
        assert result.exit_code == 0
        assert "2" in result.output or "node" in result.output.lower()

    def test_empty_graph_message(self):
        mock_conn = MagicMock()
        graph = {"nodes": [], "edges": []}
        stats = {"total_nodes": 0, "total_edges": 0, "nodes_by_type": {}, "edges_by_relation": {}}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.knowledge_graph.build_knowledge_graph", return_value=graph),
            patch("entirecontext.core.knowledge_graph.get_graph_stats", return_value=stats),
        ):
            result = runner.invoke(app, ["graph"])
        assert result.exit_code == 0
        assert "no" in result.output.lower() or "0" in result.output

    def test_session_option_passed(self):
        mock_conn = MagicMock()
        graph = {"nodes": [], "edges": []}
        stats = {"total_nodes": 0, "total_edges": 0, "nodes_by_type": {}, "edges_by_relation": {}}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch(
                "entirecontext.core.knowledge_graph.build_knowledge_graph", return_value=graph
            ) as mock_build,
            patch("entirecontext.core.knowledge_graph.get_graph_stats", return_value=stats),
        ):
            runner.invoke(app, ["graph", "--session", "sess-001"])
        mock_build.assert_called_once()
        assert mock_build.call_args.kwargs.get("session_id") == "sess-001"

    def test_limit_option_passed(self):
        mock_conn = MagicMock()
        graph = {"nodes": [], "edges": []}
        stats = {"total_nodes": 0, "total_edges": 0, "nodes_by_type": {}, "edges_by_relation": {}}
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch(
                "entirecontext.core.knowledge_graph.build_knowledge_graph", return_value=graph
            ) as mock_build,
            patch("entirecontext.core.knowledge_graph.get_graph_stats", return_value=stats),
        ):
            runner.invoke(app, ["graph", "--limit", "50"])
        assert mock_build.call_args.kwargs.get("limit") == 50
