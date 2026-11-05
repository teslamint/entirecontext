"""File-backed, cross-process leases for assessment enrichment."""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .async_worker import file_lock


def _path(repo_path: str) -> Path:
    return Path(repo_path) / ".entirecontext" / "state" / "enrich-claims.json"


@contextmanager
def _store(repo_path: str, now: float) -> Iterator[dict[str, Any]]:
    path = _path(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path.parent / "enrich-claims.lock"):
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                data = {}
            data = {
                key: value
                for key, value in data.items()
                if isinstance(value, dict)
                and isinstance(value.get("attempts"), int)
                and isinstance(value.get("lease_until"), (int, float))
            }
        except (OSError, ValueError, TypeError):
            data = {}
        yield data
        data = {
            key: value
            for key, value in data.items()
            if isinstance(value, dict) and value.get("lease_until", float("-inf")) >= now - 7 * 86400
        }
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=".enrich-claims-")
        try:
            with os.fdopen(fd, "w") as out:
                json.dump(data, out)
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def claim_candidates(
    repo_path: str,
    candidates: list[dict[str, Any]],
    *,
    max_claims: int = 10,
    lease_seconds: int = 1800,
    max_attempts: int = 5,
    now: float | None = None,
) -> list[dict[str, Any]]:
    current = time.time() if now is None else now
    claimed: list[dict[str, Any]] = []
    with _store(repo_path, current) as data:
        for candidate in candidates:
            if len(claimed) >= max_claims:
                break
            key = str(candidate["id"])
            entry = data.get(key, {})
            if current < entry.get("lease_until", 0) or entry.get("attempts", 0) >= max_attempts:
                continue
            data[key] = {"attempts": entry.get("attempts", 0) + 1, "lease_until": current + lease_seconds}
            claimed.append(candidate)
    return claimed


def record_failure(
    repo_path: str,
    assessment_id: str,
    *,
    now: float | None = None,
    base_seconds: int = 900,
    cap_seconds: int = 21600,
) -> None:
    current = time.time() if now is None else now
    with _store(repo_path, current) as data:
        entry = data.get(str(assessment_id))
        if entry:
            entry["lease_until"] = current + min(cap_seconds, base_seconds * 2 ** (entry["attempts"] - 1))


def record_success(repo_path: str, assessment_id: str) -> None:
    with _store(repo_path, time.time()) as data:
        data.pop(str(assessment_id), None)
