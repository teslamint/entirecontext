"""Shared runtime context helpers."""

from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _find_git_root(path: str | Path = ".") -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


@dataclass(slots=True)
class RequestContext:
    source: str
    session_id: str | None = None
    turn_id: str | None = None
    agent_type: str | None = None


@dataclass(slots=True)
class RepoContext:
    repo_path: str
    conn: sqlite3.Connection
    config: dict[str, Any]
    project: dict[str, Any] | None
    current_session_id: str | None

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

        resolved_repo_path = str(Path(repo_path).resolve())
        conn = get_db(resolved_repo_path)
        check_and_migrate(conn)

        project_row = conn.execute("SELECT * FROM projects WHERE repo_path = ?", (resolved_repo_path,)).fetchone()
        project = dict(project_row) if project_row else None
        if require_project and project is None:
            conn.close()
            return None

        current_session = conn.execute(
            "SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY last_activity_at DESC LIMIT 1"
        ).fetchone()

        return cls(
            repo_path=resolved_repo_path,
            conn=conn,
            config=load_config(resolved_repo_path),
            project=project,
            current_session_id=current_session["id"] if current_session else None,
        )

    def close(self) -> None:
        self.conn.close()

    def as_request_context(self, *, source: str, turn_id: str | None = None, agent_type: str | None = None) -> RequestContext:
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
