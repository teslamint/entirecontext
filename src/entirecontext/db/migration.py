"""Schema migration management. Forward-only."""

from __future__ import annotations

import sqlite3

from .migrations import get_migrations
from .schema import FTS_TABLES, FTS_TRIGGERS, SCHEMA_VERSION, TABLES


def get_current_version(conn: sqlite3.Connection) -> int:
    """Get current schema version. Returns 0 if no schema exists."""
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return row[0] if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        return 0


def bootstrap_schema(conn: sqlite3.Connection) -> None:
    """Initialize the full schema from scratch."""
    for name, sql in TABLES.items():
        for statement in sql.strip().split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(statement)

    for name, sql in FTS_TABLES.items():
        conn.execute(sql.strip().rstrip(";"))

    for name, sql in FTS_TRIGGERS.items():
        conn.execute(sql.strip())

    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (SCHEMA_VERSION, "Initial schema"),
    )


def check_and_migrate(conn: sqlite3.Connection) -> None:
    """Check schema version and apply pending migrations."""
    current = get_current_version(conn)

    if current == 0:
        bootstrap_schema(conn)
        return

    if current < SCHEMA_VERSION:
        apply_migrations(conn, current, SCHEMA_VERSION)


def apply_migrations(conn: sqlite3.Connection, from_version: int, to_version: int | None = None) -> None:
    """Apply sequential migrations from from_version to SCHEMA_VERSION.

    Each migration is a list of SQL strings or single-argument callables that
    receive the connection as their sole argument.  Callables are used when the
    migration logic requires conditional checks (e.g. ``ALTER TABLE ADD COLUMN``
    which is not idempotent in SQLite).
    """
    migrations = get_migrations()
    target_version = to_version or SCHEMA_VERSION
    for version in range(from_version + 1, target_version + 1):
        if version in migrations:
            for step in migrations[version]:
                if callable(step):
                    step(conn)
                else:
                    conn.execute(step)
            conn.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                (version, f"Migration to v{version}"),
            )


def _apply_migrations(conn: sqlite3.Connection, current_version: int) -> None:
    """Backward-compatible migration entrypoint."""
    apply_migrations(conn, current_version, SCHEMA_VERSION)


def init_schema(conn: sqlite3.Connection) -> None:
    """Backward-compatible alias for schema bootstrap."""
    bootstrap_schema(conn)
