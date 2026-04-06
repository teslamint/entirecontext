"""Unit tests for core/resolve.py and cli/helpers.py."""

from __future__ import annotations

import sqlite3

import pytest
import typer


# ---------------------------------------------------------------------------
# resolve.py
# ---------------------------------------------------------------------------


@pytest.fixture
def resolve_conn():
    """In-memory SQLite connection with the three allowed tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE decisions (id TEXT PRIMARY KEY);
        CREATE TABLE checkpoints (id TEXT PRIMARY KEY);
        CREATE TABLE assessments (id TEXT PRIMARY KEY);
        INSERT INTO decisions VALUES ('abc123def456');
        INSERT INTO decisions VALUES ('abc999xyz000');
        INSERT INTO checkpoints VALUES ('chk-aabbccdd');
        INSERT INTO assessments VALUES ('aaa-bbb-ccc');
        """
    )
    return conn


class TestResolveId:
    def test_exact_match(self, resolve_conn):
        from entirecontext.core.resolve import resolve_id

        assert resolve_id(resolve_conn, "decisions", "abc123def456") == "abc123def456"

    def test_prefix_match(self, resolve_conn):
        from entirecontext.core.resolve import resolve_id

        assert resolve_id(resolve_conn, "decisions", "abc123") == "abc123def456"

    def test_prefix_ambiguous_returns_a_match(self, resolve_conn):
        """When multiple rows share a prefix, one matching row is returned (undefined which)."""
        from entirecontext.core.resolve import resolve_id

        result = resolve_id(resolve_conn, "decisions", "abc")
        assert result in ("abc123def456", "abc999xyz000")

    def test_no_match_returns_none(self, resolve_conn):
        from entirecontext.core.resolve import resolve_id

        assert resolve_id(resolve_conn, "decisions", "zzznomatch") is None

    def test_disallowed_table_raises(self, resolve_conn):
        from entirecontext.core.resolve import resolve_id

        with pytest.raises(ValueError, match="not allowed"):
            resolve_id(resolve_conn, "turns", "anything")

    def test_disallowed_table_with_sql_injection_raises(self, resolve_conn):
        from entirecontext.core.resolve import resolve_id

        with pytest.raises(ValueError, match="not allowed"):
            resolve_id(resolve_conn, "decisions; DROP TABLE decisions; --", "x")

    def test_like_metachar_percent_in_value(self, resolve_conn):
        """A '%' in the search value should be treated literally, not as a wildcard."""
        from entirecontext.core.resolve import resolve_id

        assert resolve_id(resolve_conn, "decisions", "abc%") is None

    def test_like_metachar_underscore_in_value(self, resolve_conn):
        """An '_' in the search value should be treated literally."""
        from entirecontext.core.resolve import resolve_id

        assert resolve_id(resolve_conn, "decisions", "abc_23") is None

    def test_all_allowed_tables_accepted(self, resolve_conn):
        from entirecontext.core.resolve import resolve_id

        assert resolve_id(resolve_conn, "decisions", "abc123") is not None
        assert resolve_id(resolve_conn, "checkpoints", "chk-") is not None
        assert resolve_id(resolve_conn, "assessments", "aaa-") is not None

    def test_typed_helpers(self, resolve_conn):
        from entirecontext.core.resolve import (
            resolve_assessment_id,
            resolve_checkpoint_id,
            resolve_decision_id,
        )

        assert resolve_decision_id(resolve_conn, "abc123") == "abc123def456"
        assert resolve_checkpoint_id(resolve_conn, "chk-") == "chk-aabbccdd"
        assert resolve_assessment_id(resolve_conn, "aaa-") == "aaa-bbb-ccc"


class TestEscapeLike:
    def test_percent_escaped(self):
        from entirecontext.core.resolve import escape_like

        assert escape_like("a%b") == "a\\%b"

    def test_underscore_escaped(self):
        from entirecontext.core.resolve import escape_like

        assert escape_like("a_b") == "a\\_b"

    def test_backslash_escaped(self):
        from entirecontext.core.resolve import escape_like

        assert escape_like("a\\b") == "a\\\\b"

    def test_no_metacharacters_unchanged(self):
        from entirecontext.core.resolve import escape_like

        assert escape_like("abc123") == "abc123"


# ---------------------------------------------------------------------------
# cli/helpers.py
# ---------------------------------------------------------------------------


class TestGetRepoConnection:
    def test_exits_when_not_in_git_repo(self, monkeypatch, tmp_path):
        """Should raise typer.Exit(1) when find_git_root returns None."""
        monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda: None)

        from entirecontext.cli.helpers import get_repo_connection

        with pytest.raises(typer.Exit):
            get_repo_connection()

    def test_returns_connection_and_repo_path(self, ec_db, ec_repo, monkeypatch):
        """Should return (conn, repo_path) when called from a valid EC repo."""
        monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda: str(ec_repo))

        from entirecontext.cli.helpers import get_repo_connection

        conn, repo_path = get_repo_connection()
        try:
            assert repo_path == str(ec_repo)
            assert isinstance(conn, sqlite3.Connection)
        finally:
            conn.close()

    def test_migrate_false_skips_migration(self, ec_repo, monkeypatch):
        """migrate=False should still return a connection without error."""
        monkeypatch.setattr("entirecontext.core.project.find_git_root", lambda: str(ec_repo))

        from entirecontext.cli.helpers import get_repo_connection

        conn, _ = get_repo_connection(migrate=False)
        try:
            assert isinstance(conn, sqlite3.Connection)
        finally:
            conn.close()
