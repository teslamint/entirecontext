"""Import data from Aline database into EntireContext."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4


@dataclass
class ImportResult:
    sessions: int = 0
    turns: int = 0
    turn_content: int = 0
    checkpoints: int = 0
    events: int = 0
    event_links: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def import_from_aline(
    ec_conn: sqlite3.Connection,
    aline_db_path: str,
    project_id: str,
    repo_path: str,
    workspace_filter: str | None = None,
    dry_run: bool = False,
    skip_content: bool = False,
) -> ImportResult:
    result = ImportResult()

    aline_path = Path(aline_db_path)
    if not aline_path.exists():
        result.errors.append(f"Aline DB not found: {aline_db_path}")
        return result

    aline_conn = sqlite3.connect(f"file:{aline_db_path}?mode=ro", uri=True)
    aline_conn.row_factory = sqlite3.Row

    try:
        _import_sessions(aline_conn, ec_conn, project_id, workspace_filter, dry_run, result)
        _import_turns(aline_conn, ec_conn, dry_run, result)
        if not skip_content:
            _import_turn_content(aline_conn, ec_conn, repo_path, dry_run, result)
        _generate_checkpoints(ec_conn, dry_run, result)
        _import_events(aline_conn, ec_conn, dry_run, result)
    except Exception as e:
        result.errors.append(str(e))
    finally:
        aline_conn.close()

    return result


def _get_imported_session_ids(ec_conn: sqlite3.Connection) -> set[str]:
    rows = ec_conn.execute("SELECT id FROM sessions").fetchall()
    return {r["id"] for r in rows}


def _import_sessions(
    aline_conn: sqlite3.Connection,
    ec_conn: sqlite3.Connection,
    project_id: str,
    workspace_filter: str | None,
    dry_run: bool,
    result: ImportResult,
) -> None:
    query = "SELECT * FROM sessions"
    params: list[str] = []
    if workspace_filter:
        query += " WHERE workspace_path LIKE ?"
        params.append(f"%{workspace_filter}%")

    rows = aline_conn.execute(query, params).fetchall()

    for row in rows:
        if dry_run:
            result.sessions += 1
            continue

        try:
            cursor = ec_conn.execute(
                """INSERT OR IGNORE INTO sessions
                (id, project_id, session_type, workspace_path, started_at, last_activity_at,
                 session_title, session_summary, total_turns, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["id"],
                    project_id,
                    row["session_type"] or "claude",
                    row["workspace_path"],
                    row["started_at"] or row["last_activity_at"] or "1970-01-01T00:00:00",
                    row["last_activity_at"] or row["started_at"] or "1970-01-01T00:00:00",
                    row["session_title"],
                    row["session_summary"],
                    row["total_turns"] or 0,
                    row["started_at"] or "1970-01-01T00:00:00",
                    row["last_activity_at"] or "1970-01-01T00:00:00",
                ),
            )
            if cursor.rowcount > 0:
                result.sessions += 1
            else:
                result.skipped += 1
        except Exception as e:
            result.errors.append(f"Session {row['id']}: {e}")
            result.skipped += 1

    if not dry_run:
        ec_conn.commit()


