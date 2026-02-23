"""Memory consolidation/decay — compress old turn content files while preserving metadata."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_content_path(repo_path: str, content_path: str) -> Path:
    """Resolve *content_path* relative to the repo's .entirecontext directory.

    Raises ValueError if the resolved path escapes the base directory (path
    traversal prevention).
    """
    base = (Path(repo_path) / ".entirecontext").resolve()
    resolved = (base / content_path).resolve()
    if not str(resolved).startswith(str(base) + "/") and resolved != base:
        raise ValueError(f"content_path escapes base directory: {content_path!r}")
    return resolved


def find_turns_for_consolidation(
    conn,
    *,
    before_date: str,
    session_id: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return turns that have content files and are eligible for consolidation.

    A turn is eligible when:
    - It has an entry in ``turn_content`` (i.e. a content file was saved)
    - Its ``timestamp`` is before ``before_date``
    - It has not already been consolidated (``consolidated_at IS NULL``)

    Args:
        conn: DB connection.
        before_date: ISO date/datetime string; only turns older than this qualify.
        session_id: If given, restrict to a single session.
        limit: Maximum candidates to return.

    Returns:
        List of turn dicts with ``id``, ``session_id``, ``turn_number``, ``timestamp``,
        and ``content_path`` from the join with ``turn_content``.
    """
    query = """
        SELECT t.id, t.session_id, t.turn_number, t.timestamp, tc.content_path
        FROM turns t
        JOIN turn_content tc ON tc.turn_id = t.id
        WHERE t.consolidated_at IS NULL
          AND t.timestamp < ?
    """
    params: list[Any] = [before_date]

    if session_id is not None:
        query += " AND t.session_id = ?"
        params.append(session_id)

    query += " ORDER BY t.timestamp ASC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def consolidate_turn_content(
    conn,
    repo_path: str,
    turn_id: str,
    *,
    dry_run: bool = True,
) -> bool:
    """Consolidate a single turn: delete its content file and mark it in the DB.

    The turn's metadata (``user_message``, ``assistant_summary``, ``files_touched``,
    etc.) is preserved intact. Only the external JSONL content file is removed and
    the ``turn_content`` row is deleted.

    The DB is updated and committed *before* the file is deleted so that the
    worst-case failure (process killed after commit but before unlink) leaves an
    orphaned file that can be cleaned up, rather than a missing file with a stale
    DB reference.

    Args:
        conn: DB connection.
        repo_path: Absolute path to the git repository root.
        turn_id: Full turn UUID.
        dry_run: If True, only simulate — no files or DB rows are changed.

    Returns:
        True if consolidation was performed, False on dry_run.
    """
    row = conn.execute("SELECT content_path FROM turn_content WHERE turn_id = ?", (turn_id,)).fetchone()

    if dry_run:
        return False

    if row is None:
        # Nothing to consolidate for this turn; still mark as consolidated.
        conn.execute("UPDATE turns SET consolidated_at = ? WHERE id = ?", (_iso_now(), turn_id))
        conn.commit()
        return True

    content_path = row["content_path"]

    # Validate the path before any operation.
    try:
        content_file = _safe_content_path(repo_path, content_path)
    except ValueError:
        logger.warning("Skipping consolidation for turn %s: unsafe content_path %r", turn_id, content_path)
        return False

    # Update DB first (commit), then delete the file.
    # This ordering ensures DB consistency even if the process is interrupted
    # after commit but before unlink — the orphaned file can be reclaimed later.
    conn.execute("DELETE FROM turn_content WHERE turn_id = ?", (turn_id,))
    conn.execute("UPDATE turns SET consolidated_at = ? WHERE id = ?", (_iso_now(), turn_id))
    conn.commit()

    if content_file.exists():
        content_file.unlink()

    return True


def consolidate_old_turns(
    conn,
    repo_path: str,
    *,
    before_date: str = "2099-12-31",
    session_id: str | None = None,
    limit: int = 500,
    dry_run: bool = True,
) -> dict[str, int]:
    """Consolidate multiple old turns in batch.

    Args:
        conn: DB connection.
        repo_path: Absolute path to the git repository root.
        before_date: ISO date/datetime string; only turns older than this qualify.
        session_id: If given, restrict to a single session.
        limit: Maximum candidates to process.
        dry_run: If True, count candidates without making changes.

    Returns:
        Dict with keys:
        - ``candidates``: number of eligible turns found
        - ``consolidated``: number of turns actually consolidated (0 on dry_run)
    """
    candidates = find_turns_for_consolidation(
        conn,
        before_date=before_date,
        session_id=session_id,
        limit=limit,
    )

    if dry_run:
        return {"candidates": len(candidates), "consolidated": 0}

    consolidated_count = 0
    for turn in candidates:
        try:
            if consolidate_turn_content(conn, repo_path, turn["id"], dry_run=False):
                consolidated_count += 1
        except OSError as exc:
            logger.warning("Failed to consolidate turn %s: %s", turn["id"], exc)

    return {"candidates": len(candidates), "consolidated": consolidated_count}
