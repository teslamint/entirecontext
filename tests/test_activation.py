"""Tests for spreading activation — chained turn traversal."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.activation import spread_activation

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _seed_db(ec_repo, ec_db):
    """Seed the DB with sessions and turns sharing files/commits."""
    from entirecontext.core.project import get_project
    from entirecontext.core.session import create_session
    from entirecontext.core.turn import create_turn

    project = get_project(str(ec_repo))
    s1 = create_session(ec_db, project["id"], session_id="act-session-1")
    s2 = create_session(ec_db, project["id"], session_id="act-session-2")

    # t1 touches auth.py and has commit abc123
    t1 = create_turn(
        ec_db,
        s1["id"],
        1,
        user_message="implement auth",
        assistant_summary="added auth module",
        git_commit_hash="abc123",
        files_touched=json.dumps(["auth.py", "utils.py"]),
    )
    # t2 also touches auth.py (same file → related to t1), different commit
    t2 = create_turn(
        ec_db,
        s1["id"],
        2,
        user_message="fix auth bug",
        assistant_summary="patched auth login",
        git_commit_hash="def456",
        files_touched=json.dumps(["auth.py", "tests/test_auth.py"]),
    )
    # t3 touches tests/test_auth.py (related to t2 via file)
    t3 = create_turn(
        ec_db,
        s2["id"],
        1,
        user_message="add more auth tests",
        assistant_summary="added edge cases",
        git_commit_hash="ghi789",
        files_touched=json.dumps(["tests/test_auth.py"]),
    )
    # t4 shares commit abc123 with t1 (same commit → related)
    t4 = create_turn(
        ec_db,
        s2["id"],
        2,
        user_message="update readme",
        assistant_summary="updated docs",
        git_commit_hash="abc123",
        files_touched=json.dumps(["README.md"]),
    )
    # t5 is isolated — no shared files or commits
    t5 = create_turn(
        ec_db,
        s2["id"],
        3,
        user_message="unrelated task",
        assistant_summary="did something else",
        git_commit_hash="zzz999",
        files_touched=json.dumps(["other.py"]),
    )
    return {
        "s1": s1["id"],
        "s2": s2["id"],
        "t1": t1["id"],
        "t2": t2["id"],
        "t3": t3["id"],
        "t4": t4["id"],
        "t5": t5["id"],
    }


# ---------------------------------------------------------------------------
# spread_activation core tests
# ---------------------------------------------------------------------------


class TestSpreadActivation:
    def test_returns_list(self, ec_repo, ec_db):
        ids = _seed_db(ec_repo, ec_db)
        results = spread_activation(ec_db, seed_turn_id=ids["t1"])
        assert isinstance(results, list)

    def test_seed_turn_not_in_results(self, ec_repo, ec_db):
        """The seed turn itself should not appear in the related results."""
        ids = _seed_db(ec_repo, ec_db)
        results = spread_activation(ec_db, seed_turn_id=ids["t1"])
        result_ids = [r["id"] for r in results]
        assert ids["t1"] not in result_ids

    def test_finds_turn_sharing_file(self, ec_repo, ec_db):
        """t2 shares auth.py with t1 — should be in results."""
        ids = _seed_db(ec_repo, ec_db)
        results = spread_activation(ec_db, seed_turn_id=ids["t1"])
        result_ids = [r["id"] for r in results]
        assert ids["t2"] in result_ids

    def test_finds_turn_sharing_commit(self, ec_repo, ec_db):
        """t4 shares commit abc123 with t1 — should be in results."""
        ids = _seed_db(ec_repo, ec_db)
        results = spread_activation(ec_db, seed_turn_id=ids["t1"])
        result_ids = [r["id"] for r in results]
        assert ids["t4"] in result_ids

    def test_isolated_turn_not_in_results(self, ec_repo, ec_db):
        """t5 has no shared files or commits with t1."""
        ids = _seed_db(ec_repo, ec_db)
        results = spread_activation(ec_db, seed_turn_id=ids["t1"])
        result_ids = [r["id"] for r in results]
        assert ids["t5"] not in result_ids

    def test_results_have_activation_score(self, ec_repo, ec_db):
        ids = _seed_db(ec_repo, ec_db)
        results = spread_activation(ec_db, seed_turn_id=ids["t1"])
        for r in results:
            assert "activation_score" in r
            assert r["activation_score"] > 0

    def test_results_sorted_by_score_descending(self, ec_repo, ec_db):
        ids = _seed_db(ec_repo, ec_db)
        results = spread_activation(ec_db, seed_turn_id=ids["t1"])
        scores = [r["activation_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_multi_hop_traversal(self, ec_repo, ec_db):
        """t3 is reachable from t1 via: t1→(auth.py)→t2→(test_auth.py)→t3."""
        ids = _seed_db(ec_repo, ec_db)
        results = spread_activation(ec_db, seed_turn_id=ids["t1"], max_hops=2)
        result_ids = [r["id"] for r in results]
        assert ids["t3"] in result_ids

    def test_max_hops_1_limits_traversal(self, ec_repo, ec_db):
        """With max_hops=1, t3 (requires 2 hops from t1) should NOT appear."""
        ids = _seed_db(ec_repo, ec_db)
        results = spread_activation(ec_db, seed_turn_id=ids["t1"], max_hops=1)
        result_ids = [r["id"] for r in results]
        # t3 is not directly connected to t1 (needs 2 hops)
        assert ids["t3"] not in result_ids

    def test_limit_respected(self, ec_repo, ec_db):
        ids = _seed_db(ec_repo, ec_db)
        # t1 is connected to t2, t3, t4 — with limit=2 only 2 should be returned
        results = spread_activation(ec_db, seed_turn_id=ids["t1"], max_hops=2, limit=2)
        assert len(results) <= 2

    def test_seed_by_session_id(self, ec_repo, ec_db):
        """seed_session_id uses all turns in session as starting seeds."""
        ids = _seed_db(ec_repo, ec_db)
        results = spread_activation(ec_db, seed_session_id=ids["s1"])
        assert isinstance(results, list)

    def test_empty_db_returns_empty_list(self, ec_repo, ec_db):
        results = spread_activation(ec_db, seed_turn_id="nonexistent-id")
        assert results == []

    def test_result_includes_turn_metadata(self, ec_repo, ec_db):
        ids = _seed_db(ec_repo, ec_db)
        results = spread_activation(ec_db, seed_turn_id=ids["t1"])
        for r in results:
            assert "id" in r
            assert "session_id" in r

    def test_direct_connection_higher_score_than_indirect(self, ec_repo, ec_db):
        """Directly connected turns should have higher activation than 2-hop turns."""
        ids = _seed_db(ec_repo, ec_db)
        results = spread_activation(ec_db, seed_turn_id=ids["t1"], max_hops=2)
        score_map = {r["id"]: r["activation_score"] for r in results}
        # t2 is directly connected; t3 requires 2 hops
        if ids["t2"] in score_map and ids["t3"] in score_map:
            assert score_map[ids["t2"]] >= score_map[ids["t3"]]

    def test_no_seed_returns_empty(self, ec_repo, ec_db):
        """Calling with neither seed_turn_id nor seed_session_id returns []."""
        results = spread_activation(ec_db)
        assert results == []


# ---------------------------------------------------------------------------
# CLI: ec search activate
# ---------------------------------------------------------------------------


class TestSessionActivateCLI:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["session", "activate", "--turn", "abc123"])
            assert result.exit_code == 1

    def test_output_with_results(self):
        mock_conn = MagicMock()
        results = [
            {
                "id": "turn-abc-001",
                "session_id": "sess-001",
                "activation_score": 2.5,
                "user_message": "fix auth",
                "assistant_summary": "fixed it",
                "timestamp": "2025-01-01T10:00:00",
            }
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.activation.spread_activation", return_value=results),
        ):
            result = runner.invoke(app, ["session", "activate", "--turn", "turn-abc-001"])
            assert result.exit_code == 0
            assert "fix auth" in result.output or "turn-abc" in result.output

    def test_no_results_message(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.activation.spread_activation", return_value=[]),
        ):
            result = runner.invoke(app, ["session", "activate", "--turn", "nonexistent"])
            assert result.exit_code == 0
            assert "no" in result.output.lower() or "0" in result.output

    def test_session_option(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.activation.spread_activation", return_value=[]) as mock_activate,
        ):
            runner.invoke(app, ["session", "activate", "--session", "sess-001"])
            mock_activate.assert_called_once()
            call_args = mock_activate.call_args
            assert call_args.args[0] is mock_conn
            assert call_args.kwargs.get("seed_session_id") == "sess-001"

    def test_hops_option(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.activation.spread_activation", return_value=[]) as mock_activate,
        ):
            runner.invoke(app, ["session", "activate", "--turn", "abc", "--hops", "3"])
            mock_activate.assert_called_once()
            call_args = mock_activate.call_args
            assert call_args.args[0] is mock_conn
            assert call_args.kwargs.get("max_hops") == 3
