"""Async assessment worker — background process management.

Provides a thin layer for launching and tracking a background worker process.
The worker's PID is stored in ``<repo>/.entirecontext/worker.pid`` so that
the CLI can later query its status or terminate it.

Typical usage (hook handler launching background assessment):
    pid = launch_worker(repo_path, ["ec", "futures", "assess", "--diff", diff])
    # returns immediately; assessment runs in the background

No external dependencies — pure standard library (subprocess, os, pathlib).
"""

from __future__ import annotations

import errno
import os
import subprocess
from pathlib import Path


def _pid_file(repo_path: str) -> Path:
    """Return the path to the worker PID file."""
    return Path(repo_path) / ".entirecontext" / "worker.pid"


def get_worker_pid(repo_path: str) -> int | None:
    """Read the worker PID from the PID file.

    Returns None if the file does not exist or contains invalid content.
    """
    pid_path = _pid_file(repo_path)
    if not pid_path.exists():
        return None
    try:
        return int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return None


def is_worker_running(pid: int) -> bool:
    """Return True if the process with the given PID is alive.

    Uses ``os.kill(pid, 0)`` (signal 0 = existence check).
    - ``ProcessLookupError`` / ``OSError(ESRCH)`` → process does not exist → False
    - ``PermissionError`` → process exists but we lack signal permission → True
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        # PermissionError or other errno: process exists but we can't signal it
        return True


def launch_worker(repo_path: str, cmd: list[str]) -> int:
    """Launch *cmd* as a detached background process and record its PID.

    The child process is started with ``start_new_session=True`` so it is
    detached from the parent's terminal and process group.  Its PID is
    written to ``<repo>/.entirecontext/worker.pid``.

    Args:
        repo_path: Absolute path to the git repository root.
        cmd: Command + arguments to execute (passed directly to ``Popen``).

    Returns:
        The PID of the launched process.
    """
    pid_path = _pid_file(repo_path)
    pid_path.parent.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        cmd,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid_path.write_text(f"{proc.pid}\n")
    return proc.pid


def stop_worker(repo_path: str) -> str:
    """Send SIGTERM to the worker and remove the PID file.

    Returns a string indicating the outcome:
    - ``"none"``   — no PID file found; nothing to do.
    - ``"killed"`` — SIGTERM was sent successfully.
    - ``"stale"``  — PID file existed but the process was already gone.

    Raises:
        PermissionError: if the worker process exists but SIGTERM cannot be
            delivered due to OS permission restrictions.
    """
    pid = get_worker_pid(repo_path)
    if pid is None:
        return "none"

    outcome = "killed"
    try:
        os.kill(pid, 15)  # SIGTERM
    except ProcessLookupError:
        # Process already gone — clean up the stale PID file.
        outcome = "stale"
    # PermissionError propagates so the caller knows the stop failed.

    pid_path = _pid_file(repo_path)
    try:
        pid_path.unlink()
    except OSError:
        pass

    return outcome


def worker_status(repo_path: str) -> dict:
    """Return a dict describing the current worker state.

    Keys:
        ``running`` (bool): True if a live worker process is detected.
        ``pid`` (int | None): PID read from the PID file (None if no file).
        ``stale`` (bool, optional): Present and True when a PID file exists
            but the referenced process is no longer alive.
    """
    pid = get_worker_pid(repo_path)
    if pid is None:
        return {"running": False, "pid": None}

    if is_worker_running(pid):
        return {"running": True, "pid": pid}

    return {"running": False, "pid": pid, "stale": True}
