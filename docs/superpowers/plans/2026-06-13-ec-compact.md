# `ec compact` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ec compact` command that consolidates old content files, removes orphaned files, VACUUMs the DB, and reports space savings — cron-friendly for periodic use.

**Architecture:** New `core/compact.py` orchestrates three phases: (1) content consolidation via existing `consolidate_old_turns`, (2) orphan file cleanup, (3) SQLite VACUUM. Config-driven retention via `capture.content_retention_days`. New `cli/compact_cmds.py` for the CLI surface.

**Tech Stack:** Python 3.12+, SQLite, Typer CLI, existing consolidation module

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/entirecontext/core/compact.py` | Create | Orchestration: consolidate + orphan cleanup + vacuum + size report |
| `src/entirecontext/core/config.py` | Modify | Add `capture.content_retention_days` default (30) |
| `src/entirecontext/cli/compact_cmds.py` | Create | `ec compact` CLI command |
| `src/entirecontext/cli/__init__.py` | Modify | Register compact_cmds |
| `tests/test_compact.py` | Create | Core + CLI tests |

---

### Task 1: Add `capture.content_retention_days` config default

**Files:**
- Modify: `src/entirecontext/core/config.py:12-17`
- Test: `tests/test_config.py` (existing)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compact.py — bootstrap with config test
from entirecontext.core.config import DEFAULT_CONFIG


def test_content_retention_days_default():
    assert DEFAULT_CONFIG["capture"]["content_retention_days"] == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_compact.py::test_content_retention_days_default -v`
Expected: FAIL — key not found

- [ ] **Step 3: Add config default**

In `src/entirecontext/core/config.py`, add to the `"capture"` dict:

```python
"content_retention_days": 30,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_compact.py::test_content_retention_days_default -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/core/config.py tests/test_compact.py
git commit -m "feat(config): add capture.content_retention_days default (30)"
```

---

### Task 2: Implement orphan file detection in `core/compact.py`

**Files:**
- Create: `src/entirecontext/core/compact.py`
- Test: `tests/test_compact.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

from entirecontext.core.compact import find_orphan_content_files


class TestFindOrphanContentFiles:
    def test_no_orphans_when_all_referenced(self, ec_repo, ec_db):
        """All JSONL files have turn_content rows → no orphans."""
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session
        from entirecontext.core.turn import create_turn, save_turn_content

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="s1")
        t = create_turn(ec_db, session["id"], 1, user_message="msg")
        save_turn_content(str(ec_repo), ec_db, t["id"], session["id"], '{"m": 1}')

        orphans = find_orphan_content_files(ec_db, str(ec_repo), min_age_seconds=0)
        assert orphans == []

    def test_detects_orphan_file(self, ec_repo, ec_db):
        """A JSONL file with no turn_content row is an orphan."""
        content_dir = Path(str(ec_repo)) / ".entirecontext" / "content" / "orphan-session"
        content_dir.mkdir(parents=True)
        orphan_file = content_dir / "orphan-turn.jsonl"
        orphan_file.write_text('{"orphan": true}')

        orphans = find_orphan_content_files(ec_db, str(ec_repo), min_age_seconds=0)
        assert len(orphans) == 1
        assert orphans[0] == orphan_file
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_compact.py::TestFindOrphanContentFiles -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement `find_orphan_content_files`**

```python
# src/entirecontext/core/compact.py
"""Database and content compaction — consolidate, clean orphans, vacuum."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def find_orphan_content_files(
    conn, repo_path: str, *, min_age_seconds: int = 3600
) -> list[Path]:
    """Find JSONL content files on disk that have no matching turn_content row.

    These can arise when a process is interrupted between DB commit and file
    deletion during consolidation.

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

    # Collect all known content_path values from DB
    rows = conn.execute("SELECT content_path FROM turn_content").fetchall()
    known_paths = {(base / row["content_path"]).resolve() for row in rows}

    orphans = []
    for jsonl_file in content_dir.rglob("*.jsonl"):
        if jsonl_file.resolve() not in known_paths:
            if jsonl_file.stat().st_mtime < cutoff_mtime:
                orphans.append(jsonl_file)

    return sorted(orphans)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_compact.py::TestFindOrphanContentFiles -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/core/compact.py tests/test_compact.py
