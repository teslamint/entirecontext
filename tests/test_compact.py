from pathlib import Path

from entirecontext.core.config import DEFAULT_CONFIG


def test_content_retention_days_default():
    assert DEFAULT_CONFIG["capture"]["content_retention_days"] == 30


from entirecontext.core.compact import find_orphan_content_files


class TestFindOrphanContentFiles:
    def test_no_orphans_when_all_referenced(self, ec_repo, ec_db):
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session
        from entirecontext.core.turn import create_turn, save_turn_content

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="s1")
        t = create_turn(ec_db, session["id"], 1, user_message="msg")
        save_turn_content(str(ec_repo), ec_db, t["id"], session["id"], '{"m": 1}')

        orphans = find_orphan_content_files(ec_db, str(ec_repo), min_age_seconds=0)
        assert orphans == []

    def test_detects_orphan_file(self, ec_repo, ec_db):
        content_dir = Path(str(ec_repo)) / ".entirecontext" / "content" / "orphan-session"
        content_dir.mkdir(parents=True)
        orphan_file = content_dir / "orphan-turn.jsonl"
        orphan_file.write_text('{"orphan": true}')

        orphans = find_orphan_content_files(ec_db, str(ec_repo), min_age_seconds=0)
        assert len(orphans) == 1
        assert orphans[0] == orphan_file


from entirecontext.core.compact import remove_orphan_content_files


class TestRemoveOrphanContentFiles:
    def test_dry_run_does_not_delete(self, ec_repo, ec_db):
        content_dir = Path(str(ec_repo)) / ".entirecontext" / "content" / "orphan-s"
        content_dir.mkdir(parents=True)
        (content_dir / "orphan.jsonl").write_text("{}")

        result = remove_orphan_content_files(ec_db, str(ec_repo), dry_run=True, min_age_seconds=0)
        assert result["orphans_found"] == 1
        assert result["orphans_removed"] == 0
        assert (content_dir / "orphan.jsonl").exists()

    def test_execute_deletes_orphans(self, ec_repo, ec_db):
        content_dir = Path(str(ec_repo)) / ".entirecontext" / "content" / "orphan-s"
        content_dir.mkdir(parents=True)
        orphan = content_dir / "orphan.jsonl"
        orphan.write_text("{}")

        result = remove_orphan_content_files(ec_db, str(ec_repo), dry_run=False, min_age_seconds=0)
        assert result["orphans_found"] == 1
        assert result["orphans_removed"] == 1
        assert not orphan.exists()

    def test_removes_empty_parent_dir(self, ec_repo, ec_db):
        content_dir = Path(str(ec_repo)) / ".entirecontext" / "content" / "empty-session"
        content_dir.mkdir(parents=True)
        (content_dir / "orphan.jsonl").write_text("{}")

        remove_orphan_content_files(ec_db, str(ec_repo), dry_run=False, min_age_seconds=0)
        assert not content_dir.exists()


from entirecontext.core.compact import measure_storage, vacuum_db


class TestMeasureStorage:
    def test_returns_content_and_db_sizes(self, ec_repo, ec_db):
        result = measure_storage(str(ec_repo))
        assert "content_bytes" in result
        assert "db_bytes" in result
        assert "content_file_count" in result
        assert isinstance(result["content_bytes"], int)
        assert isinstance(result["db_bytes"], int)


class TestVacuumDb:
    def test_vacuum_runs_without_error(self, ec_repo, ec_db):
        result = vacuum_db(str(ec_repo))
        assert "db_before" in result
        assert "db_after" in result
        assert result["db_after"] <= result["db_before"]


from entirecontext.core.compact import compact_repo


class TestCompactRepo:
    def test_dry_run_returns_report(self, ec_repo, ec_db):
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session
        from entirecontext.core.turn import create_turn, save_turn_content

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="s1")
        t = create_turn(ec_db, session["id"], 1, user_message="msg")
        save_turn_content(str(ec_repo), ec_db, t["id"], session["id"], '{"m": 1}')

        report = compact_repo(ec_db, str(ec_repo), retention_days=0, dry_run=True)
        assert "before" in report
        assert "consolidation" in report
        assert "orphans" in report
        assert report["consolidation"]["consolidated"] == 0  # dry run

    def test_execute_consolidates_and_reports(self, ec_repo, ec_db):
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session
        from entirecontext.core.turn import create_turn, save_turn_content

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="s1")
        t = create_turn(ec_db, session["id"], 1, user_message="msg")
        save_turn_content(str(ec_repo), ec_db, t["id"], session["id"], '{"m": 1}')

        report = compact_repo(ec_db, str(ec_repo), retention_days=0, dry_run=False)
        assert report["consolidation"]["consolidated"] == 1
        assert report["after"]["content_file_count"] == 0


from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestCompactCLI:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["compact"])
            assert result.exit_code == 1

    def test_dry_run_by_default(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.db.check_and_migrate"),
            patch(
                "entirecontext.core.compact.compact_repo",
                return_value={
                    "before": {"content_bytes": 1000, "content_file_count": 10, "db_bytes": 500},
                    "after": {"content_bytes": 1000, "content_file_count": 10, "db_bytes": 500},
                    "consolidation": {"candidates": 5, "consolidated": 0},
                    "orphans": {"orphans_found": 2, "orphans_removed": 0, "bytes_freed": 0},
                    "vacuum": {},
                    "retention_days": 30,
                    "dry_run": True,
                },
            ) as mock_compact,
        ):
            result = runner.invoke(app, ["compact"])
            assert result.exit_code == 0
            call_kwargs = mock_compact.call_args
            assert call_kwargs.kwargs.get("dry_run", True) is True

    def test_execute_flag(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.db.check_and_migrate"),
            patch(
                "entirecontext.core.compact.compact_repo",
                return_value={
                    "before": {"content_bytes": 1000, "content_file_count": 10, "db_bytes": 500},
                    "after": {"content_bytes": 200, "content_file_count": 2, "db_bytes": 400},
                    "consolidation": {"candidates": 8, "consolidated": 8},
                    "orphans": {"orphans_found": 1, "orphans_removed": 1, "bytes_freed": 100},
                    "vacuum": {"db_before": 500, "db_after": 400},
                    "retention_days": 30,
                    "dry_run": False,
                },
            ) as mock_compact,
        ):
            result = runner.invoke(app, ["compact", "--execute"])
            assert result.exit_code == 0
            call_kwargs = mock_compact.call_args
            assert call_kwargs.kwargs.get("dry_run") is False

    def test_retention_days_option(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.db.check_and_migrate"),
            patch(
                "entirecontext.core.compact.compact_repo",
                return_value={
                    "before": {"content_bytes": 0, "content_file_count": 0, "db_bytes": 0},
                    "after": {"content_bytes": 0, "content_file_count": 0, "db_bytes": 0},
                    "consolidation": {"candidates": 0, "consolidated": 0},
                    "orphans": {"orphans_found": 0, "orphans_removed": 0, "bytes_freed": 0},
                    "vacuum": {},
                    "retention_days": 7,
                    "dry_run": True,
                },
            ) as mock_compact,
        ):
            runner.invoke(app, ["compact", "--retention-days", "7"])
            call_kwargs = mock_compact.call_args
            assert call_kwargs.kwargs.get("retention_days") == 7
