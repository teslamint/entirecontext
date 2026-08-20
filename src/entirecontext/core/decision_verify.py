"""Verify that decision UUIDs referenced in docs exist in the local DB.

Provides the gate logic for the feature-worktree decision preservation
workflow: before a worktree is removed, ``verify-docs`` confirms every
UUID cited in active documentation resolves in the base repo's DB, and
``--promote-from`` copies missing records from a worktree DB.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

_DEFAULT_SCAN_DIRS = ("docs/adr", "docs/specs", "docs/plans")
_DEFAULT_SCAN_FILES = ("ROADMAP.md",)


@dataclass
class DocRef:
    file: str
    line: int
    uuid: str


@dataclass
class VerifyResult:
    found: list[DocRef] = field(default_factory=list)
    missing: list[DocRef] = field(default_factory=list)


@dataclass
class PromoteResult:
    promoted: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    missing_in_source: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def scan_doc_decision_refs(
    repo_path: str | Path,
    dirs: tuple[str, ...] = _DEFAULT_SCAN_DIRS,
    files: tuple[str, ...] = _DEFAULT_SCAN_FILES,
) -> list[DocRef]:
    root = Path(repo_path)
    refs: list[DocRef] = []

    for d in dirs:
        if Path(d).is_absolute():
            raise ValueError(f"Scan directory must be relative to repo root: {d}")
        dir_path = root / d
        if not dir_path.is_dir():
            continue
        for f in sorted(dir_path.rglob("*")):
            if not f.is_file():
                continue
            _scan_file(f, root, refs)

    for fname in files:
        if Path(fname).is_absolute():
            raise ValueError(f"Scan file must be relative to repo root: {fname}")
        fpath = root / fname
        if fpath.is_file():
            _scan_file(fpath, root, refs)

    return refs


def _scan_file(path: Path, root: Path, refs: list[DocRef]) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    rel = str(path.relative_to(root))
    for i, line_text in enumerate(text.splitlines(), start=1):
        for m in _UUID_RE.finditer(line_text):
            refs.append(DocRef(file=rel, line=i, uuid=m.group(0).lower()))


def verify_decisions(conn: sqlite3.Connection, refs: list[DocRef]) -> VerifyResult:
    unique_uuids = {r.uuid for r in refs}
    if not unique_uuids:
        return VerifyResult()

    placeholders = ",".join("?" for _ in unique_uuids)
    rows = conn.execute(
        f"SELECT id FROM decisions WHERE id IN ({placeholders})",  # noqa: S608
        list(unique_uuids),
    ).fetchall()
    existing = {row[0] for row in rows}

    result = VerifyResult()
    for ref in refs:
        if ref.uuid in existing:
            result.found.append(ref)
        else:
            result.missing.append(ref)
    return result


def open_source_db_readonly(db_path: str | Path) -> sqlite3.Connection:
    p = Path(db_path)
    if not p.is_file():
        raise FileNotFoundError(f"Source DB not found: {p}")
    encoded = quote(str(p), safe="/")
    conn = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _get_source_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return row[0] if row and row[0] is not None else 0
    except sqlite3.Error:
        return 0


_PROMOTE_TABLES = (
    "decision_files",
    "decision_commits",
)


def promote_decisions(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    decision_ids: list[str],
    *,
    target_schema_version: int | None = None,
) -> PromoteResult:
    from .context import transaction

    source_version = _get_source_schema_version(source_conn)
    if target_schema_version is not None and source_version != target_schema_version:
        raise ValueError(
            f"Schema version mismatch: source={source_version}, target={target_schema_version}. "
            "Migrate the source DB first."
        )

    result = PromoteResult()

    existing = set()
    if decision_ids:
        placeholders = ",".join("?" for _ in decision_ids)
        rows = target_conn.execute(
            f"SELECT id FROM decisions WHERE id IN ({placeholders})",  # noqa: S608
            decision_ids,
        ).fetchall()
        existing = {row[0] for row in rows}

    to_promote = [did for did in decision_ids if did not in existing]
    result.already_present = [did for did in decision_ids if did in existing]

    if not to_promote:
        return result

    source_rows: dict[str, sqlite3.Row] = {}
    for did in to_promote:
        row = source_conn.execute("SELECT * FROM decisions WHERE id = ?", (did,)).fetchone()
        if row is None:
            result.missing_in_source.append(did)
        else:
            source_rows[did] = row

    if not source_rows:
        return result

    with transaction(target_conn):
        # Two-pass: insert with superseded_by_id = NULL, then update links
        successor_map: dict[str, str | None] = {}
        for did, row in source_rows.items():
            successor_map[did] = row["superseded_by_id"]
            try:
                target_conn.execute(
                    """INSERT OR IGNORE INTO decisions (
                        id, title, rationale, scope, staleness_status,
                        superseded_by_id, rejected_alternatives, supporting_evidence,
                        auto_promotion_reset_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)""",
                    (
                        row["id"],
                        row["title"],
                        row["rationale"],
                        row["scope"],
                        row["staleness_status"],
                        row["rejected_alternatives"],
                        row["supporting_evidence"],
                        row["auto_promotion_reset_at"],
                        row["created_at"],
                        row["updated_at"],
                    ),
                )
                result.promoted.append(did)
            except sqlite3.Error as exc:
                result.errors.append(f"{did}: {exc}")
                continue

            for table in _PROMOTE_TABLES:
                _copy_child_rows(source_conn, target_conn, table, "decision_id", did)

        # Second pass: restore superseded_by_id where the successor exists in target
        for did, successor_id in successor_map.items():
            if successor_id is None or did not in result.promoted:
                continue
            check = target_conn.execute("SELECT 1 FROM decisions WHERE id = ?", (successor_id,)).fetchone()
            if check:
                target_conn.execute(
                    "UPDATE decisions SET superseded_by_id = ? WHERE id = ?",
                    (successor_id, did),
                )

    return result


def _copy_child_rows(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    table: str,
    fk_column: str,
    fk_value: str,
) -> None:
    rows = source_conn.execute(
        f"SELECT * FROM {table} WHERE {fk_column} = ?",  # noqa: S608
        (fk_value,),
    ).fetchall()
    if not rows:
        return
    columns = rows[0].keys()
    cols_str = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    for row in rows:
        target_conn.execute(
            f"INSERT OR IGNORE INTO {table} ({cols_str}) VALUES ({placeholders})",  # noqa: S608
            tuple(row[c] for c in columns),
        )
