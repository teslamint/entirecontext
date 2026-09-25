"""Shared runtime context helpers."""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .repo_roots import RepoRoots, resolve_repo_roots, roots_for_workspace


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Own a BEGIN IMMEDIATE boundary, or defer to an outer owner if nested.

    Connections are configured with ``conn.autocommit = True`` (see
    ``db.connection._configure_connection``), so each DML self-commits unless
    an explicit ``BEGIN`` is open. This helper opens ``BEGIN IMMEDIATE`` on
    outer entry, increments a per-connection depth counter on nested entry,
    and only issues ``COMMIT``/``ROLLBACK`` when the depth returns to 0.

    Three nesting cases handled:

      1. **Helper-owned outer** (``_ec_tx_depth > 0``): increment depth,
         defer commit to the outermost helper exit. Symmetric tracking.
      2. **Raw-SQL outer** (``conn.in_transaction`` True with depth 0): a
         caller has opened ``BEGIN IMMEDIATE`` directly without coordinating
         with the depth counter. Defer without touching either marker; the
         raw caller manages its own COMMIT/ROLLBACK. This restores the
         deferral safety the previous ``conn.in_transaction``-based detector
         provided, so callers don't need to know about the private depth
         counter for nested correctness.
      3. **No outer** (both false): open a fresh ``BEGIN IMMEDIATE`` and own
         the boundary.
    """
    depth = getattr(conn, "_ec_tx_depth", 0)
    if depth > 0:
        conn._ec_tx_depth = depth + 1
        try:
            yield
        finally:
            conn._ec_tx_depth -= 1
        return

    if conn.in_transaction:
        # Raw-SQL outer owner; defer entirely without touching depth or
        # issuing COMMIT/ROLLBACK. The outer caller controls the boundary.
        yield
        return

    # Under conn.autocommit=True, conn.commit()/rollback() are no-ops because
    # Python's sqlite3 driver only tracks transactions it opened itself via
    # implicit BEGIN. Since we open BEGIN IMMEDIATE explicitly, we must close
    # it with explicit COMMIT/ROLLBACK SQL statements.
    conn.execute("BEGIN IMMEDIATE")
    conn._ec_tx_depth = 1
    try:
        yield
        conn.execute("COMMIT")
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn._ec_tx_depth = 0


def _find_git_root(path: str | Path = ".") -> str | None:
    roots = resolve_repo_roots(path)
    return roots.workspace_root if roots else None


@dataclass(slots=True)
class RequestContext:
    source: str
    session_id: str | None = None
    turn_id: str | None = None
    agent_type: str | None = None


@dataclass(slots=True)
class RepoContext:
    """Per-repository runtime context.

    ``repo_path`` is the canonical project root (DB, config, content); it is
    kept under that name for backward compatibility. ``workspace_root`` is the
    active checkout, which differs from ``repo_path`` in a linked worktree.
    """

    repo_path: str
    conn: sqlite3.Connection
    config: dict[str, Any]
    project: dict[str, Any] | None
    current_session_id: str | None
    workspace_root: str | None = None
    roots: RepoRoots | None = None

    @property
    def project_root(self) -> str:
        return self.repo_path

    @classmethod
    def from_cwd(cls, cwd: str | Path = ".", *, require_project: bool = False) -> RepoContext | None:
        repo_path = _find_git_root(cwd)
        if not repo_path:
            return None
        return cls.from_repo_path(repo_path, require_project=require_project)

    @classmethod
    def from_repo_path(cls, repo_path: str | Path, *, require_project: bool = False) -> RepoContext | None:
        from ..core.config import load_config
        from ..db import check_and_migrate, get_db

        roots = roots_for_workspace(str(Path(repo_path).resolve()))
        project_root = roots.project_root
        conn = get_db(project_root)
        check_and_migrate(conn)

        project_row = conn.execute("SELECT * FROM projects WHERE repo_path = ?", (project_root,)).fetchone()
        project = dict(project_row) if project_row else None
        if require_project and project is None:
            conn.close()
            return None

        from .session import get_current_session

        current_session = get_current_session(conn, workspace_root=roots.workspace_root)

        return cls(
            repo_path=project_root,
            conn=conn,
            config=load_config(project_root),
            project=project,
            current_session_id=current_session["id"] if current_session else None,
            workspace_root=roots.workspace_root,
            roots=roots,
        )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> RepoContext:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def as_request_context(
        self, *, source: str, turn_id: str | None = None, agent_type: str | None = None
    ) -> RequestContext:
        return RequestContext(
            source=source,
            session_id=self.current_session_id,
            turn_id=turn_id,
            agent_type=agent_type,
        )


@dataclass(slots=True)
class GlobalContext:
    conn: sqlite3.Connection

    @classmethod
    def create(cls) -> GlobalContext:
        from ..db import get_global_db
        from ..db.global_schema import init_global_schema

        conn = get_global_db()
        init_global_schema(conn)
        return cls(conn=conn)

    def list_registered_repos(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM repo_index ORDER BY repo_name").fetchall()
        repos = []
        for row in rows:
            repo = dict(row)
            if names and repo["repo_name"] not in names:
                continue
            repos.append(repo)
        return repos

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> GlobalContext:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