git commit -m "feat(compact): add orphan content file detection"
```

---

### Task 3: Implement orphan file removal

**Files:**
- Modify: `src/entirecontext/core/compact.py`
- Test: `tests/test_compact.py`

- [ ] **Step 1: Write the failing test**

```python
from entirecontext.core.compact import remove_orphan_content_files


class TestRemoveOrphanContentFiles:
    def test_dry_run_does_not_delete(self, ec_repo, ec_db):
        content_dir = Path(str(ec_repo)) / ".entirecontext" / "content" / "orphan-s"
        content_dir.mkdir(parents=True)
        (content_dir / "orphan.jsonl").write_text("{}")

        result = remove_orphan_content_files(ec_db, str(ec_repo), dry_run=True, min_age_seconds=0)
        assert result["orphans_found"] == 1
        assert result["orphans_removed"] == 0
        assert (content_dir / "orphan.jsonl").exists()

    def test_execute_deletes_orphans(self, ec_repo, ec_db):
        content_dir = Path(str(ec_repo)) / ".entirecontext" / "content" / "orphan-s"
        content_dir.mkdir(parents=True)
        orphan = content_dir / "orphan.jsonl"
        orphan.write_text("{}")

        result = remove_orphan_content_files(ec_db, str(ec_repo), dry_run=False, min_age_seconds=0)
        assert result["orphans_found"] == 1
        assert result["orphans_removed"] == 1
        assert not orphan.exists()

    def test_removes_empty_parent_dir(self, ec_repo, ec_db):
        content_dir = Path(str(ec_repo)) / ".entirecontext" / "content" / "empty-session"
        content_dir.mkdir(parents=True)
        (content_dir / "orphan.jsonl").write_text("{}")

        remove_orphan_content_files(ec_db, str(ec_repo), dry_run=False)
        assert not content_dir.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_compact.py::TestRemoveOrphanContentFiles -v`
Expected: FAIL — function not found

- [ ] **Step 3: Implement `remove_orphan_content_files`**

```python
def remove_orphan_content_files(
    conn, repo_path: str, *, dry_run: bool = True, min_age_seconds: int = 3600
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
            # Remove empty parent directory
            parent = path.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError as exc:
            logger.warning("Failed to remove orphan %s: %s", path, exc)

    return {"orphans_found": len(orphans), "orphans_removed": removed, "bytes_freed": bytes_freed}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_compact.py::TestRemoveOrphanContentFiles -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/core/compact.py tests/test_compact.py
git commit -m "feat(compact): add orphan content file removal"
```

---

### Task 4: Implement VACUUM + size reporting

**Files:**
- Modify: `src/entirecontext/core/compact.py`
- Test: `tests/test_compact.py`

- [ ] **Step 1: Write the failing test**

```python
from entirecontext.core.compact import measure_storage, vacuum_db


class TestMeasureStorage:
    def test_returns_content_and_db_sizes(self, ec_repo, ec_db):
        result = measure_storage(str(ec_repo))
        assert "content_bytes" in result
        assert "db_bytes" in result
        assert "content_file_count" in result
        assert isinstance(result["content_bytes"], int)
        assert isinstance(result["db_bytes"], int)


class TestVacuumDb:
    def test_vacuum_runs_without_error(self, ec_repo, ec_db):
        result = vacuum_db(str(ec_repo))
        assert "db_before" in result
        assert "db_after" in result
        assert result["db_after"] <= result["db_before"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_compact.py::TestMeasureStorage tests/test_compact.py::TestVacuumDb -v`
Expected: FAIL — functions not found

- [ ] **Step 3: Implement `measure_storage` and `vacuum_db`**

```python
def measure_storage(repo_path: str) -> dict[str, int]:
    """Measure current storage usage for content files and DB."""
    base = Path(repo_path) / ".entirecontext"
    content_dir = base / "content"
    db_path = base / "db" / "local.db"

    content_bytes = 0
    content_count = 0
    if content_dir.exists():
        for f in content_dir.rglob("*.jsonl"):
            content_bytes += f.stat().st_size
            content_count += 1

    db_bytes = db_path.stat().st_size if db_path.exists() else 0

    return {
        "content_bytes": content_bytes,
        "content_file_count": content_count,
        "db_bytes": db_bytes,
    }


def vacuum_db(repo_path: str) -> dict[str, int]:
    """Run VACUUM on the local DB and return before/after sizes.

    Opens a dedicated connection for VACUUM (it cannot run inside a
    transaction). Failures are logged but never propagate — VACUUM is
    a minor hygiene step and must not abort a successful compact run.
    """
    import sqlite3

    db_path = Path(repo_path) / ".entirecontext" / "db" / "local.db"
    if not db_path.exists():
        return {"db_before": 0, "db_after": 0}

    db_before = db_path.stat().st_size

    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("VACUUM")
        conn.close()
    except sqlite3.OperationalError as exc:
        logger.warning("VACUUM skipped: %s", exc)
        return {"db_before": db_before, "db_after": db_before}

    db_after = db_path.stat().st_size
    return {"db_before": db_before, "db_after": db_after}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_compact.py::TestMeasureStorage tests/test_compact.py::TestVacuumDb -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/core/compact.py tests/test_compact.py
git commit -m "feat(compact): add storage measurement and VACUUM"
```

---

### Task 5: Implement `compact_repo` orchestrator

**Files:**
- Modify: `src/entirecontext/core/compact.py`
- Test: `tests/test_compact.py`

- [ ] **Step 1: Write the failing test**

```python
from entirecontext.core.compact import compact_repo


class TestCompactRepo:
    def test_dry_run_returns_report(self, ec_repo, ec_db):
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session
        from entirecontext.core.turn import create_turn, save_turn_content

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="s1")
        t = create_turn(ec_db, session["id"], 1, user_message="msg")
        save_turn_content(str(ec_repo), ec_db, t["id"], session["id"], '{"m": 1}')

        report = compact_repo(ec_db, str(ec_repo), retention_days=0, dry_run=True)
        assert "before" in report
        assert "consolidation" in report
        assert "orphans" in report
        assert report["consolidation"]["consolidated"] == 0  # dry run

    def test_execute_consolidates_and_reports(self, ec_repo, ec_db):
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session
        from entirecontext.core.turn import create_turn, save_turn_content

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="s1")
        t = create_turn(ec_db, session["id"], 1, user_message="msg")
        save_turn_content(str(ec_repo), ec_db, t["id"], session["id"], '{"m": 1}')

        report = compact_repo(ec_db, str(ec_repo), retention_days=0, dry_run=False)
        assert report["consolidation"]["consolidated"] == 1
        assert report["after"]["content_file_count"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_compact.py::TestCompactRepo -v`
Expected: FAIL — function not found

- [ ] **Step 3: Implement `compact_repo`**

```python
def compact_repo(
    conn,
    repo_path: str,
    *,
    retention_days: int = 30,
    limit: int = 10000,
    dry_run: bool = True,
) -> dict:
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

    after = measure_storage(repo_path)

    return {
        "before": before,
        "after": after,
        "consolidation": consolidation,
        "orphans": orphans,
        "vacuum": vacuum,
        "retention_days": retention_days,
        "dry_run": dry_run,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_compact.py::TestCompactRepo -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/core/compact.py tests/test_compact.py
git commit -m "feat(compact): add compact_repo orchestrator"
```

---

### Task 6: Implement `ec compact` CLI command

**Files:**
- Create: `src/entirecontext/cli/compact_cmds.py`
- Modify: `src/entirecontext/cli/__init__.py`
- Test: `tests/test_compact.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


class TestCompactCLI:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["compact"])
            assert result.exit_code == 1

    def test_dry_run_by_default(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.db.check_and_migrate"),
            patch(
                "entirecontext.core.compact.compact_repo",
                return_value={
                    "before": {"content_bytes": 1000, "content_file_count": 10, "db_bytes": 500},
                    "after": {"content_bytes": 1000, "content_file_count": 10, "db_bytes": 500},
                    "consolidation": {"candidates": 5, "consolidated": 0},
                    "orphans": {"orphans_found": 2, "orphans_removed": 0, "bytes_freed": 0},
                    "vacuum": {},
                    "retention_days": 30,
                    "dry_run": True,
                },
            ) as mock_compact,
        ):
            result = runner.invoke(app, ["compact"])
            assert result.exit_code == 0
            call_kwargs = mock_compact.call_args
            assert call_kwargs.kwargs.get("dry_run", True) is True

    def test_execute_flag(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.db.check_and_migrate"),
            patch(
                "entirecontext.core.compact.compact_repo",
                return_value={
                    "before": {"content_bytes": 1000, "content_file_count": 10, "db_bytes": 500},
                    "after": {"content_bytes": 200, "content_file_count": 2, "db_bytes": 400},
                    "consolidation": {"candidates": 8, "consolidated": 8},
                    "orphans": {"orphans_found": 1, "orphans_removed": 1, "bytes_freed": 100},
                    "vacuum": {"db_before": 500, "db_after": 400},
                    "retention_days": 30,
                    "dry_run": False,
                },
            ) as mock_compact,
        ):
            result = runner.invoke(app, ["compact", "--execute"])
            assert result.exit_code == 0
            call_kwargs = mock_compact.call_args
            assert call_kwargs.kwargs.get("dry_run") is False

    def test_retention_days_option(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/test"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.db.check_and_migrate"),
            patch(
                "entirecontext.core.compact.compact_repo",
                return_value={
                    "before": {"content_bytes": 0, "content_file_count": 0, "db_bytes": 0},
                    "after": {"content_bytes": 0, "content_file_count": 0, "db_bytes": 0},
                    "consolidation": {"candidates": 0, "consolidated": 0},
                    "orphans": {"orphans_found": 0, "orphans_removed": 0, "bytes_freed": 0},
                    "vacuum": {},
                    "retention_days": 7,
                    "dry_run": True,
                },
            ) as mock_compact,
        ):
            runner.invoke(app, ["compact", "--retention-days", "7"])
            call_kwargs = mock_compact.call_args
            assert call_kwargs.kwargs.get("retention_days") == 7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_compact.py::TestCompactCLI -v`
Expected: FAIL — "compact" command not registered

- [ ] **Step 3: Implement CLI**

```python
# src/entirecontext/cli/compact_cmds.py
"""CLI command for database and content compaction."""

