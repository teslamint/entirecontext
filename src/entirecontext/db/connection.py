"""Database connection management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_GLOBAL_DB_DIR = Path.home() / ".entirecontext" / "db"
_GLOBAL_DB_PATH = _GLOBAL_DB_DIR / "ec.db"


def _configure_connection(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row


def get_db(repo_path: str | Path) -> sqlite3.Connection:
    """Get a connection to the per-repo database."""
    db_path = Path(repo_path) / ".entirecontext" / "db" / "local.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    _configure_connection(conn)
    return conn


def get_global_db() -> sqlite3.Connection:
    """Get a connection to the global cross-repo index database."""
    _GLOBAL_DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_GLOBAL_DB_PATH))
    _configure_connection(conn)
    return conn


def get_memory_db() -> sqlite3.Connection:
    """Get an in-memory database (for testing)."""
    conn = sqlite3.connect(":memory:")
    _configure_connection(conn)
    return conn
