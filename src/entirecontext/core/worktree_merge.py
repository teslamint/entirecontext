"""Merge a legacy per-worktree database into the canonical project database.

Before schema v21 every linked Git worktree kept its own
``<worktree>/.entirecontext/db/local.db``. This module copies such a database
into the logical project's database at the canonical project root.

The source database is only ever opened read-only; it is never modified,
moved or deleted. A dry run executes the same row merge inside a transaction
that is rolled back, so the report matches what ``apply=True`` would write.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .decision_verify import _get_source_schema_version, open_source_db_readonly
from .project import ensure_project, legacy_worktree_db_path
from .repo_roots import RepoRoots, resolve_repo_roots
from ..db import db_path_for, get_db
from ..db.migration import check_and_migrate, get_current_version
from ..db.schema import FTS_TABLES, SCHEMA_VERSION

MIN_SOURCE_VERSION = 20

# Parents before children so immediate foreign-key checks pass.
MERGE_TABLES = (
    "agents",
    "sessions",
    "turns",
    "turn_content",
    "checkpoints",
    "assessments",
    "assessment_relationships",
    "events",
    "event_sessions",
    "event_checkpoints",
    "attributions",
    "ast_symbols",
    "embeddings",
    "retrieval_events",
    "retrieval_selections",
    "ranking_snapshots",
    "context_applications",
    "operation_events",
    "decisions",
    "decision_commits",
    "decision_checkpoints",
    "decision_files",
    "decision_file_lineage_suppressions",
    "decision_assessments",
    "decision_outcomes",
    "decision_candidates",
    "decision_file_lineage",
    "archaeology_processed",
)

# Per-database singletons and bookkeeping; the canonical DB keeps its own.
SKIPPED_TABLES = (
    "projects",
    "schema_version",
    "sync_metadata",
    "decision_file_lineage_state",
    "decision_file_lineage_worktree_state",
)

# Self-referencing columns are inserted as NULL and restored in a second pass.
_SELF_REFS = {
    "agents": "parent_agent_id",
    "checkpoints": "parent_checkpoint_id",
    "decisions": "superseded_by_id",
}

# Columns the merge rewrites; they are not part of the divergence comparison.
_REWRITTEN = {
    "sessions": {"project_id", "workspace_root", "worktree_git_dir", "git_branch"},
    "turn_content": {"content_path"},
}


class WorktreeMergeError(RuntimeError):
    """The merge cannot run; nothing was written."""


@dataclass
class MergeReport:
    source_db: str
    project_root: str
    workspace_root: str
    source_version: int
    applied: bool = False
    inserted: dict[str, int] = field(default_factory=dict)
    identical: dict[str, int] = field(default_factory=dict)
    divergent: list[dict[str, Any]] = field(default_factory=list)
    collisions: list[dict[str, Any]] = field(default_factory=list)
    skipped_tables: list[str] = field(default_factory=list)
    content: dict[str, int] = field(default_factory=dict)
    content_issues: list[dict[str, Any]] = field(default_factory=list)
    source_backup: str | None = None
    target_backup: str | None = None
    repo_index_removed: int = 0

    @property
    def inserted_total(self) -> int:
        return sum(self.inserted.values())

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["inserted_total"] = self.inserted_total
        return data


@dataclass
class _ContentItem:
    turn_id: str
    content_path: str
    src_path: Path | None
    dest: Path | None
    content_hash: str | None
    status: str


def resolve_merge_source(path: str | Path) -> tuple[RepoRoots, Path]:
    """Return the linked worktree roots and legacy DB path for ``path``.

    ``path`` may be the linked worktree (or a directory inside it) or the
    legacy ``local.db`` file itself.
    """
    p = Path(path).expanduser().resolve()
    if p.is_file():
        if p.name != "local.db" or p.parent.name != "db" or p.parent.parent.name != ".entirecontext":
            raise WorktreeMergeError(f"{p} is not a per-worktree database (.entirecontext/db/local.db)")
        p = p.parent.parent.parent
    if not p.is_dir():
        raise WorktreeMergeError(f"Path not found: {p}")
    roots = resolve_repo_roots(p)
    if roots is None:
        raise WorktreeMergeError(f"{p} is not inside a Git repository")
    if not roots.is_linked_worktree:
        raise WorktreeMergeError(f"{roots.workspace_root} is not a linked Git worktree")
    db_path = legacy_worktree_db_path(roots)
    if db_path is None:
        raise WorktreeMergeError(f"No legacy per-worktree database at {db_path_for(roots.workspace_root)}")
    return roots, db_path


def merge_worktree(path: str | Path, *, apply: bool = False, now: datetime | None = None) -> MergeReport:
    """Merge the legacy DB of the linked worktree at ``path`` into the canonical DB.

    Without ``apply`` this is a dry run: rows are merged inside a transaction
    that is rolled back and no content file is copied.
    """
    roots, source_path = resolve_merge_source(path)
    target_path = db_path_for(roots.project_root)
    if not target_path.is_file():
        raise WorktreeMergeError(
            f"Canonical database not found at {target_path}; run 'ec init' in {roots.project_root} first"
        )

    source = open_source_db_readonly(source_path)
    try:
        version = _get_source_schema_version(source)
        if not MIN_SOURCE_VERSION <= version <= SCHEMA_VERSION:
            raise WorktreeMergeError(
                f"Unsupported source schema version {version}; expected {MIN_SOURCE_VERSION}..{SCHEMA_VERSION}"
            )
        report = MergeReport(
            source_db=str(source_path),
            project_root=roots.project_root,
            workspace_root=roots.workspace_root,
            source_version=version,
        )
        target = get_db(roots.project_root)
        try:
            if apply:
                check_and_migrate(target)
            elif get_current_version(target) != SCHEMA_VERSION:
                raise WorktreeMergeError(
                    f"Canonical database is at schema {get_current_version(target)}, not {SCHEMA_VERSION}; "
                    "run any 'ec' command in the main worktree to migrate it first"
                )
            items = _plan_content(source, roots)
            if apply:
                stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S%fZ")
                backup_dir = Path(roots.project_root) / ".entirecontext" / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                name = Path(roots.workspace_root).name
                report.source_backup = str(_backup(source, backup_dir / f"worktree-merge-{stamp}-{name}-source.db"))
                report.target_backup = str(_backup(target, backup_dir / f"worktree-merge-{stamp}-canonical.db"))
                _copy_content(items)
            _record_content(report, items)
            _merge_rows(source, target, roots, report, items, apply=apply)
        finally:
            target.close()
    finally:
        source.close()

    if apply:
        report.applied = True
        report.repo_index_removed = _remove_stale_repo_index(roots, source_path)
    return report


def _backup(conn: sqlite3.Connection, dest: Path) -> Path:
    out = sqlite3.connect(str(dest))
    try:
        conn.backup(out)
    finally:
        out.close()
    return dest


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_content_path(content_path: str, ec_dir: Path) -> str | None:
    """Return ``content_path`` relative to ``ec_dir``, or None when it points outside it."""
    base = ec_dir.resolve()
    p = Path(content_path)
    try:
        return (p if p.is_absolute() else base / p).resolve().relative_to(base).as_posix()
    except ValueError:
        return None


def _plan_content(source: sqlite3.Connection, roots: RepoRoots) -> list[_ContentItem]:
    """Classify every source content file without touching the filesystem."""
    source_ec = Path(roots.workspace_root) / ".entirecontext"
    target_ec = Path(roots.project_root) / ".entirecontext"
    items = []
    for row in source.execute("SELECT turn_id, content_path, content_hash FROM turn_content ORDER BY turn_id"):
        rel = _relative_content_path(row["content_path"], source_ec)
        if rel is None:
            status = "external" if Path(row["content_path"]).is_absolute() else "unsafe_path"
            items.append(_ContentItem(row["turn_id"], row["content_path"], None, None, row["content_hash"], status))
            continue
        src = source_ec / rel
        dest = target_ec / rel
        expected = row["content_hash"]
        if not src.is_file():
            status = "missing"
        elif expected and _md5(src) != expected:
            status = "hash_mismatch"
        elif dest.exists():
            status = "already_present" if dest.is_file() and _md5(dest) == _md5(src) else "conflict"
        else:
            status = "copy" if expected else "copy_unverified"
        items.append(_ContentItem(row["turn_id"], rel, src, dest, expected, status))
    return items


UNLINKED_CONTENT = frozenset({"missing", "hash_mismatch", "conflict", "unsafe_path", "external"})


def _copy_content(items: list[_ContentItem]) -> None:
    for item in items:
        if item.status not in ("copy", "copy_unverified"):
            continue
        assert item.src_path is not None and item.dest is not None
        item.dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = item.dest.with_name(item.dest.name + ".merge-tmp")
        shutil.copy2(item.src_path, tmp)
        if _md5(tmp) != _md5(item.src_path):
            tmp.unlink(missing_ok=True)
            raise WorktreeMergeError(f"Copied content does not match its source: {item.src_path}")
        os.replace(tmp, item.dest)


def _record_content(report: MergeReport, items: list[_ContentItem]) -> None:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
        if item.status not in ("copy", "already_present"):
            report.content_issues.append(
                {"turn_id": item.turn_id, "content_path": item.content_path, "status": item.status}
            )
    report.content = counts


def _columns(conn: sqlite3.Connection, table: str) -> list[tuple[str, int]]:
    return [(r[1], r[5]) for r in conn.execute(f"PRAGMA table_info({table})")]


def _source_tables(source: sqlite3.Connection) -> set[str]:
    rows = source.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'fts_%'"
    )
    return {r[0] for r in rows}


def _merge_rows(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    roots: RepoRoots,
    report: MergeReport,
    items: list[_ContentItem],
    *,
    apply: bool,
) -> None:
    source_tables = _source_tables(source)
    report.skipped_tables = sorted(source_tables - set(MERGE_TABLES))
    content = {item.turn_id: item for item in items}

    target.execute("BEGIN IMMEDIATE")
    try:
        project_id = ensure_project(target, roots)
        overrides = {
            "sessions": {
                "project_id": project_id,
                "workspace_root": roots.workspace_root,
                "worktree_git_dir": roots.worktree_git_dir,
            }
        }
        for table in MERGE_TABLES:
            if table not in source_tables:
                continue
            _merge_table(source, target, table, report, overrides.get(table, {}), roots, content, apply)
        _check_fts(target)
    except BaseException:
        if target.in_transaction:
            target.execute("ROLLBACK")
        raise
    target.execute("COMMIT" if apply else "ROLLBACK")


def _merge_table(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
    report: MergeReport,
    overrides: dict[str, Any],
    roots: RepoRoots,
    content: dict[str, _ContentItem],
    apply: bool,
) -> None:
    target_cols = {name for name, _ in _columns(target, table)}
    source_info = _columns(source, table)
    cols = [name for name, _ in source_info if name in target_cols]
    pk = [name for name, pos in sorted(source_info, key=lambda c: c[1]) if pos]
    insert_cols = cols + [c for c in overrides if c not in cols]
    if table == "sessions" and "git_branch" not in insert_cols:
        insert_cols.append("git_branch")
    compare = [c for c in cols if c not in _REWRITTEN.get(table, set())]
    self_ref = _SELF_REFS.get(table)
    pk_where = " AND ".join(f"{c} = ?" for c in pk)
    insert_sql = f"INSERT INTO {table} ({', '.join(insert_cols)}) VALUES ({', '.join('?' for _ in insert_cols)})"
    deferred: list[tuple[Any, tuple[Any, ...]]] = []

    inserted = identical = 0
    for row in source.execute(f"SELECT {', '.join(cols)} FROM {table}"):  # noqa: S608
        values = dict(zip(cols, row))
        key = tuple(values[c] for c in pk)
        existing = target.execute(f"SELECT {', '.join(compare)} FROM {table} WHERE {pk_where}", key).fetchone()  # noqa: S608
        if existing is not None:
            diff = [c for c in compare if existing[c] != values[c]]
            if diff:
                report.divergent.append({"table": table, "key": _key(pk, key), "columns": diff})
            else:
                identical += 1
            continue

        values.update(overrides)
        if table == "sessions" and values.get("git_branch") is None:
            values["git_branch"] = roots.branch
        item = content.get(values["turn_id"]) if table == "turn_content" else None
        if item is not None:
            if item.status in UNLINKED_CONTENT:
                continue
            values["content_path"] = item.content_path
        if self_ref and values.get(self_ref) is not None:
            deferred.append((values[self_ref], key))
            values[self_ref] = None
        try:
            target.execute(insert_sql, [values[c] for c in insert_cols])
        except sqlite3.IntegrityError as exc:
            report.collisions.append({"table": table, "key": _key(pk, key), "error": str(exc)})
            if item is not None and item.status in ("copy", "copy_unverified"):
                report.content_issues.append(
                    {
                        "turn_id": item.turn_id,
                        "content_path": item.content_path,
                        "status": "orphan_copy" if apply else "would_orphan",
                    }
                )
            continue
        inserted += 1

    for ref, key in deferred:
        if target.execute(f"SELECT 1 FROM {table} WHERE id = ?", (ref,)).fetchone():  # noqa: S608
            target.execute(f"UPDATE {table} SET {self_ref} = ? WHERE {pk_where}", (ref, *key))  # noqa: S608
        else:
            report.collisions.append(
                {"table": table, "key": _key(pk, key), "error": f"{self_ref} {ref} was not merged; left NULL"}
            )
    if inserted:
        report.inserted[table] = inserted
    if identical:
        report.identical[table] = identical


def _key(pk: list[str], key: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip(pk, key))


def _check_fts(conn: sqlite3.Connection) -> None:
    for name in FTS_TABLES:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()
        if exists:
            conn.execute(f"INSERT INTO {name}({name}) VALUES('integrity-check')")  # noqa: S608


def _remove_stale_repo_index(roots: RepoRoots, source_path: Path) -> int:
    """Drop the global index row that points at the merged per-worktree DB."""
    from ..db.connection import _GLOBAL_DB_PATH, get_global_db

    if not Path(_GLOBAL_DB_PATH).is_file():
        return 0
    conn = get_global_db()
    try:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'repo_index'").fetchone()
        if not exists:
            return 0
        cur = conn.execute(
            "DELETE FROM repo_index WHERE (repo_path = ? OR db_path = ?) AND repo_path != ?",
            (roots.workspace_root, str(source_path), roots.project_root),
        )
        return cur.rowcount
    finally:
        conn.close()