from __future__ import annotations

from typing import Optional

import typer

from rich.console import Console

console = Console()


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    elif n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    else:
        return f"{n / (1024 * 1024 * 1024):.2f} GB"


def compact_cmd(
    execute: bool = typer.Option(False, "--execute", help="Actually compact (default is dry-run)"),
    retention_days: Optional[int] = typer.Option(
        None,
        "--retention-days",
        "-r",
        help="Keep content files newer than N days (default: from config, fallback 30)",
    ),
    limit: int = typer.Option(10000, "--limit", "-n", help="Max turns to consolidate per run"),
):
    """Compact storage: consolidate old content, remove orphans, vacuum DB.

    Runs in dry-run mode by default — use --execute to apply changes.
    """
    from ..core.compact import compact_repo
    from ..core.config import load_config
    from ..core.project import find_git_root
    from ..db import check_and_migrate, get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    if retention_days is None:
        config = load_config(repo_path)
        retention_days = config.get("capture", {}).get("content_retention_days", 30)

    conn = get_db(repo_path)
    try:
        check_and_migrate(conn)
        report = compact_repo(
            conn, repo_path, retention_days=retention_days, limit=limit, dry_run=not execute
        )
    finally:
        conn.close()

    _print_report(report)


def _print_report(report: dict) -> None:
    before = report["before"]
    after = report["after"]
    cons = report["consolidation"]
    orphans = report["orphans"]
    vacuum = report.get("vacuum", {})
    dry = report["dry_run"]

    if dry:
        console.print("[dim]Dry-run mode — no changes made.[/dim]\n")

    console.print(f"[bold]Retention:[/bold] {report['retention_days']} days\n")

    console.print("[bold]Content files:[/bold]")
    console.print(f"  Before: {before['content_file_count']} files ({_format_bytes(before['content_bytes'])})")
    if not dry:
        console.print(f"  After:  {after['content_file_count']} files ({_format_bytes(after['content_bytes'])})")
        saved = before["content_bytes"] - after["content_bytes"]
        if saved > 0:
            console.print(f"  [green]Freed: {_format_bytes(saved)}[/green]")

    console.print(f"\n[bold]Consolidation:[/bold] {cons['candidates']} eligible, {cons['consolidated']} consolidated")

    console.print(f"[bold]Orphans:[/bold] {orphans['orphans_found']} found, {orphans['orphans_removed']} removed")
    if orphans.get("bytes_freed", 0) > 0:
        console.print(f"  [green]Freed: {_format_bytes(orphans['bytes_freed'])}[/green]")

    if vacuum:
        console.print(f"\n[bold]DB vacuum:[/bold] {_format_bytes(vacuum['db_before'])} → {_format_bytes(vacuum['db_after'])}")


