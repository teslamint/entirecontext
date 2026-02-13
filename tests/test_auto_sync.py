"""Tests for auto-sync module."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from entirecontext.sync.auto_sync import (
    should_sync,
    should_pull,
    acquire_sync_lock,
    release_sync_lock,
    _is_lock_stale,
    trigger_background_sync,
)


@pytest.fixture
def sync_conn(ec_db):
    ec_db.execute("INSERT OR REPLACE INTO sync_metadata (id, sync_status) VALUES (1, 'idle')")
    ec_db.commit()
    return ec_db


class TestShouldSync:
    def test_true_when_no_metadata_row(self, ec_db):
        ec_db.execute("DELETE FROM sync_metadata")
        ec_db.commit()
        assert should_sync(ec_db, {}) is True

    def test_true_when_last_export_at_is_none(self, sync_conn):
        sync_conn.execute("UPDATE sync_metadata SET last_export_at = NULL WHERE id = 1")
        sync_conn.commit()
        assert should_sync(sync_conn, {}) is True

    def test_false_within_cooldown(self, sync_conn):
        now = datetime.now(timezone.utc).isoformat()
        sync_conn.execute("UPDATE sync_metadata SET last_export_at = ? WHERE id = 1", (now,))
        sync_conn.commit()
        assert should_sync(sync_conn, {"cooldown_seconds": 300}) is False

    def test_true_when_cooldown_expired(self, sync_conn):
        old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        sync_conn.execute("UPDATE sync_metadata SET last_export_at = ? WHERE id = 1", (old,))
        sync_conn.commit()
        assert should_sync(sync_conn, {"cooldown_seconds": 300}) is True

    def test_false_when_syncing_not_stale(self, sync_conn):
        sync_conn.execute(
            "UPDATE sync_metadata SET sync_status = 'syncing', sync_pid = ? WHERE id = 1",
            (os.getpid(),),
        )
        sync_conn.commit()
        assert should_sync(sync_conn, {}) is False

    def test_true_when_lock_stale_dead_process(self, sync_conn):
        sync_conn.execute(
            "UPDATE sync_metadata SET sync_status = 'syncing', sync_pid = 999999 WHERE id = 1",
        )
        sync_conn.commit()
        with patch("entirecontext.sync.auto_sync.os.kill", side_effect=OSError):
            assert should_sync(sync_conn, {}) is True


class TestShouldPull:
    def test_true_when_no_metadata(self, ec_db):
        ec_db.execute("DELETE FROM sync_metadata")
        ec_db.commit()
        assert should_pull(ec_db, {}) is True

    def test_true_when_no_last_import_at(self, sync_conn):
        sync_conn.execute("UPDATE sync_metadata SET last_import_at = NULL WHERE id = 1")
        sync_conn.commit()
        assert should_pull(sync_conn, {}) is True

    def test_true_when_data_stale(self, sync_conn):
        old = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
        sync_conn.execute("UPDATE sync_metadata SET last_import_at = ? WHERE id = 1", (old,))
        sync_conn.commit()
        assert should_pull(sync_conn, {"pull_staleness_seconds": 600}) is True

    def test_false_when_data_fresh(self, sync_conn):
        now = datetime.now(timezone.utc).isoformat()
        sync_conn.execute("UPDATE sync_metadata SET last_import_at = ? WHERE id = 1", (now,))
        sync_conn.commit()
        assert should_pull(sync_conn, {"pull_staleness_seconds": 600}) is False


class TestAcquireSyncLock:
    def test_acquire_when_idle(self, sync_conn):
        assert acquire_sync_lock(sync_conn) is True
        row = sync_conn.execute("SELECT sync_status, sync_pid FROM sync_metadata WHERE id = 1").fetchone()
        assert row["sync_status"] == "syncing"
        assert row["sync_pid"] == os.getpid()

    def test_fail_when_already_syncing(self, sync_conn):
        sync_conn.execute("UPDATE sync_metadata SET sync_status = 'syncing' WHERE id = 1")
        sync_conn.commit()
        assert acquire_sync_lock(sync_conn) is False

    def test_creates_row_if_missing(self, ec_db):
        ec_db.execute("DELETE FROM sync_metadata")
        ec_db.commit()
        assert acquire_sync_lock(ec_db) is True
        row = ec_db.execute("SELECT sync_status FROM sync_metadata WHERE id = 1").fetchone()
        assert row["sync_status"] == "syncing"


class TestReleaseSyncLock:
    def test_release(self, sync_conn):
        sync_conn.execute(
            "UPDATE sync_metadata SET sync_status = 'syncing', sync_pid = ? WHERE id = 1",
            (os.getpid(),),
        )
        sync_conn.commit()
        release_sync_lock(sync_conn)
        row = sync_conn.execute("SELECT sync_status, sync_pid FROM sync_metadata WHERE id = 1").fetchone()
        assert row["sync_status"] == "idle"
        assert row["sync_pid"] is None


class TestIsLockStale:
    def test_stale_when_pid_null(self, sync_conn):
        sync_conn.execute("UPDATE sync_metadata SET sync_pid = NULL WHERE id = 1")
        sync_conn.commit()
        assert _is_lock_stale(sync_conn) is True

    def test_stale_when_process_dead(self, sync_conn):
        sync_conn.execute("UPDATE sync_metadata SET sync_pid = 999999 WHERE id = 1")
        sync_conn.commit()
        with patch("entirecontext.sync.auto_sync.os.kill", side_effect=OSError):
            assert _is_lock_stale(sync_conn) is True

    def test_not_stale_when_process_alive(self, sync_conn):
        sync_conn.execute("UPDATE sync_metadata SET sync_pid = ? WHERE id = 1", (os.getpid(),))
        sync_conn.commit()
        with patch("entirecontext.sync.auto_sync.os.kill") as mock_kill:
            mock_kill.return_value = None
            assert _is_lock_stale(sync_conn) is False
            mock_kill.assert_called_once_with(os.getpid(), 0)


class TestTriggerBackgroundSync:
    def test_success(self):
        with patch("entirecontext.sync.auto_sync.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            assert trigger_background_sync("/tmp/repo") is True

    def test_failure(self):
        with patch("entirecontext.sync.auto_sync.subprocess.Popen", side_effect=OSError("no")):
            assert trigger_background_sync("/tmp/repo") is False


class TestMaybeTriggerAutoSync:
    def test_calls_trigger_when_enabled(self, ec_repo):
        config = {"sync": {"auto_sync": True}}
        with (
            patch("entirecontext.core.config.load_config", return_value=config),
            patch("entirecontext.sync.auto_sync.trigger_background_sync") as mock_trigger,
        ):
            from entirecontext.hooks.session_lifecycle import _maybe_trigger_auto_sync

            _maybe_trigger_auto_sync(str(ec_repo))
            mock_trigger.assert_called_once_with(str(ec_repo))

    def test_noop_when_disabled(self, ec_repo):
        config = {"sync": {"auto_sync": False}}
        with (
            patch("entirecontext.core.config.load_config", return_value=config),
            patch("entirecontext.sync.auto_sync.trigger_background_sync") as mock_trigger,
        ):
            from entirecontext.hooks.session_lifecycle import _maybe_trigger_auto_sync

            _maybe_trigger_auto_sync(str(ec_repo))
            mock_trigger.assert_not_called()

    def test_no_crash_on_exception(self, ec_repo):
        with patch(
            "entirecontext.core.config.load_config",
            side_effect=RuntimeError("config broken"),
        ):
            from entirecontext.hooks.session_lifecycle import _maybe_trigger_auto_sync

            _maybe_trigger_auto_sync(str(ec_repo))


class TestSchemaMigrationV1ToV2:
    def test_migration_adds_columns(self, ec_repo):
        from entirecontext.db import get_db
        from entirecontext.db.migration import _apply_migrations

        conn = get_db(str(ec_repo))
        conn.execute("DROP TABLE IF EXISTS sync_metadata")
        conn.execute(
            """CREATE TABLE sync_metadata (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_export_at TEXT,
                last_import_at TEXT,
                sync_status TEXT DEFAULT 'idle'
            )"""
        )
        conn.execute("DELETE FROM schema_version WHERE version >= 2")
        conn.commit()

        _apply_migrations(conn, 1)

        conn.execute(
            "INSERT OR REPLACE INTO sync_metadata (id, last_sync_error, last_sync_duration_ms, sync_pid) VALUES (1, 'test', 100, 123)"
        )
        conn.commit()
        row = conn.execute(
            "SELECT last_sync_error, last_sync_duration_ms, sync_pid FROM sync_metadata WHERE id = 1"
        ).fetchone()
        assert row["last_sync_error"] == "test"
        assert row["last_sync_duration_ms"] == 100
        assert row["sync_pid"] == 123
        conn.close()
