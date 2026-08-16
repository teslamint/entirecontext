"""Persist committed Git rename lineage and propagate decision file links."""

from __future__ import annotations

import re
import sqlite3
import subprocess
import time
from dataclasses import dataclass

from .context import transaction


_COMMIT_MARKER = "\x1e"
_COMMIT_SHA_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_RENAME_STATUS_RE = re.compile(r"R\d{1,3}")
_DEFAULT_GIT_TIMEOUT_SECONDS = 2.0


class RenameLogError(ValueError):
    """Raised when Git rename output cannot be persisted without ambiguity."""


class RenameSyncError(RuntimeError):
    """Raised when committed rename history cannot be read from Git."""


@dataclass(frozen=True)
class RenameRecord:
    """One Git-proven committed path rename."""

    old_path: str
    new_path: str
    commit_sha: str


@dataclass(frozen=True)
class RenameSyncResult:
    """Observable result of one repository rename synchronization."""

    scanned_from: str | None
    head_commit: str
    full_scan: bool
    renames_recorded: int
    links_added: int


def _decode_git_output(raw: bytes) -> str:
    return raw.decode("utf-8", errors="surrogateescape")


def _require_sqlite_text(value: str, *, label: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise RenameLogError(f"{label} is not representable as SQLite text") from exc


def _parse_rename_log(raw: bytes) -> list[RenameRecord]:
    """Parse NUL-delimited ``git log --name-status -M`` rename records.

    Commit boundaries use an ASCII record-separator marker emitted by
    ``--format=%x1e%H%x00``. Path tokens are consumed positionally after an
    ``R<score>`` status, so leading newlines and status-shaped filenames remain
    unambiguous.
    """
    if not raw:
        return []
    if not raw.endswith(b"\0"):
        raise RenameLogError("rename log is not NUL-terminated")

    parts = _decode_git_output(raw).split("\0")
    records: list[RenameRecord] = []
    current_commit: str | None = None
    index = 0

    while index < len(parts):
        token = parts[index]
        control_token = token.lstrip("\n")

        if not control_token:
            index += 1
            continue

        if control_token.startswith(_COMMIT_MARKER):
            commit_sha = control_token[len(_COMMIT_MARKER) :]
            if _COMMIT_SHA_RE.fullmatch(commit_sha) is None:
                raise RenameLogError("rename log contains an invalid commit marker")
            current_commit = commit_sha
            index += 1
            continue

        if _RENAME_STATUS_RE.fullmatch(control_token) is not None:
            if current_commit is None:
                raise RenameLogError("rename record appears before its commit marker")
            if index + 2 >= len(parts) or not parts[index + 1] or not parts[index + 2]:
                raise RenameLogError("rename record is missing an old or new path")
            old_path = parts[index + 1]
            new_path = parts[index + 2]
            _require_sqlite_text(old_path, label="old path")
            _require_sqlite_text(new_path, label="new path")
            if old_path == new_path:
                raise RenameLogError("rename record has identical old and new paths")
            records.append(
                RenameRecord(
                    old_path=old_path,
                    new_path=new_path,
                    commit_sha=current_commit,
                )
            )
            index += 3
            continue

        raise RenameLogError(f"unexpected token in rename log: {control_token!r}")

    return records


def _run_git(repo_path: str, args: list[str], *, timeout_seconds: float) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        raise RenameSyncError(f"git {' '.join(args)} failed: {exc}") from exc

    if result.returncode != 0:
        stderr = _decode_git_output(result.stderr).strip()
        detail = stderr or f"exit status {result.returncode}"
        raise RenameSyncError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def _read_head(repo_path: str, *, timeout_seconds: float) -> str:
    raw = _run_git(
        repo_path,
        ["rev-parse", "--verify", "HEAD"],
        timeout_seconds=timeout_seconds,
    )
    head = raw.decode("ascii", errors="strict").strip()
    if _COMMIT_SHA_RE.fullmatch(head) is None:
        raise RenameSyncError("git rev-parse returned an invalid HEAD commit")
    return head


def _is_ancestor(repo_path: str, ancestor: str, head: str, *, timeout_seconds: float) -> bool:
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, head],
            cwd=repo_path,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        raise RenameSyncError(f"git merge-base --is-ancestor failed: {exc}") from exc
    return result.returncode == 0


