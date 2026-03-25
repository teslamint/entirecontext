"""Runtime helpers for MCP tool modules."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(slots=True)
class ServiceRegistry:
    name: str = "entirecontext"


def get_repo_db():
    from . import server

    return server._get_repo_db()


def detect_current_session(conn):
    from . import server

    return server._detect_current_session(conn)


def record_search_event(conn, **kwargs):
    from . import server

    return server._record_search_event(conn, **kwargs)


def record_selection(conn, **kwargs):
    from . import server

    return server._record_selection(conn, **kwargs)


def normalize_repo_names(repos: list[str] | None) -> list[str] | None:
    return None if not repos or repos == ["*"] else repos


def error_payload(message: str, *, warnings: list | None = None, **extra) -> str:
    payload = {"error": message}
    if warnings:
        payload["warnings"] = warnings
    payload.update(extra)
    return json.dumps(payload)
