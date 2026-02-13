"""Schema migration management. Forward-only."""

from __future__ import annotations

import sqlite3

from .schema import SCHEMA_VERSION, TABLES, FTS_TABLES, FTS_TRIGGERS


def get_current_version(conn: sqlite3.Connection) -> int:
    """Get current schema version. Returns 0 if no schema exists."""
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return row[0] if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        return 0


def init_schema(conn: sqlite3.Connection) -> None:
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
    conn.commit()


def check_and_migrate(conn: sqlite3.Connection) -> None:
    """Check schema version and apply pending migrations."""
    current = get_current_version(conn)

    if current == 0:
        init_schema(conn)
        return

    if current < SCHEMA_VERSION:
        _apply_migrations(conn, current)


def _apply_migrations(conn: sqlite3.Connection, from_version: int) -> None:
    """Apply sequential migrations from from_version to SCHEMA_VERSION."""
    migrations = _get_migrations()
    for version in range(from_version + 1, SCHEMA_VERSION + 1):
        if version in migrations:
            for sql in migrations[version]:
                conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                (version, f"Migration to v{version}"),
            )
    conn.commit()


def _get_migrations() -> dict[int, list[str]]:
    """Return migration SQL for each version transition.

    Add new entries as schema evolves:
        2: ["ALTER TABLE ...", "CREATE INDEX ..."],
    """
    return {}
