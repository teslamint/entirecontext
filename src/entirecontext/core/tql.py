"""Temporal Query Language — ref resolution and filter injection."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


class TQLError(Exception):
    """Raised on invalid temporal references or empty time ranges."""


@dataclass
class TQLContext:
    since: str | None = None
    until: str | None = None
    until_exclusive: bool = False

    @classmethod
    def validated(cls, since: str | None = None, until: str | None = None, until_exclusive: bool = False) -> TQLContext:
        ctx = cls(since=since, until=until, until_exclusive=until_exclusive)
        if ctx.since and ctx.until and ctx.since > ctx.until:
            raise TQLError(f"Empty time range: --since ({ctx.since}) is after --until ({ctx.until})")
        return ctx


def resolve_temporal_ref(ref: str, *, repo_path: str | None = None) -> tuple[str, bool]:
    """Resolve git ref or ISO date to (normalized_utc_string, is_date_only).

    Returns a tuple of (timestamp in 'YYYY-MM-DD HH:MM:SS' UTC format, is_date_only).
    """
    ts, is_date_only = _try_parse_iso(ref)
    if ts is not None:
        return ts, is_date_only

    if repo_path:
        ts = _resolve_git_ref(ref, repo_path)
        if ts is not None:
            return ts, False

    raise TQLError(f"Cannot resolve temporal reference '{ref}': not a valid git ref or date")


def resolve_until(ref: str, *, repo_path: str | None = None) -> tuple[str, bool]:
    """Resolve an --until ref with date-only expansion.

    For date-only inputs (e.g. "2026-04-01"), expands to next day midnight
    with exclusive semantics so that the entire target day is included.
    Returns (timestamp, until_exclusive).
    """
    ts, is_date_only = resolve_temporal_ref(ref, repo_path=repo_path)
    if is_date_only:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") + timedelta(days=1)
        return dt.strftime("%Y-%m-%d %H:%M:%S"), True
    return ts, False


def _try_parse_iso(ref: str) -> tuple[str | None, bool]:
    """Parse ISO date/datetime. Returns (normalized_utc, is_date_only)."""
    ref = ref.strip()

    # date-only: YYYY-MM-DD (exactly 10 chars, no T or space+time)
    if len(ref) == 10 and ref[4] == "-" and ref[7] == "-":
        try:
            datetime.strptime(ref, "%Y-%m-%d")
            return f"{ref} 00:00:00", True
        except ValueError:
            return None, False

    # datetime with timezone: try fromisoformat
    try:
        dt = datetime.fromisoformat(ref)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S"), False
    except ValueError:
        pass

    return None, False


def _resolve_git_ref(ref: str, repo_path: str) -> str | None:
    """git log -1 --format=%cI <ref> → normalized UTC timestamp."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI", ref],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=repo_path,
        )
        if result.returncode == 0 and result.stdout.strip():
            raw = result.stdout.strip()
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return None


def apply_temporal_filters(
    conditions: list[str], params: list, tql: TQLContext | None, column: str
) -> None:
    """Append datetime()-normalized WHERE clauses for since/until bounds."""
    if not tql:
        return
    if tql.since:
        conditions.append(f"datetime({column}) >= datetime(?)")
        params.append(tql.since)
    if tql.until:
        op = "<" if tql.until_exclusive else "<="
        conditions.append(f"datetime({column}) {op} datetime(?)")
        params.append(tql.until)