def _collect_rename_records(
    repo_path: str,
    revision: str,
    *,
    timeout_seconds: float,
) -> list[RenameRecord]:
    raw = _run_git(
        repo_path,
        [
            "log",
            "--topo-order",
            "--diff-merges=separate",
            "--reverse",
            "--format=%x1e%H%x00",
            "--name-status",
            "-M",
            "-z",
            "--diff-filter=R",
            revision,
        ],
        timeout_seconds=timeout_seconds,
    )
    return _parse_rename_log(raw)


def _last_scanned_commit(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT last_scanned_commit FROM decision_file_lineage_state WHERE id = 1").fetchone()
    if row is None:
        return None
    value = row["last_scanned_commit"]
    return str(value) if value else None


def _insert_lineage_records(conn: sqlite3.Connection, records: list[RenameRecord]) -> int:
    inserted = 0
    for record in records:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO decision_file_lineage
            (old_path, new_path, commit_sha) VALUES (?, ?, ?)""",
            (record.old_path, record.new_path, record.commit_sha),
        )
        inserted += max(cursor.rowcount, 0)
    return inserted


def _propagate_destination_links(conn: sqlite3.Connection) -> int:
    conn.execute(
        """WITH RECURSIVE propagated(decision_id, file_path) AS (
            SELECT df.decision_id, lineage.new_path
            FROM decision_files AS df
            JOIN decision_file_lineage AS lineage
              ON REPLACE(
                  CASE WHEN lineage.old_path LIKE './%'
                       THEN SUBSTR(lineage.old_path, 3)
                       ELSE lineage.old_path END,
                  '\\',
                  '/'
              ) = REPLACE(
                  CASE WHEN df.file_path LIKE './%' THEN SUBSTR(df.file_path, 3)
                       ELSE df.file_path END,
                  '\\',
                  '/'
              )
            UNION
            SELECT propagated.decision_id, lineage.new_path
            FROM propagated
            JOIN decision_file_lineage AS lineage
              ON REPLACE(
                  CASE WHEN lineage.old_path LIKE './%'
                       THEN SUBSTR(lineage.old_path, 3)
                       ELSE lineage.old_path END,
                  '\\',
                  '/'
              ) = REPLACE(
                  CASE WHEN propagated.file_path LIKE './%'
                       THEN SUBSTR(propagated.file_path, 3)
                       ELSE propagated.file_path END,
                  '\\',
                  '/'
              )
        )
        INSERT OR IGNORE INTO decision_files (decision_id, file_path)
        SELECT decision_id, file_path FROM propagated"""
    )
    row = conn.execute("SELECT changes() AS count").fetchone()
    return int(row["count"] if row else 0)


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RenameSyncError("Git rename synchronization exceeded its time budget")
    return remaining


def sync_decision_file_lineage(
    conn: sqlite3.Connection,
    repo_path: str,
    *,
    timeout_seconds: float = _DEFAULT_GIT_TIMEOUT_SECONDS,
) -> RenameSyncResult:
    """Synchronize committed rename history into the decision-file read model.

    Git reads happen before the transaction. Lineage insertion, transitive link
    propagation, and watermark advancement then commit atomically. Any raised
    error leaves the prior watermark and decision links unchanged.
    """
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    deadline = time.monotonic() + timeout_seconds
    head_commit = _read_head(
        repo_path,
        timeout_seconds=_remaining_timeout(deadline),
    )
    last_scanned = _last_scanned_commit(conn)

    full_scan = last_scanned is None
    scanned_from: str | None = None
    records: list[RenameRecord] = []

    if last_scanned == head_commit:
        full_scan = False
    else:
        if last_scanned is not None and _is_ancestor(
            repo_path,
            last_scanned,
            head_commit,
            timeout_seconds=_remaining_timeout(deadline),
        ):
            scanned_from = last_scanned
            revision = f"{last_scanned}..{head_commit}"
            full_scan = False
        else:
            revision = head_commit
            full_scan = True
        records = _collect_rename_records(
            repo_path,
            revision,
            timeout_seconds=_remaining_timeout(deadline),
        )

    with transaction(conn):
        renames_recorded = _insert_lineage_records(conn, records)
        links_added = _propagate_destination_links(conn)
        conn.execute(
            """INSERT INTO decision_file_lineage_state (id, last_scanned_commit)
            VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET last_scanned_commit = excluded.last_scanned_commit""",
            (head_commit,),
        )

    return RenameSyncResult(
        scanned_from=scanned_from,
        head_commit=head_commit,
        full_scan=full_scan,
        renames_recorded=renames_recorded,
        links_added=links_added,
    )
