"""Tests for async assessment worker — background process management."""

from __future__ import annotations

import errno
from unittest.mock import MagicMock, patch

import pytest

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.async_worker import (
    get_worker_pid,
    is_worker_running,
    launch_worker,
    stop_worker,
    worker_status,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# get_worker_pid
# ---------------------------------------------------------------------------


class TestGetWorkerPid:
    def test_returns_none_when_no_pid_file(self, tmp_path):
        assert get_worker_pid(str(tmp_path)) is None

    def test_returns_pid_from_file(self, tmp_path):
        (tmp_path / ".entirecontext").mkdir()
        (tmp_path / ".entirecontext" / "worker.pid").write_text("12345\n")
        assert get_worker_pid(str(tmp_path)) == 12345

    def test_returns_none_on_malformed_content(self, tmp_path):
        (tmp_path / ".entirecontext").mkdir()
        (tmp_path / ".entirecontext" / "worker.pid").write_text("not-a-number\n")
        assert get_worker_pid(str(tmp_path)) is None

    def test_returns_none_on_empty_file(self, tmp_path):
        (tmp_path / ".entirecontext").mkdir()
        (tmp_path / ".entirecontext" / "worker.pid").write_text("")
        assert get_worker_pid(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# is_worker_running
# ---------------------------------------------------------------------------


class TestIsWorkerRunning:
    def test_returns_true_when_process_alive(self):
        with patch("os.kill", return_value=None):
            assert is_worker_running(12345) is True

    def test_returns_false_when_process_lookup_error(self):
        with patch("os.kill", side_effect=ProcessLookupError):
            assert is_worker_running(12345) is False

    def test_returns_true_when_permission_error(self):
        # PermissionError means the process exists but we can't signal it
        with patch("os.kill", side_effect=PermissionError):
            assert is_worker_running(12345) is True

    def test_returns_false_on_oserror_no_such_process(self):
        with patch("os.kill", side_effect=OSError(errno.ESRCH, "No such process")):
            assert is_worker_running(12345) is False


# ---------------------------------------------------------------------------
# launch_worker
# ---------------------------------------------------------------------------


class TestLaunchWorker:
    def test_returns_pid(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        with patch("subprocess.Popen", return_value=mock_proc):
            pid = launch_worker(str(tmp_path), ["echo", "hello"])
        assert pid == 99999

    def test_creates_pid_file(self, tmp_path):
        (tmp_path / ".entirecontext").mkdir()
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        with patch("subprocess.Popen", return_value=mock_proc):
            launch_worker(str(tmp_path), ["echo", "hello"])
        pid_file = tmp_path / ".entirecontext" / "worker.pid"
        assert pid_file.exists()
        assert pid_file.read_text().strip() == "99999"

    def test_creates_entirecontext_dir_if_missing(self, tmp_path):
        # .entirecontext does NOT exist yet
        mock_proc = MagicMock()
        mock_proc.pid = 12
        with patch("subprocess.Popen", return_value=mock_proc):
            launch_worker(str(tmp_path), ["echo"])
        assert (tmp_path / ".entirecontext").is_dir()

    def test_popen_called_with_correct_cmd(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.pid = 1
        cmd = ["ec", "futures", "assess", "--diff", "hello"]
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            launch_worker(str(tmp_path), cmd)
        assert mock_popen.call_args.args[0] == cmd

    def test_popen_starts_detached(self, tmp_path):
        """Worker must be started outside the current process group."""
        mock_proc = MagicMock()
        mock_proc.pid = 1
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            launch_worker(str(tmp_path), ["echo"])
        kwargs = mock_popen.call_args.kwargs
        # start_new_session=True detaches the child from the parent's TTY/group
        assert kwargs.get("start_new_session") is True


# ---------------------------------------------------------------------------
# stop_worker
# ---------------------------------------------------------------------------


class TestStopWorker:
    def test_returns_none_when_no_pid_file(self, tmp_path):
        assert stop_worker(str(tmp_path)) == "none"

    def test_kills_process(self, tmp_path):
        (tmp_path / ".entirecontext").mkdir()
        (tmp_path / ".entirecontext" / "worker.pid").write_text("55555\n")
        with patch("os.kill") as mock_kill:
            stop_worker(str(tmp_path))
        mock_kill.assert_called_once_with(55555, 15)  # SIGTERM

    def test_removes_pid_file_after_stop(self, tmp_path):
        (tmp_path / ".entirecontext").mkdir()
        (tmp_path / ".entirecontext" / "worker.pid").write_text("55555\n")
        with patch("os.kill"):
            stop_worker(str(tmp_path))
        assert not (tmp_path / ".entirecontext" / "worker.pid").exists()

    def test_returns_killed_on_success(self, tmp_path):
        (tmp_path / ".entirecontext").mkdir()
        (tmp_path / ".entirecontext" / "worker.pid").write_text("55555\n")
        with patch("os.kill"):
            result = stop_worker(str(tmp_path))
        assert result == "killed"

    def test_returns_stale_when_process_already_dead(self, tmp_path):
        (tmp_path / ".entirecontext").mkdir()
        (tmp_path / ".entirecontext" / "worker.pid").write_text("55555\n")
        with patch("os.kill", side_effect=ProcessLookupError):
            result = stop_worker(str(tmp_path))
        assert result == "stale"
        assert not (tmp_path / ".entirecontext" / "worker.pid").exists()

    def test_raises_permission_error_when_cannot_signal(self, tmp_path):
        (tmp_path / ".entirecontext").mkdir()
        (tmp_path / ".entirecontext" / "worker.pid").write_text("55555\n")
        with patch("os.kill", side_effect=PermissionError):
            with pytest.raises(PermissionError):
                stop_worker(str(tmp_path))


# ---------------------------------------------------------------------------
# worker_status
# ---------------------------------------------------------------------------


class TestWorkerStatus:
    def test_idle_when_no_pid_file(self, tmp_path):
        status = worker_status(str(tmp_path))
        assert status["running"] is False
        assert status["pid"] is None

    def test_running_when_pid_file_and_alive_process(self, tmp_path):
        (tmp_path / ".entirecontext").mkdir()
        (tmp_path / ".entirecontext" / "worker.pid").write_text("11111\n")
        with patch("os.kill", return_value=None):
            status = worker_status(str(tmp_path))
        assert status["running"] is True
        assert status["pid"] == 11111

    def test_stale_when_pid_file_but_dead_process(self, tmp_path):
        (tmp_path / ".entirecontext").mkdir()
        (tmp_path / ".entirecontext" / "worker.pid").write_text("22222\n")
        with patch("os.kill", side_effect=ProcessLookupError):
            status = worker_status(str(tmp_path))
        assert status["running"] is False
        assert status.get("stale") is True

    def test_stale_pid_not_in_running_status(self, tmp_path):
        (tmp_path / ".entirecontext").mkdir()
        (tmp_path / ".entirecontext" / "worker.pid").write_text("33333\n")
        with patch("os.kill", side_effect=ProcessLookupError):
            status = worker_status(str(tmp_path))
        assert status["running"] is False


# ---------------------------------------------------------------------------
# CLI: ec futures worker-status / worker-stop / worker-launch
# ---------------------------------------------------------------------------


class TestFuturesWorkerCLI:
    def test_worker_status_idle(self):
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.core.async_worker.worker_status", return_value={"running": False, "pid": None}),
        ):
            result = runner.invoke(app, ["futures", "worker-status"])
        assert result.exit_code == 0
        assert (
            "idle" in result.output.lower() or "no" in result.output.lower() or "not running" in result.output.lower()
        )

    def test_worker_status_running(self):
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.core.async_worker.worker_status", return_value={"running": True, "pid": 12345}),
        ):
            result = runner.invoke(app, ["futures", "worker-status"])
        assert result.exit_code == 0
        assert "12345" in result.output or "running" in result.output.lower()

    def test_worker_status_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["futures", "worker-status"])
        assert result.exit_code == 1

    def test_worker_stop_no_worker(self):
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.core.async_worker.stop_worker", return_value="none"),
        ):
            result = runner.invoke(app, ["futures", "worker-stop"])
        assert result.exit_code == 0
        assert "no" in result.output.lower() or "not" in result.output.lower()

    def test_worker_stop_success(self):
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.core.async_worker.stop_worker", return_value="killed"),
        ):
            result = runner.invoke(app, ["futures", "worker-stop"])
        assert result.exit_code == 0
        assert "stop" in result.output.lower() or "sigterm" in result.output.lower()

    def test_worker_stop_stale(self):
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.core.async_worker.stop_worker", return_value="stale"),
        ):
            result = runner.invoke(app, ["futures", "worker-stop"])
        assert result.exit_code == 0
        assert "stale" in result.output.lower() or "removed" in result.output.lower()

    def test_worker_stop_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["futures", "worker-stop"])
        assert result.exit_code == 1

    def test_worker_launch_invokes_launch_worker(self):
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.core.async_worker.launch_worker", return_value=42) as mock_launch,
        ):
            result = runner.invoke(app, ["futures", "worker-launch"])
        assert result.exit_code == 0
        mock_launch.assert_called_once()

    def test_worker_launch_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["futures", "worker-launch"])
        assert result.exit_code == 1

    def test_worker_launch_shows_pid(self):
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.core.async_worker.launch_worker", return_value=9876),
        ):
            result = runner.invoke(app, ["futures", "worker-launch"])
        assert "9876" in result.output
