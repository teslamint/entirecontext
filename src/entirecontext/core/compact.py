"""Database and content compaction — consolidate, clean orphans, vacuum."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def find_orphan_content_files(
    conn: sqlite3.Connection, repo_path: str, *, min_age_seconds: int = 3600
) -> list[Path]:
    """Find JSONL content files on disk that have no matching turn_content row.

    Args:
        min_age_seconds: Only consider files whose mtime is older than this
            many seconds ago (default 3600). Protects against deleting files
            from in-flight turn writes that haven't committed yet.
    """
    import time

    base = Path(repo_path) / ".entirecontext"
    content_dir = base / "content"
    if not content_dir.exists():
        return []

    cutoff_mtime = time.time() - min_age_seconds

    rows = conn.execute("SELECT content_path FROM turn_content").fetchall()
    known_paths = {(base / row["content_path"]).resolve() for row in rows}

    orphans = []
    for jsonl_file in content_dir.rglob("*.jsonl"):
        if jsonl_file.resolve() not in known_paths:
            try:
                mtime = jsonl_file.stat().st_mtime
            except (FileNotFoundError, OSError):
                continue
            if mtime < cutoff_mtime:
                orphans.append(jsonl_file)

    return sorted(orphans)


def remove_orphan_content_files(
    conn: sqlite3.Connection, repo_path: str, *, dry_run: bool = True, min_age_seconds: int = 3600
) -> dict[str, int]:
    """Find and optionally remove orphan content files.

    Returns dict with orphans_found, orphans_removed, bytes_freed.
    """
    orphans = find_orphan_content_files(conn, repo_path, min_age_seconds=min_age_seconds)
    bytes_freed = 0

    if dry_run:
        return {"orphans_found": len(orphans), "orphans_removed": 0, "bytes_freed": 0}

    removed = 0
    for path in orphans:
        try:
            size = path.stat().st_size
            path.unlink()
            bytes_freed += size
            removed += 1
            parent = path.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError as exc:
            logger.warning("Failed to remove orphan %s: %s", path, exc)

    return {"orphans_found": len(orphans), "orphans_removed": removed, "bytes_freed": bytes_freed}


def measure_storage(repo_path: str) -> dict[str, int]:
    """Measure current storage usage for content files and DB."""
    base = Path(repo_path) / ".entirecontext"
    content_dir = base / "content"
    db_path = base / "db" / "local.db"

    content_bytes = 0
    content_count = 0
    if content_dir.exists():
        for f in content_dir.rglob("*.jsonl"):
            try:
                content_bytes += f.stat().st_size
                content_count += 1
            except (FileNotFoundError, OSError):
                continue

    db_bytes = 0
    if db_path.exists():
        db_bytes = db_path.stat().st_size
        for suffix in ("-wal", "-shm"):
            sidecar = db_path.with_name(db_path.name + suffix)
            try:
                db_bytes += sidecar.stat().st_size
            except (FileNotFoundError, OSError):
                continue

    return {
        "content_bytes": content_bytes,
        "content_file_count": content_count,
        "db_bytes": db_bytes,
    }


def _db_total_size(db_path: Path) -> int:
    """Return total size of DB file including WAL/SHM sidecars."""
    total = db_path.stat().st_size if db_path.exists() else 0
    for suffix in ("-wal", "-shm"):
        sidecar = db_path.with_name(db_path.name + suffix)
        try:
            total += sidecar.stat().st_size
        except (FileNotFoundError, OSError):
            continue
    return total


def vacuum_db(repo_path: str) -> dict[str, int]:
    """Run VACUUM on the local DB and return before/after sizes.

    Opens a dedicated connection because compact_repo() borrows (but
    does not own) the caller's connection.  Failures are logged but
    never propagate — VACUUM is a minor hygiene step and must not
    abort a successful compact run.
    """
    db_path = Path(repo_path) / ".entirecontext" / "db" / "local.db"
    if not db_path.exists():
        return {"db_before": 0, "db_after": 0}

    db_before = _db_total_size(db_path)

    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except sqlite3.OperationalError as exc:
        logger.warning("VACUUM skipped: %s", exc)
        return {"db_before": db_before, "db_after": db_before}

    db_after = _db_total_size(db_path)
    return {"db_before": db_before, "db_after": db_after}


def compact_repo(
    conn: sqlite3.Connection,
    repo_path: str,
    *,
    retention_days: int = 30,
    limit: int = 10000,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Orchestrate full compaction: consolidate → orphan cleanup → vacuum.

    Args:
        conn: DB connection.
        repo_path: Absolute path to the git repository root.
        retention_days: Content files older than this many days are consolidated.
        limit: Maximum turns to consolidate in one run.
        dry_run: If True, only report — no changes.

    Returns:
        Report dict with before/after sizes, consolidation stats, orphan stats.
    """
    from datetime import datetime, timedelta, timezone

    from .consolidation import consolidate_old_turns

    if retention_days < 0:
        raise ValueError(f"retention_days must be non-negative, got {retention_days}")
    if limit < 0:
        raise ValueError(f"limit must be non-negative, got {limit}")

    before = measure_storage(repo_path)

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    before_date = cutoff.isoformat()
    consolidation = consolidate_old_turns(
        conn, repo_path, before_date=before_date, limit=limit, dry_run=dry_run
    )

    orphans = remove_orphan_content_files(conn, repo_path, dry_run=dry_run)

    vacuum = {}
    if not dry_run:
        vacuum = vacuum_db(repo_path)

    after = measure_storage(repo_path) if not dry_run else before

    return {
        "before": before,
        "after": after,
        "consolidation": consolidation,
        "orphans": orphans,
        "vacuum": vacuum,
        "retention_days": retention_days,
        "dry_run": dry_run,
    }
