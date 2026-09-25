"""Database connection management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_GLOBAL_DB_DIR = Path.home() / ".entirecontext" / "db"
_GLOBAL_DB_PATH = _GLOBAL_DB_DIR / "ec.db"


class _ECConnection(sqlite3.Connection):
    """sqlite3.Connection subclass that supports ad-hoc instance attributes.

    The base ``sqlite3.Connection`` is a built-in C type without ``__dict__``,
    so attempting ``conn._ec_tx_depth = 1`` on a stock connection raises
    ``AttributeError``. Subclassing in pure Python adds the dict slot, which
    ``core.context.transaction`` relies on to track per-connection nesting.
    """


def _configure_connection(conn: sqlite3.Connection) -> None:
    conn.autocommit = True
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row


class LinkedWorktreeDatabaseError(RuntimeError):
    """Raised when a caller asks for a DB rooted at a linked Git worktree.

    All linked worktrees share the main worktree's database; opening one at the
    worktree path would silently fork the project's memory.
    """


def db_path_for(project_root: str | Path) -> Path:
    """Return the per-repo database path under a canonical project root."""
    return Path(project_root) / ".entirecontext" / "db" / "local.db"


def get_db(repo_path: str | Path) -> sqlite3.Connection:
    """Get a connection to the per-repo database.

    ``repo_path`` must be the canonical project root; a linked worktree root
    raises ``LinkedWorktreeDatabaseError`` instead of creating a new DB there.
    """
    if (Path(repo_path) / ".git").is_file():
        from ..core.repo_roots import is_linked_worktree_root

        if is_linked_worktree_root(repo_path):
            raise LinkedWorktreeDatabaseError(
                f"{repo_path} is a linked Git worktree; open the database at its canonical project root instead"
            )
    db_path = db_path_for(repo_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), factory=_ECConnection)
    _configure_connection(conn)
    return conn


def get_global_db() -> sqlite3.Connection:
    """Get a connection to the global cross-repo index database."""
    _GLOBAL_DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_GLOBAL_DB_PATH), factory=_ECConnection)
    _configure_connection(conn)
    return conn


def get_memory_db() -> sqlite3.Connection:
    """Get an in-memory database (for testing)."""
    conn = sqlite3.connect(":memory:", factory=_ECConnection, check_same_thread=False)
    _configure_connection(conn)
    return conn
