"""Auto-sync: background export on session end, lazy pull before cross-repo queries."""

from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def should_sync(conn: sqlite3.Connection, config: dict) -> bool:
    """Check if enough time has passed since last sync and not currently syncing."""
    cooldown = config.get("cooldown_seconds", 300)
    row = conn.execute("SELECT last_export_at, sync_status FROM sync_metadata WHERE id = 1").fetchone()
    if not row:
        return True
    if row["sync_status"] == "syncing":
        if _is_lock_stale(conn):
            release_sync_lock(conn)
            return True
        return False
    if row["last_export_at"]:
        last = datetime.fromisoformat(row["last_export_at"])
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        return elapsed >= cooldown
    return True


def should_pull(conn: sqlite3.Connection, config: dict) -> bool:
    """Check if imported data is stale enough to warrant a pull."""
    staleness = config.get("pull_staleness_seconds", 600)
    row = conn.execute("SELECT last_import_at FROM sync_metadata WHERE id = 1").fetchone()
    if not row or not row["last_import_at"]:
        return True
    last = datetime.fromisoformat(row["last_import_at"])
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return elapsed >= staleness


def acquire_sync_lock(conn: sqlite3.Connection) -> bool:
    """Atomic lock acquisition via conditional UPDATE. Returns True if acquired."""
    conn.execute("INSERT OR IGNORE INTO sync_metadata (id, sync_status) VALUES (1, 'idle')")
    cursor = conn.execute(
        "UPDATE sync_metadata SET sync_status = 'syncing', sync_pid = ? WHERE id = 1 AND sync_status = 'idle'",
        (os.getpid(),),
    )
    conn.commit()
    return cursor.rowcount > 0


def release_sync_lock(conn: sqlite3.Connection) -> None:
    """Release sync lock."""
    conn.execute("UPDATE sync_metadata SET sync_status = 'idle', sync_pid = NULL WHERE id = 1")
    conn.commit()


def _is_lock_stale(conn: sqlite3.Connection) -> bool:
    """Check if the process holding the lock is still alive."""
    row = conn.execute("SELECT sync_pid FROM sync_metadata WHERE id = 1").fetchone()
    if not row or not row["sync_pid"]:
        return True
    try:
        os.kill(row["sync_pid"], 0)
        return False
    except OSError:
        return True


def trigger_background_sync(repo_path: str) -> bool:
    """Spawn a detached subprocess to run sync. Returns True if spawned."""
    try:
        subprocess.Popen(
            [sys.executable, "-m", "entirecontext.sync.auto_sync", "sync", repo_path],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        logger.debug("Failed to spawn background sync", exc_info=True)
        return False


def run_sync(repo_path: str) -> None:
    """Entry point for background subprocess. Opens DB, acquires lock, syncs, releases."""
    from ..core.config import load_config
    from ..db import get_db

    conn = get_db(repo_path)
    config = load_config(repo_path).get("sync", {})

    if not acquire_sync_lock(conn):
        conn.close()
        return

    try:
        from .engine import perform_sync

        result = perform_sync(conn, repo_path, config, quiet=True)
        if result.get("error"):
            conn.execute(
                "UPDATE sync_metadata SET last_sync_error = ? WHERE id = 1",
                (result["error"],),
            )
            conn.commit()
    except Exception as exc:
        try:
            conn.execute(
                "UPDATE sync_metadata SET last_sync_error = ? WHERE id = 1",
                (str(exc),),
            )
            conn.commit()
        except Exception:
            pass
    finally:
        release_sync_lock(conn)
        conn.close()


def run_pull(repo_path: str) -> None:
    """Inline pull before cross-repo query."""
    from ..core.config import load_config
    from ..db import get_db

    conn = get_db(repo_path)
    config = load_config(repo_path).get("sync", {})

    try:
        from .engine import perform_pull

        perform_pull(conn, repo_path, config, quiet=True)
    except Exception:
        logger.debug("Lazy pull failed for %s", repo_path, exc_info=True)
    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "sync":
        run_sync(sys.argv[2])
