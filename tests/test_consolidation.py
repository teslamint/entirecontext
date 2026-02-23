"""Tests for memory consolidation/decay feature."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.consolidation import (
    consolidate_old_turns,
    consolidate_turn_content,
    find_turns_for_consolidation,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helper: build in-memory DB with turns
# ---------------------------------------------------------------------------


def _setup_db_with_turns(ec_repo, ec_db):
    """Seed the test DB with sessions and turns. Returns (session_id, turn_ids)."""
    from entirecontext.core.project import get_project
    from entirecontext.core.session import create_session
    from entirecontext.core.turn import create_turn, save_turn_content

    project = get_project(str(ec_repo))
    session = create_session(ec_db, project["id"], session_id="test-session-001")

    turn_ids = []
    for i in range(1, 5):
        t = create_turn(
            ec_db,
            session["id"],
            turn_number=i,
            user_message=f"user message {i}",
            assistant_summary=f"assistant summary {i}",
        )
        # Save content file
        content = json.dumps({"messages": [{"role": "user", "content": f"user message {i}"}]})
        save_turn_content(str(ec_repo), ec_db, t["id"], session["id"], content)
        turn_ids.append(t["id"])

    return session["id"], turn_ids


# ---------------------------------------------------------------------------
# find_turns_for_consolidation
# ---------------------------------------------------------------------------


class TestFindTurnsForConsolidation:
    def test_returns_all_old_turns(self, ec_repo, ec_db):
        session_id, turn_ids = _setup_db_with_turns(ec_repo, ec_db)
        # Use a future date so all turns qualify
        results = find_turns_for_consolidation(ec_db, before_date="2099-01-01")
        assert len(results) == 4

    def test_no_turns_before_past_date(self, ec_repo, ec_db):
        _setup_db_with_turns(ec_repo, ec_db)
        results = find_turns_for_consolidation(ec_db, before_date="2000-01-01")
        assert len(results) == 0

    def test_filter_by_session_id(self, ec_repo, ec_db):
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session
        from entirecontext.core.turn import create_turn

        project = get_project(str(ec_repo))
        s2 = create_session(ec_db, project["id"], session_id="test-session-002")
        create_turn(ec_db, s2["id"], 1, user_message="other session turn")

        session_id, _ = _setup_db_with_turns(ec_repo, ec_db)
        results = find_turns_for_consolidation(ec_db, before_date="2099-01-01", session_id=session_id)
        assert all(r["session_id"] == session_id for r in results)

    def test_excludes_already_consolidated(self, ec_repo, ec_db):
        session_id, turn_ids = _setup_db_with_turns(ec_repo, ec_db)
        # Mark first turn as consolidated manually
        ec_db.execute("UPDATE turns SET consolidated_at = '2025-01-01T00:00:00' WHERE id = ?", (turn_ids[0],))
        ec_db.commit()
        results = find_turns_for_consolidation(ec_db, before_date="2099-01-01")
        result_ids = [r["id"] for r in results]
        assert turn_ids[0] not in result_ids
        assert len(results) == 3

    def test_respects_limit(self, ec_repo, ec_db):
        _setup_db_with_turns(ec_repo, ec_db)
        results = find_turns_for_consolidation(ec_db, before_date="2099-01-01", limit=2)
        assert len(results) == 2

    def test_only_returns_turns_with_content(self, ec_repo, ec_db):
        """Only turns that have content files should be returned (nothing to delete otherwise)."""
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session
        from entirecontext.core.turn import create_turn

        project = get_project(str(ec_repo))
        s = create_session(ec_db, project["id"], session_id="no-content-session")
        create_turn(ec_db, s["id"], 1, user_message="no content turn")
        # This turn has no entry in turn_content

        results = find_turns_for_consolidation(ec_db, before_date="2099-01-01")
        # The no-content turn should not appear since there's nothing to consolidate
        session_ids = [r["session_id"] for r in results]
        assert "no-content-session" not in session_ids


# ---------------------------------------------------------------------------
# consolidate_turn_content
# ---------------------------------------------------------------------------


class TestConsolidateTurnContent:
    def test_dry_run_does_not_delete_file(self, ec_repo, ec_db):
        session_id, turn_ids = _setup_db_with_turns(ec_repo, ec_db)
        # Find the content file path
        row = ec_db.execute("SELECT content_path FROM turn_content WHERE turn_id = ?", (turn_ids[0],)).fetchone()
        content_file = Path(str(ec_repo)) / ".entirecontext" / row["content_path"]
        assert content_file.exists()

        consolidate_turn_content(ec_db, str(ec_repo), turn_ids[0], dry_run=True)

        # File should still exist
        assert content_file.exists()
        # DB row should not be updated
        row2 = ec_db.execute("SELECT consolidated_at FROM turns WHERE id = ?", (turn_ids[0],)).fetchone()
        assert row2["consolidated_at"] is None

    def test_execute_deletes_content_file(self, ec_repo, ec_db):
        session_id, turn_ids = _setup_db_with_turns(ec_repo, ec_db)
        row = ec_db.execute("SELECT content_path FROM turn_content WHERE turn_id = ?", (turn_ids[0],)).fetchone()
        content_file = Path(str(ec_repo)) / ".entirecontext" / row["content_path"]
        assert content_file.exists()

        consolidate_turn_content(ec_db, str(ec_repo), turn_ids[0], dry_run=False)

        assert not content_file.exists()

    def test_execute_sets_consolidated_at(self, ec_repo, ec_db):
        session_id, turn_ids = _setup_db_with_turns(ec_repo, ec_db)
        consolidate_turn_content(ec_db, str(ec_repo), turn_ids[0], dry_run=False)

        row = ec_db.execute("SELECT consolidated_at FROM turns WHERE id = ?", (turn_ids[0],)).fetchone()
        assert row["consolidated_at"] is not None

    def test_execute_removes_turn_content_row(self, ec_repo, ec_db):
        session_id, turn_ids = _setup_db_with_turns(ec_repo, ec_db)
        consolidate_turn_content(ec_db, str(ec_repo), turn_ids[0], dry_run=False)

        row = ec_db.execute("SELECT * FROM turn_content WHERE turn_id = ?", (turn_ids[0],)).fetchone()
        assert row is None

    def test_execute_preserves_turn_metadata(self, ec_repo, ec_db):
        session_id, turn_ids = _setup_db_with_turns(ec_repo, ec_db)
        consolidate_turn_content(ec_db, str(ec_repo), turn_ids[0], dry_run=False)

        row = ec_db.execute("SELECT user_message, assistant_summary FROM turns WHERE id = ?", (turn_ids[0],)).fetchone()
        assert row["user_message"] == "user message 1"
        assert row["assistant_summary"] == "assistant summary 1"

    def test_idempotent_on_already_consolidated(self, ec_repo, ec_db):
        """Calling consolidate twice should not raise errors."""
        session_id, turn_ids = _setup_db_with_turns(ec_repo, ec_db)
        consolidate_turn_content(ec_db, str(ec_repo), turn_ids[0], dry_run=False)
        # Second call should not raise
        consolidate_turn_content(ec_db, str(ec_repo), turn_ids[0], dry_run=False)

    def test_returns_true_when_action_taken(self, ec_repo, ec_db):
        session_id, turn_ids = _setup_db_with_turns(ec_repo, ec_db)
        result = consolidate_turn_content(ec_db, str(ec_repo), turn_ids[0], dry_run=False)
        assert result is True

    def test_returns_false_on_dry_run(self, ec_repo, ec_db):
        session_id, turn_ids = _setup_db_with_turns(ec_repo, ec_db)
        result = consolidate_turn_content(ec_db, str(ec_repo), turn_ids[0], dry_run=True)
        assert result is False

    def test_missing_content_file_still_marks_consolidated(self, ec_repo, ec_db):
        """If content file is already gone, mark turn consolidated anyway (idempotent)."""
        session_id, turn_ids = _setup_db_with_turns(ec_repo, ec_db)
        # Delete the file manually
        row = ec_db.execute("SELECT content_path FROM turn_content WHERE turn_id = ?", (turn_ids[0],)).fetchone()
        content_file = Path(str(ec_repo)) / ".entirecontext" / row["content_path"]
        content_file.unlink()

        # Should not raise
        consolidate_turn_content(ec_db, str(ec_repo), turn_ids[0], dry_run=False)

        row2 = ec_db.execute("SELECT consolidated_at FROM turns WHERE id = ?", (turn_ids[0],)).fetchone()
        assert row2["consolidated_at"] is not None


# ---------------------------------------------------------------------------
# consolidate_old_turns
# ---------------------------------------------------------------------------


class TestConsolidateOldTurns:
    def test_dry_run_returns_candidates_count(self, ec_repo, ec_db):
        _setup_db_with_turns(ec_repo, ec_db)
        stats = consolidate_old_turns(ec_db, str(ec_repo), before_date="2099-01-01", dry_run=True)
        assert stats["candidates"] == 4
        assert stats["consolidated"] == 0

    def test_execute_returns_consolidated_count(self, ec_repo, ec_db):
        _setup_db_with_turns(ec_repo, ec_db)
        stats = consolidate_old_turns(ec_db, str(ec_repo), before_date="2099-01-01", dry_run=False)
        assert stats["consolidated"] == 4

    def test_execute_files_are_removed(self, ec_repo, ec_db):
        _setup_db_with_turns(ec_repo, ec_db)
        content_dir = Path(str(ec_repo)) / ".entirecontext" / "content"
        files_before = list(content_dir.rglob("*.jsonl"))
        assert len(files_before) == 4

        consolidate_old_turns(ec_db, str(ec_repo), before_date="2099-01-01", dry_run=False)

        files_after = list(content_dir.rglob("*.jsonl"))
        assert len(files_after) == 0

    def test_no_candidates_returns_zero(self, ec_repo, ec_db):
        _setup_db_with_turns(ec_repo, ec_db)
        stats = consolidate_old_turns(ec_db, str(ec_repo), before_date="2000-01-01", dry_run=False)
        assert stats["candidates"] == 0
        assert stats["consolidated"] == 0

    def test_stats_dict_has_expected_keys(self, ec_repo, ec_db):
        _setup_db_with_turns(ec_repo, ec_db)
        stats = consolidate_old_turns(ec_db, str(ec_repo), before_date="2099-01-01", dry_run=True)
        assert "candidates" in stats
        assert "consolidated" in stats

    def test_session_filter_passed_through(self, ec_repo, ec_db):
        session_id, _ = _setup_db_with_turns(ec_repo, ec_db)
        stats = consolidate_old_turns(
            ec_db, str(ec_repo), before_date="2099-01-01", session_id=session_id, dry_run=True
        )
        assert stats["candidates"] == 4

    def test_limit_passed_through(self, ec_repo, ec_db):
        _setup_db_with_turns(ec_repo, ec_db)
        stats = consolidate_old_turns(ec_db, str(ec_repo), before_date="2099-01-01", limit=2, dry_run=False)
        assert stats["consolidated"] == 2


# ---------------------------------------------------------------------------
# CLI: ec session consolidate
# ---------------------------------------------------------------------------


class TestSessionConsolidateCLI:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["session", "consolidate"])
            assert result.exit_code == 1

    def test_dry_run_by_default(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch(
                "entirecontext.core.consolidation.consolidate_old_turns",
                return_value={"candidates": 3, "consolidated": 0},
            ) as mock_consolidate,
        ):
            result = runner.invoke(app, ["session", "consolidate"])
            assert result.exit_code == 0
            # Should have been called with dry_run=True
            call_kwargs = mock_consolidate.call_args
            assert call_kwargs.kwargs.get("dry_run", True) is True

    def test_execute_flag(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch(
                "entirecontext.core.consolidation.consolidate_old_turns",
                return_value={"candidates": 3, "consolidated": 3},
            ) as mock_consolidate,
        ):
            result = runner.invoke(app, ["session", "consolidate", "--execute"])
            assert result.exit_code == 0
            call_kwargs = mock_consolidate.call_args
            assert call_kwargs.kwargs.get("dry_run") is False

    def test_before_option_passed(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch(
                "entirecontext.core.consolidation.consolidate_old_turns",
                return_value={"candidates": 0, "consolidated": 0},
            ) as mock_consolidate,
        ):
            runner.invoke(app, ["session", "consolidate", "--before", "2025-01-01"])
            call_kwargs = mock_consolidate.call_args
            assert "2025-01-01" in str(call_kwargs)

    def test_output_shows_candidates(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch(
                "entirecontext.core.consolidation.consolidate_old_turns",
                return_value={"candidates": 5, "consolidated": 0},
            ),
        ):
            result = runner.invoke(app, ["session", "consolidate"])
            assert "5" in result.output

    def test_output_shows_consolidated_count_on_execute(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch(
                "entirecontext.core.consolidation.consolidate_old_turns",
                return_value={"candidates": 4, "consolidated": 4},
            ),
        ):
            result = runner.invoke(app, ["session", "consolidate", "--execute"])
            assert "4" in result.output