def _import_turns(
    aline_conn: sqlite3.Connection,
    ec_conn: sqlite3.Connection,
    dry_run: bool,
    result: ImportResult,
) -> None:
    ec_session_ids = _get_imported_session_ids(ec_conn)
    if not ec_session_ids:
        return

    placeholders = ",".join("?" for _ in ec_session_ids)
    rows = aline_conn.execute(
        f"SELECT * FROM turns WHERE session_id IN ({placeholders})",
        list(ec_session_ids),
    ).fetchall()

    for row in rows:
        if dry_run:
            result.turns += 1
            continue

        content_hash = row["content_hash"] or hashlib.md5((row["user_message"] or "").encode()).hexdigest()

        try:
            cursor = ec_conn.execute(
                """INSERT OR IGNORE INTO turns
                (id, session_id, turn_number, user_message, assistant_summary,
                 model_name, git_commit_hash, content_hash, timestamp, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["id"],
                    row["session_id"],
                    row["turn_number"],
                    row["user_message"],
                    row["assistant_summary"],
                    row["model_name"],
                    row["git_commit_hash"],
                    content_hash,
                    row["started_at"] if "started_at" in row.keys() else "1970-01-01T00:00:00",
                    row["started_at"] if "started_at" in row.keys() else "1970-01-01T00:00:00",
                ),
            )
            if cursor.rowcount > 0:
                result.turns += 1
            else:
                result.skipped += 1
        except Exception as e:
            result.errors.append(f"Turn {row['id']}: {e}")
            result.skipped += 1

    if not dry_run:
        ec_conn.commit()


def _import_turn_content(
    aline_conn: sqlite3.Connection,
    ec_conn: sqlite3.Connection,
    repo_path: str,
    dry_run: bool,
    result: ImportResult,
) -> None:
    ec_turn_ids = {r["id"] for r in ec_conn.execute("SELECT id FROM turns").fetchall()}
    if not ec_turn_ids:
        return

    existing = {r["turn_id"] for r in ec_conn.execute("SELECT turn_id FROM turn_content").fetchall()}

    placeholders = ",".join("?" for _ in ec_turn_ids)

    try:
        rows = aline_conn.execute(
            f"SELECT * FROM turn_content WHERE turn_id IN ({placeholders})",
            list(ec_turn_ids),
        ).fetchall()
    except sqlite3.OperationalError:
        return

    content_dir = Path(repo_path) / ".entirecontext" / "content"

    for row in rows:
        if row["turn_id"] in existing:
            result.skipped += 1
            continue

        if dry_run:
            result.turn_content += 1
            continue

        content = row["content"] or ""
        content_hash = hashlib.md5(content.encode()).hexdigest()
        content_path = str(content_dir / f"{row['turn_id']}.jsonl")

        content_dir.mkdir(parents=True, exist_ok=True)
        Path(content_path).write_text(content, encoding="utf-8")

        try:
            cursor = ec_conn.execute(
                "INSERT OR IGNORE INTO turn_content (turn_id, content_path, content_size, content_hash) VALUES (?, ?, ?, ?)",
                (row["turn_id"], content_path, len(content.encode()), content_hash),
            )
            if cursor.rowcount > 0:
                result.turn_content += 1
            else:
                result.skipped += 1
        except Exception as e:
            result.errors.append(f"Content {row['turn_id']}: {e}")
            result.skipped += 1

    if not dry_run:
        ec_conn.commit()


def _generate_checkpoints(
    ec_conn: sqlite3.Connection,
    dry_run: bool,
    result: ImportResult,
) -> None:
    rows = ec_conn.execute(
        """SELECT t.id, t.session_id, t.git_commit_hash, t.timestamp
        FROM turns t
        WHERE t.git_commit_hash IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM checkpoints c
            WHERE c.git_commit_hash = t.git_commit_hash AND c.session_id = t.session_id
        )"""
    ).fetchall()

    for row in rows:
        if dry_run:
            result.checkpoints += 1
            continue

        try:
            ec_conn.execute(
                "INSERT OR IGNORE INTO checkpoints (id, session_id, git_commit_hash, created_at) VALUES (?, ?, ?, ?)",
                (str(uuid4()), row["session_id"], row["git_commit_hash"], row["timestamp"]),
            )
            result.checkpoints += 1
        except Exception as e:
            result.errors.append(f"Checkpoint for turn {row['id']}: {e}")

    if not dry_run:
        ec_conn.commit()


def _import_events(
    aline_conn: sqlite3.Connection,
    ec_conn: sqlite3.Connection,
    dry_run: bool,
    result: ImportResult,
) -> None:
    try:
        event_rows = aline_conn.execute("SELECT * FROM events").fetchall()
    except sqlite3.OperationalError:
        return

    for row in event_rows:
        if dry_run:
            result.events += 1
            continue

        try:
            cursor = ec_conn.execute(
                """INSERT OR IGNORE INTO events
                (id, title, description, event_type, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["id"],
                    row["title"],
                    row["description"],
                    row["event_type"] or "task",
                    row["status"] or "active",
                    row["created_at"] if "created_at" in row.keys() else "1970-01-01T00:00:00",
                    row["created_at"] if "created_at" in row.keys() else "1970-01-01T00:00:00",
                ),
            )
            if cursor.rowcount > 0:
                result.events += 1
            else:
                result.skipped += 1
        except Exception as e:
            result.errors.append(f"Event {row['id']}: {e}")
            result.skipped += 1

    if not dry_run:
        ec_conn.commit()

    try:
        link_rows = aline_conn.execute("SELECT * FROM event_sessions").fetchall()
    except sqlite3.OperationalError:
        return

    ec_session_ids = _get_imported_session_ids(ec_conn)
    ec_event_ids = {r["id"] for r in ec_conn.execute("SELECT id FROM events").fetchall()}

    for row in link_rows:
        if row["event_id"] not in ec_event_ids or row["session_id"] not in ec_session_ids:
            continue

        if dry_run:
            result.event_links += 1
            continue

        try:
            cursor = ec_conn.execute(
                "INSERT OR IGNORE INTO event_sessions (event_id, session_id) VALUES (?, ?)",
                (row["event_id"], row["session_id"]),
            )
            if cursor.rowcount > 0:
                result.event_links += 1
        except Exception as e:
            result.errors.append(f"Event link {row['event_id']}-{row['session_id']}: {e}")

    if not dry_run:
        ec_conn.commit()