def register(app: typer.Typer) -> None:
    app.command("compact")(compact_cmd)
```

- [ ] **Step 4: Register in `cli/__init__.py`**

Add to imports:
```python
from . import compact_cmds  # noqa: E402
```

Add to `_MODULES` tuple:
```python
compact_cmds,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_compact.py::TestCompactCLI -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest tests/test_compact.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/entirecontext/cli/compact_cmds.py src/entirecontext/cli/__init__.py tests/test_compact.py
git commit -m "feat(cli): add ec compact command"
```

---

### Task 7: Integration test with real repo fixture

**Files:**
- Modify: `tests/test_compact.py`

- [ ] **Step 1: Write the integration test**

```python
class TestCompactIntegration:
    def test_full_compact_cycle(self, ec_repo, ec_db):
        """End-to-end: create content → compact → verify cleanup."""
        from entirecontext.core.compact import compact_repo, measure_storage
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session
        from entirecontext.core.turn import create_turn, save_turn_content

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="int-test")

        for i in range(5):
            t = create_turn(ec_db, session["id"], i + 1, user_message=f"turn {i}")
            save_turn_content(str(ec_repo), ec_db, t["id"], session["id"], f'{{"n": {i}}}')

        # Add an orphan
        orphan_dir = Path(str(ec_repo)) / ".entirecontext" / "content" / "ghost"
        orphan_dir.mkdir(parents=True)
        (orphan_dir / "phantom.jsonl").write_text('{"orphan": true}')

        before = measure_storage(str(ec_repo))
        assert before["content_file_count"] == 6  # 5 real + 1 orphan

        report = compact_repo(ec_db, str(ec_repo), retention_days=0, dry_run=False)

        assert report["consolidation"]["consolidated"] == 5
        assert report["orphans"]["orphans_removed"] == 1
        assert report["after"]["content_file_count"] == 0

    def test_respects_retention_days(self, ec_repo, ec_db):
        """Content newer than retention_days is preserved."""
        from entirecontext.core.compact import compact_repo
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session
        from entirecontext.core.turn import create_turn, save_turn_content

        project = get_project(str(ec_repo))
        session = create_session(ec_db, project["id"], session_id="ret-test")
        t = create_turn(ec_db, session["id"], 1, user_message="recent")
        save_turn_content(str(ec_repo), ec_db, t["id"], session["id"], '{"recent": true}')

        # retention_days=9999 → nothing qualifies
        report = compact_repo(ec_db, str(ec_repo), retention_days=9999, dry_run=False)
        assert report["consolidation"]["consolidated"] == 0
        assert report["after"]["content_file_count"] == 1
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_compact.py::TestCompactIntegration -v`
Expected: PASS

- [ ] **Step 3: Run full test suite to check for regressions**

Run: `uv run pytest tests/ -x -q`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_compact.py
git commit -m "test(compact): add integration tests"
```

---

### Task 8: Update CLAUDE.md architecture table

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add compact to architecture table**

In the `cli/` section, add `compact_cmds`. In `core/` section, add `compact`.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add compact module to architecture table"
```

---

## Unresolved questions

1. **Global DB compact** — `~/.entirecontext/db/ec.db`도 VACUUM해야 하나? v1에서는 per-repo만 다루고, 필요 시 확장.
2. **Cron automation** — `ec compact --execute`를 crontab에 등록하는 건 사용자 몫. 나중에 `ec compact --schedule` 같은 편의 기능 추가 가능.
3. **`consolidate_old_turns` limit 10,000** — resume 프로젝트의 3,927 turns 규모에서는 충분. 더 큰 프로젝트에서 pagination이 필요할 수 있음.
