# Hypothesis Validation Framework — v0.11.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the measurement infrastructure (ranking snapshot capture + outcome audit tooling) needed to validate the hypothesis "structured decision retrieval improves agent work quality."

**Architecture:** Two independent subsystems. (A) A new `ranking_snapshots` table with capture inside `rank_related_decisions()`, gated by a `_capture_snapshots` bool parameter passed from each caller (not loaded from DB inside the ranker — avoids silent-failure surface), with double-filter redaction and retention/purge wired into `ec purge`. (B) Standalone scripts under `scripts/experiments/` for outcome inference audit (sampling, labeling, precision computation) and block-experiment analysis. Only (A) is product code; (B) stays outside the shipped CLI.

**Tech Stack:** Python 3.12+, SQLite (WAL), uv, pytest. No new dependencies.

## Global Constraints

- Schema version bumps to 15 (from current 14).
- New config keys live under `[decisions]` section.
- All diff text persisted to `ranking_snapshots` MUST pass both `security.filter_secrets()` AND `content_filter.redact_content()` before storage.
- Stored diff text capped at 8192 bytes (existing convention).
- New table excluded from `ec sync` export by default (exporter uses explicit per-table functions; no `export_ranking_snapshots` = excluded by omission).
- New table covered by `ec purge` with 90-day default retention.
- Migration follows existing `db/migrations/vNNN.py` pattern.
- FTS5 not needed for this table (no search requirement).
- Standalone scripts go to `scripts/experiments/`, not CLI commands.
- Test files match `tests/test_<module>.py` naming.
- `create_decision()` returns `dict` (not id string). `link_decision_to_file(conn, decision_id, file_path)` is the correct function (singular file, not batch).

---

### Task 1: Schema v15 — `ranking_snapshots` Table + Migration

**Files:**
- Create: `src/entirecontext/db/migrations/v015.py`
- Modify: `src/entirecontext/db/schema.py:3` (SCHEMA_VERSION), `src/entirecontext/db/schema.py` (TABLES dict)
- Modify: `src/entirecontext/db/migrations/__init__.py:10` (range upper bound)
- Test: `tests/test_db_schema.py` (append new migration test)

**Interfaces:**
- Produces: `ranking_snapshots` table available via `conn.execute(...)` for Task 3 to INSERT into.

- [ ] **Step 1: Write the failing test**

Follow the existing migration test pattern in `test_db_schema.py` — `get_memory_db()` takes NO parameters. Setup: create schema_version table, insert version 14, create prerequisite tables (retrieval_events at minimum for the FK), then call `check_and_migrate(conn)`.

```python
# Append to tests/test_db_schema.py, inside the TestMigrations class

    def test_migrate_v14_to_v15_adds_ranking_snapshots(self):
        conn = get_memory_db()
        conn.execute(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT, description TEXT)"
        )
        conn.execute("INSERT INTO schema_version (version, description) VALUES (14, 'v14')")
        # ranking_snapshots FK target
        conn.execute(
            "CREATE TABLE retrieval_events (id TEXT PRIMARY KEY, session_id TEXT, search_type TEXT, "
            "created_at TEXT DEFAULT (datetime('now')))"
        )
        conn.commit()

        # Verify table does not exist yet
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ranking_snapshots'"
        ).fetchone()
        assert row is None

        check_and_migrate(conn)

        # Table exists
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ranking_snapshots'"
        ).fetchone()
        assert row is not None

        # Columns are correct
        cols = {r[1] for r in conn.execute("PRAGMA table_info(ranking_snapshots)").fetchall()}
        expected = {
            "id", "retrieval_event_id", "input_files", "input_diff_text",
            "input_commits", "scored_candidates", "effective_limit",
            "created_at",
        }
        assert expected.issubset(cols)

        # retrieval_event_id is nullable
        col_info = {r[1]: r[3] for r in conn.execute("PRAGMA table_info(ranking_snapshots)").fetchall()}
        assert col_info["retrieval_event_id"] == 0  # notnull=0 means nullable

        # Verify schema version
        ver = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()[0]
        assert ver == 15

        # FK works: can insert with NULL retrieval_event_id
        conn.execute(
            "INSERT INTO ranking_snapshots (id, scored_candidates, effective_limit) VALUES ('s1', '[]', 5)"
        )
        row = conn.execute("SELECT * FROM ranking_snapshots WHERE id='s1'").fetchone()
        assert row is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db_schema.py::TestMigrations::test_migrate_v14_to_v15_adds_ranking_snapshots -v`
Expected: FAIL (migration v015 module not found)

- [ ] **Step 3: Create migration v015.py**

```python
# src/entirecontext/db/migrations/v015.py
"""Migration to schema v15 — add ranking_snapshots table for hypothesis validation."""

from __future__ import annotations

import sqlite3

_RANKING_SNAPSHOTS_DDL = """\
CREATE TABLE IF NOT EXISTS ranking_snapshots (
    id TEXT PRIMARY KEY,
    retrieval_event_id TEXT,
    input_files TEXT,
    input_diff_text TEXT,
    input_commits TEXT,
    scored_candidates TEXT NOT NULL,
    effective_limit INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (retrieval_event_id) REFERENCES retrieval_events(id) ON DELETE SET NULL
)
"""


def _create_ranking_snapshots(conn: sqlite3.Connection) -> None:
    conn.execute(_RANKING_SNAPSHOTS_DDL)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ranking_snapshots_event_id "
        "ON ranking_snapshots(retrieval_event_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ranking_snapshots_created_at "
        "ON ranking_snapshots(created_at DESC)"
    )


MIGRATION_STEPS = [_create_ranking_snapshots]
```

- [ ] **Step 4: Update schema.py — bump version and add table DDL**

In `src/entirecontext/db/schema.py`:
- Change `SCHEMA_VERSION = 14` → `SCHEMA_VERSION = 15`
- Add to `TABLES` dict at the end:

```python
"ranking_snapshots": """\
CREATE TABLE IF NOT EXISTS ranking_snapshots (
    id TEXT PRIMARY KEY,
    retrieval_event_id TEXT,
    input_files TEXT,
    input_diff_text TEXT,
    input_commits TEXT,
    scored_candidates TEXT NOT NULL,
    effective_limit INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (retrieval_event_id) REFERENCES retrieval_events(id) ON DELETE SET NULL
)
""",
```

- [ ] **Step 5: Update migrations/__init__.py range**

Change `range(2, 15)` → `range(2, 16)` in `src/entirecontext/db/migrations/__init__.py:10`.

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_db_schema.py::TestMigrations::test_migrate_v14_to_v15_adds_ranking_snapshots -v`
Expected: PASS

- [ ] **Step 7: Run all existing migration tests for regression**

Run: `uv run pytest tests/test_db_schema.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add src/entirecontext/db/migrations/v015.py src/entirecontext/db/schema.py src/entirecontext/db/migrations/__init__.py tests/test_db_schema.py
git commit -m "feat(db): add ranking_snapshots table (schema v15)"
```

---

### Task 2: Config Gate for Snapshot Capture

**Files:**
- Modify: `src/entirecontext/core/config.py` (DEFAULT_CONFIG `decisions` section)
- Test: `tests/test_config.py` (or the existing config test file — verify key presence)

**Interfaces:**
- Produces: `config["decisions"]["capture_ranking_snapshots"]` (bool, default false) consumed by callers in Task 4.

- [ ] **Step 1: Write the failing test**

```python
# Append to existing config tests or create a focused test

def test_capture_ranking_snapshots_default_false():
    from entirecontext.core.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["decisions"]["capture_ranking_snapshots"] is False


def test_ranking_snapshot_retention_days_default():
    from entirecontext.core.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["decisions"]["ranking_snapshot_retention_days"] == 90
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_capture_ranking_snapshots_default_false -v`
Expected: FAIL (KeyError)

- [ ] **Step 3: Add config key**

In `src/entirecontext/core/config.py`, within the `"decisions"` dict of `DEFAULT_CONFIG`, add:

```python
"capture_ranking_snapshots": False,
"ranking_snapshot_retention_days": 90,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py::test_capture_ranking_snapshots_default_false tests/test_config.py::test_ranking_snapshot_retention_days_default -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/core/config.py tests/test_config.py
git commit -m "feat(config): add capture_ranking_snapshots + retention defaults"
```

---

### Task 3: Snapshot Capture Inside `rank_related_decisions()`

**Files:**
- Modify: `src/entirecontext/core/decisions.py:1322-1664` (add `_capture_snapshots` parameter + capture logic after sort, before truncation)
- Test: `tests/test_ranking_snapshots.py` (new file)

**Interfaces:**
- Consumes: `ranking_snapshots` table (Task 1)
- Produces: `snapshot_id` exposed via `_return_stats` dict (`stats["snapshot_id"]`) for callers in Task 4 to backpatch with `retrieval_event_id`. New parameter `_capture_snapshots: bool = False` on `rank_related_decisions()`.

**Design decision (from advisor review):** Capture is gated by a `_capture_snapshots` bool parameter on `rank_related_decisions()`, NOT by loading config from DB inside the ranker. Callers already have config and pass `True`/`False` based on `config["decisions"]["capture_ranking_snapshots"]`. This eliminates: (a) silent failure from DB lookup errors, (b) the need to mock config loading in tests, (c) coupling the ranker to config loading. The ranker also needs the full config dict for `redact_content()` — pass it as `_capture_config: dict | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ranking_snapshots.py
"""Tests for ranking snapshot capture inside rank_related_decisions."""

import json

from entirecontext.core.decisions import (
    rank_related_decisions,
    create_decision,
    link_decision_to_file,
)


def _make_decision(conn, title="test decision", files=None):
    """Helper — create a decision with linked files."""
    decision = create_decision(
        conn,
        title=title,
        rationale="test",
        scope="module",
    )
    did = decision["id"]
    if files:
        for f in files:
            link_decision_to_file(conn, did, f)
    return did


def test_snapshot_captured_when_enabled(ec_db):
    """When _capture_snapshots=True, a snapshot row is written."""
    conn, repo_path = ec_db
    did = _make_decision(conn, files=["src/foo.py"])

    results, stats = rank_related_decisions(
        conn,
        file_paths=["src/foo.py"],
        _return_stats=True,
        _capture_snapshots=True,
    )

    assert "snapshot_id" in stats
    row = conn.execute(
        "SELECT * FROM ranking_snapshots WHERE id = ?", (stats["snapshot_id"],)
    ).fetchone()
    assert row is not None
    candidates = json.loads(row["scored_candidates"])
    assert len(candidates) >= 1
    assert row["effective_limit"] == 10  # default limit
    assert row["retrieval_event_id"] is None  # not yet backpatched


def test_snapshot_not_captured_when_disabled(ec_db):
    """When _capture_snapshots=False (default), no snapshot row."""
    conn, repo_path = ec_db
    _make_decision(conn, files=["src/foo.py"])

    results, stats = rank_related_decisions(
        conn,
        file_paths=["src/foo.py"],
        _return_stats=True,
    )

    assert "snapshot_id" not in stats
    count = conn.execute("SELECT COUNT(*) FROM ranking_snapshots").fetchone()[0]
    assert count == 0


def test_snapshot_diff_text_redacted(ec_db):
    """Diff text is double-filtered before storage."""
    conn, repo_path = ec_db
    _make_decision(conn, files=["src/foo.py"])

    secret_diff = "added key sk-proj-abc123xyz in config"

    results, stats = rank_related_decisions(
        conn,
        file_paths=["src/foo.py"],
        diff_text=secret_diff,
        _return_stats=True,
        _capture_snapshots=True,
    )

    row = conn.execute(
        "SELECT input_diff_text FROM ranking_snapshots WHERE id = ?",
        (stats["snapshot_id"],),
    ).fetchone()
    assert "sk-proj-abc123xyz" not in (row["input_diff_text"] or "")


def test_snapshot_diff_text_truncated_at_8192(ec_db):
    """Diff text exceeding 8192 bytes is truncated."""
    conn, repo_path = ec_db
    _make_decision(conn, files=["src/foo.py"])

    long_diff = "x" * 10000

    results, stats = rank_related_decisions(
        conn,
        file_paths=["src/foo.py"],
        diff_text=long_diff,
        _return_stats=True,
        _capture_snapshots=True,
    )

    row = conn.execute(
        "SELECT input_diff_text FROM ranking_snapshots WHERE id = ?",
        (stats["snapshot_id"],),
    ).fetchone()
    assert len(row["input_diff_text"]) <= 8192


def test_snapshot_stores_full_scored_set(ec_db):
    """Snapshot stores ALL scored candidates, not just top-k."""
    conn, repo_path = ec_db
    for i in range(5):
        _make_decision(conn, title=f"decision {i}", files=["src/foo.py"])

    results, stats = rank_related_decisions(
        conn,
        file_paths=["src/foo.py"],
        limit=2,
        _return_stats=True,
        _capture_snapshots=True,
    )

    assert len(results) == 2  # truncated return
    row = conn.execute(
        "SELECT scored_candidates, effective_limit FROM ranking_snapshots WHERE id = ?",
        (stats["snapshot_id"],),
    ).fetchone()
    candidates = json.loads(row["scored_candidates"])
    assert len(candidates) == 5  # full set
    assert row["effective_limit"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ranking_snapshots.py -v`
Expected: FAIL (`_capture_snapshots` parameter doesn't exist)

- [ ] **Step 3: Implement snapshot capture in `rank_related_decisions()`**

In `src/entirecontext/core/decisions.py`:

Add import near top (if not already present):

```python
from entirecontext.core.security import filter_secrets
from entirecontext.core.content_filter import redact_content
```

Add constant near top of file:

```python
_SNAPSHOT_DIFF_MAX_BYTES = 8192
```

Add two new parameters to the function signature at line 1322:

```python
def rank_related_decisions(
    conn,
    *,
    file_paths: list[str] | None = None,
    assessment_ids: list[str] | None = None,
    diff_text: str | None = None,
    commit_shas: list[str] | None = None,
    limit: int = 10,
    include_stale: bool = True,
    include_superseded: bool = False,
    include_contradicted: bool = False,
    ranking: RankingWeights | None = None,
    quality: QualityWeights | None = None,
    _return_stats: bool = False,
    _capture_snapshots: bool = False,
    _capture_config: dict | None = None,
) -> list[dict] | tuple[list[dict], dict]:
```

Insert capture block between line 1660 (`scored.sort(...)`) and line 1661 (`top = scored[:limit]`):

```python
    scored.sort(key=lambda item: (item["score"], item.get("updated_at", "")), reverse=True)

    # --- Snapshot capture (caller passes _capture_snapshots=True) ---
    snapshot_id = None
    if _capture_snapshots and scored:
        snapshot_id = str(uuid4())

        safe_diff = diff_text
        if safe_diff:
            safe_diff = filter_secrets(safe_diff)
            if _capture_config:
                safe_diff = redact_content(safe_diff, _capture_config)
            if len(safe_diff.encode("utf-8")) > _SNAPSHOT_DIFF_MAX_BYTES:
                safe_diff = safe_diff.encode("utf-8")[:_SNAPSHOT_DIFF_MAX_BYTES].decode(
                    "utf-8", errors="ignore"
                )

        conn.execute(
            "INSERT INTO ranking_snapshots "
            "(id, input_files, input_diff_text, input_commits, scored_candidates, effective_limit) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                snapshot_id,
                json.dumps(file_paths) if file_paths else None,
                safe_diff,
                json.dumps(commit_shas) if commit_shas else None,
                json.dumps(scored),
                limit,
            ),
        )
    # --- End snapshot capture ---

    top = scored[:limit]
    if _return_stats:
        if snapshot_id is not None:
            filter_stats["snapshot_id"] = snapshot_id
        return top, filter_stats
    return top
```

Note: `uuid4` is already imported at the top of this file (used by `create_decision`). `json` is already imported.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ranking_snapshots.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run existing decision tests for regression**

Run: `uv run pytest tests/test_decisions_core.py tests/test_decision_hooks.py -v`
Expected: ALL PASS (no existing callers pass `_capture_snapshots`, so default `False` preserves behavior)

- [ ] **Step 6: Commit**

```bash
git add src/entirecontext/core/decisions.py tests/test_ranking_snapshots.py
git commit -m "feat(decisions): capture ranking snapshots inside rank_related_decisions

Gated by _capture_snapshots bool param (caller-controlled, not DB-loaded).
Stores full scored candidate set pre-truncation with double-filter
redaction on diff text (filter_secrets + redact_content) and 8192-byte
cap."
```

---

### Task 4: Wire Callers — Pass `_capture_snapshots` + Backpatch `retrieval_event_id`

**Files:**
- Modify: `src/entirecontext/core/decisions.py` (add `backpatch_snapshot_event()`)
- Modify: `src/entirecontext/hooks/decision_hooks.py` (session_start handler)
- Modify: `src/entirecontext/core/decision_prompt_surfacing.py` (prompt surfacing worker)
- Modify: `src/entirecontext/mcp/tools/decisions.py` (MCP `ec_decision_related` + `ec_decision_context`)
- Test: `tests/test_ranking_snapshot_backpatch.py` (new file)

**Interfaces:**
- Consumes: `stats["snapshot_id"]` from `rank_related_decisions(..., _return_stats=True, _capture_snapshots=True)` (Task 3)
- Produces: `ranking_snapshots.retrieval_event_id` populated after telemetry event creation.

Each call site that calls `rank_related_decisions` with `_return_stats=True` must:
1. Read `config["decisions"]["capture_ranking_snapshots"]` and pass it as `_capture_snapshots`
2. Pass `config` as `_capture_config` for redaction
3. After creating the retrieval event, call `backpatch_snapshot_event(conn, snapshot_id=stats.get("snapshot_id"), retrieval_event_id=event_id)`

Call sites to wire (identified from codebase exploration):
1. `decision_hooks.py` `on_session_start_decisions` — session_start handler (calls `rank_related_decisions(..., _return_stats=True)`)
2. `decision_hooks.py` `on_post_tool_use_decisions` — uses `_gather_exact_file_matches()`, NOT the full ranker → **skip** (no snapshot)
3. `decision_prompt_surfacing.py` `rank_decisions_for_prompt()` / `run_prompt_surface_worker` — calls `rank_related_decisions()`
4. `mcp/tools/decisions.py` `ec_decision_related` — calls `rank_related_decisions(..., _return_stats=True)`
5. `mcp/tools/decisions.py` `ec_decision_context` — calls `rank_related_decisions()`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ranking_snapshot_backpatch.py
"""Tests that callers backpatch ranking_snapshots.retrieval_event_id."""


def test_backpatch_links_snapshot_to_event(ec_db):
    """After a caller creates a retrieval_event, the snapshot row gets the event_id."""
    conn, repo_path = ec_db

    conn.execute(
        "INSERT INTO ranking_snapshots (id, scored_candidates, effective_limit) VALUES (?, ?, ?)",
        ("snap-1", "[]", 5),
    )

    from entirecontext.core.decisions import backpatch_snapshot_event

    backpatch_snapshot_event(conn, snapshot_id="snap-1", retrieval_event_id="evt-1")

    row = conn.execute(
        "SELECT retrieval_event_id FROM ranking_snapshots WHERE id = ?", ("snap-1",)
    ).fetchone()
    assert row["retrieval_event_id"] == "evt-1"


def test_backpatch_noop_when_no_snapshot(ec_db):
    """Backpatch on a missing snapshot_id is a no-op (no error)."""
    conn, repo_path = ec_db

    from entirecontext.core.decisions import backpatch_snapshot_event

    backpatch_snapshot_event(conn, snapshot_id=None, retrieval_event_id="evt-1")
    # No error, no rows affected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ranking_snapshot_backpatch.py -v`
Expected: FAIL (ImportError — `backpatch_snapshot_event` doesn't exist)

- [ ] **Step 3: Add `backpatch_snapshot_event()` to decisions.py**

In `src/entirecontext/core/decisions.py`:

```python
def backpatch_snapshot_event(
    conn, *, snapshot_id: str | None, retrieval_event_id: str
) -> None:
    """Link a ranking snapshot to its retrieval event after telemetry creation."""
    if snapshot_id is None:
        return
    conn.execute(
        "UPDATE ranking_snapshots SET retrieval_event_id = ? WHERE id = ?",
        (retrieval_event_id, snapshot_id),
    )
```

- [ ] **Step 4: Wire `_capture_snapshots` + backpatch into each call site**

For each call site (1, 3, 4, 5 above), the change pattern is:

```python
# Before: caller already has config loaded
config = load_config(repo_path)
decisions_cfg = config.get("decisions", {})

# Add to the rank_related_decisions() call:
results, stats = rank_related_decisions(
    conn,
    ...,
    _return_stats=True,
    _capture_snapshots=decisions_cfg.get("capture_ranking_snapshots", False),
    _capture_config=config,
)

# After recording the retrieval event:
event_id = record_retrieval_event(conn, ...)
backpatch_snapshot_event(conn, snapshot_id=stats.get("snapshot_id"), retrieval_event_id=event_id)
```

Implementer: read each call site to find the exact location of `rank_related_decisions()` and `record_retrieval_event()` calls, then add the two parameters and the backpatch call. Import `backpatch_snapshot_event` from `entirecontext.core.decisions`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_ranking_snapshot_backpatch.py -v`
Expected: PASS

- [ ] **Step 6: Run hook tests + MCP tests for regression**

Run: `uv run pytest tests/test_decision_hooks.py -v`
Then: `ls tests/test_mcp*` to find the MCP test file, and run it.
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/entirecontext/core/decisions.py src/entirecontext/hooks/decision_hooks.py \
  src/entirecontext/core/decision_prompt_surfacing.py src/entirecontext/mcp/tools/decisions.py \
  tests/test_ranking_snapshot_backpatch.py
git commit -m "feat(decisions): wire _capture_snapshots to callers + backpatch event link

All rank_related_decisions callers now pass _capture_snapshots from config
and backpatch ranking_snapshots.retrieval_event_id after event creation."
```

---

### Task 5: Snapshot Purge + Retention + CLI Wiring

**Files:**
- Modify: `src/entirecontext/core/purge.py` (add `purge_ranking_snapshots()`)
- Modify: `src/entirecontext/cli/purge_cmds.py` (add `purge-snapshots` subcommand)
- Test: `tests/test_ranking_snapshot_purge.py` (new file)

**Interfaces:**
- Consumes: `ranking_snapshots` table (Task 1), `ranking_snapshot_retention_days` config (Task 2)
- Produces: `purge_ranking_snapshots(conn, retention_days, dry_run)` callable from CLI via `ec purge snapshots`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ranking_snapshot_purge.py
"""Tests for ranking snapshot purge and retention."""

from datetime import datetime, timedelta, timezone


def test_purge_removes_old_snapshots(ec_db):
    conn, repo_path = ec_db
    old_date = (datetime.now(timezone.utc) - timedelta(days=100)).strftime("%Y-%m-%d %H:%M:%S")
    recent_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        "INSERT INTO ranking_snapshots (id, scored_candidates, effective_limit, created_at) VALUES (?, ?, ?, ?)",
        ("old-1", "[]", 5, old_date),
    )
    conn.execute(
        "INSERT INTO ranking_snapshots (id, scored_candidates, effective_limit, created_at) VALUES (?, ?, ?, ?)",
        ("recent-1", "[]", 5, recent_date),
    )

    from entirecontext.core.purge import purge_ranking_snapshots

    result = purge_ranking_snapshots(conn, retention_days=90, dry_run=False)
    assert result["deleted"] == 1

    remaining = conn.execute("SELECT id FROM ranking_snapshots").fetchall()
    assert len(remaining) == 1
    assert remaining[0]["id"] == "recent-1"


def test_purge_dry_run_does_not_delete(ec_db):
    conn, repo_path = ec_db
    old_date = (datetime.now(timezone.utc) - timedelta(days=100)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO ranking_snapshots (id, scored_candidates, effective_limit, created_at) VALUES (?, ?, ?, ?)",
        ("old-1", "[]", 5, old_date),
    )

    from entirecontext.core.purge import purge_ranking_snapshots

    result = purge_ranking_snapshots(conn, retention_days=90, dry_run=True)
    assert result["deleted"] == 0
    assert result["matched"] == 1

    remaining = conn.execute("SELECT COUNT(*) FROM ranking_snapshots").fetchone()[0]
    assert remaining == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ranking_snapshot_purge.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement purge function**

In `src/entirecontext/core/purge.py`, add:

```python
def purge_ranking_snapshots(
    conn, retention_days: int = 90, dry_run: bool = True
) -> dict[str, Any]:
    """Purge ranking snapshots older than retention_days."""
    cutoff = conn.execute(
        "SELECT datetime('now', ?)", (f"-{retention_days} days",)
    ).fetchone()[0]

    matched = conn.execute(
        "SELECT COUNT(*) FROM ranking_snapshots WHERE created_at < ?", (cutoff,)
    ).fetchone()[0]

    if dry_run:
        return {"matched": matched, "deleted": 0, "dry_run": True}

    conn.execute("DELETE FROM ranking_snapshots WHERE created_at < ?", (cutoff,))
    return {"matched": matched, "deleted": matched, "dry_run": False}
```

- [ ] **Step 4: Wire into purge CLI**

In `src/entirecontext/cli/purge_cmds.py`, add a new subcommand following the existing pattern:

```python
@purge_app.command("snapshots")
def purge_snapshots_cmd(
    retention_days: int = typer.Option(90, help="Delete snapshots older than N days"),
    execute: bool = typer.Option(False, "--execute", help="Actually delete (default: dry run)"),
):
    """Purge old ranking snapshots (retention-based)."""
    from entirecontext.core.purge import purge_ranking_snapshots

    conn = _get_conn()  # or however the existing commands get their connection
    result = purge_ranking_snapshots(conn, retention_days=retention_days, dry_run=not execute)

    if result["dry_run"]:
        typer.echo(f"[DRY RUN] Would delete {result['matched']} snapshots older than {retention_days}d")
    else:
        typer.echo(f"Deleted {result['deleted']} snapshots older than {retention_days}d")
```

Implementer: read `purge_cmds.py` to match the existing pattern for `_get_conn()`, `purge_app`, and option naming conventions.

- [ ] **Step 5: Verify export exclusion**

Run: `grep -n "def export_" src/entirecontext/sync/exporter.py`

The exporter uses explicit per-table functions (export_sessions, export_checkpoints, etc.). No `export_ranking_snapshots` = excluded by omission. No code change needed.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_ranking_snapshot_purge.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/entirecontext/core/purge.py src/entirecontext/cli/purge_cmds.py tests/test_ranking_snapshot_purge.py
git commit -m "feat(purge): add ranking_snapshots retention purge + CLI subcommand

ec purge snapshots --retention-days 90 --execute
Default: dry run, 90-day retention."
```

---

### Task 6: Seeded-Secret Regression Test

**Files:**
- Test: `tests/test_ranking_snapshot_security.py` (new file)

**Interfaces:**
- Consumes: Snapshot capture from Task 3 (end-to-end through `rank_related_decisions`)

- [ ] **Step 1: Write the test**

```python
# tests/test_ranking_snapshot_security.py
"""Seeded-secret regression: planted tokens must never reach ranking_snapshots."""

import json

from entirecontext.core.decisions import (
    create_decision,
    link_decision_to_file,
    rank_related_decisions,
)


def test_seeded_secret_never_stored(ec_db):
    """A planted API key in diff_text must be redacted before snapshot storage."""
    conn, repo_path = ec_db

    decision = create_decision(conn, title="secret test", rationale="test", scope="module")
    link_decision_to_file(conn, decision["id"], "src/config.py")

    planted_secrets = [
        "sk-proj-ABCDEF1234567890abcdef",
        "ghp_1234567890abcdefABCDEF1234567890abcd",
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test.signature",
    ]
    diff_with_secrets = "\n".join(
        f"+API_KEY = '{s}'" for s in planted_secrets
    )

    results, stats = rank_related_decisions(
        conn,
        file_paths=["src/config.py"],
        diff_text=diff_with_secrets,
        _return_stats=True,
        _capture_snapshots=True,
    )

    row = conn.execute(
        "SELECT input_diff_text FROM ranking_snapshots WHERE id = ?",
        (stats["snapshot_id"],),
    ).fetchone()

    stored_text = row["input_diff_text"] or ""
    for secret in planted_secrets:
        assert secret not in stored_text, f"Secret leaked into snapshot: {secret[:20]}..."

    assert "[REDACTED]" in stored_text
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/test_ranking_snapshot_security.py -v`
Expected: PASS (if Task 3 redaction is correct)

- [ ] **Step 3: Commit**

```bash
git add tests/test_ranking_snapshot_security.py
git commit -m "test(security): seeded-secret regression for ranking_snapshots"
```

---

### Task 7: Outcome Inference Audit — Sampling Script

**Files:**
- Create: `scripts/experiments/__init__.py` (empty)
- Create: `scripts/experiments/sample_outcome_audit.py`

**Interfaces:**
- Consumes: `decision_outcomes` table (existing), `sessions`/`turns` tables
- Produces: A JSONL review sheet at `scripts/experiments/output/audit_cases.jsonl` with fields: `session_id`, `decision_id`, `files_overlap`, `turn_content_path` (outcome label withheld for blind review)

- [ ] **Step 1: Create the script**

```python
#!/usr/bin/env python3
"""Sample N=50 auto-inferred 'accepted' outcomes for human audit.

Produces a label-blinded review sheet: the recorded outcome is NOT in the output,
so the reviewer judges from transcript alone before comparing.

Usage:
    python scripts/experiments/sample_outcome_audit.py [--db PATH] [--n 50] [--output PATH]
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from pathlib import Path


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def sample_accepted_outcomes(conn: sqlite3.Connection, n: int = 50) -> list[dict]:
    """Sample N auto-inferred 'accepted' outcomes, label-blinded."""
    rows = conn.execute(
        """
        SELECT do.id as outcome_id, do.decision_id, do.session_id,
               do.note, do.created_at,
               d.title as decision_title
        FROM decision_outcomes do
        JOIN decisions d ON d.id = do.decision_id
        WHERE do.outcome_type = 'accepted'
          AND do.note LIKE 'auto:%'
        ORDER BY do.created_at DESC
        """
    ).fetchall()

    cases = [dict(r) for r in rows]
    if len(cases) > n:
        cases = random.sample(cases, n)

    review_sheet = []
    for case in cases:
        sid = case["session_id"]
        did = case["decision_id"]

        decision_files = [
            r["file_path"]
            for r in conn.execute(
                "SELECT file_path FROM decision_files WHERE decision_id = ?", (did,)
            ).fetchall()
        ]

        session_turns = conn.execute(
            "SELECT id, turn_number, files_touched FROM turns WHERE session_id = ? ORDER BY turn_number",
            (sid,),
        ).fetchall()

        content_paths = []
        for turn in session_turns:
            tc = conn.execute(
                "SELECT content_path FROM turn_content WHERE turn_id = ?", (turn["id"],)
            ).fetchone()
            if tc:
                content_paths.append(tc["content_path"])

        review_sheet.append({
            "outcome_id": case["outcome_id"],
            "session_id": sid,
            "decision_id": did,
            "decision_title": case["decision_title"],
            "decision_files": decision_files,
            "session_turn_count": len(session_turns),
            "content_paths": content_paths[:5],
            # outcome_type intentionally withheld for blind review
        })

    return review_sheet


def main() -> None:
    parser = argparse.ArgumentParser(description="Sample outcomes for audit")
    parser.add_argument("--db", default=".entirecontext/db/local.db")
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--output", default="scripts/experiments/output/audit_cases.jsonl")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    conn = _connect(args.db)
    cases = sample_accepted_outcomes(conn, n=args.n)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for case in cases:
            f.write(json.dumps(case) + "\n")

    print(f"Wrote {len(cases)} cases to {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create empty `__init__.py` and output .gitignore**

```bash
mkdir -p scripts/experiments/output
touch scripts/experiments/__init__.py
echo "*.jsonl" > scripts/experiments/output/.gitignore
```

- [ ] **Step 3: Verify script runs (syntax check)**

Run: `uv run python -c "import ast; ast.parse(open('scripts/experiments/sample_outcome_audit.py').read())"`
Expected: no error

- [ ] **Step 4: Commit**

```bash
git add scripts/experiments/
git commit -m "feat(experiments): add outcome inference audit sampling script

Standalone script (not shipped CLI) that samples N=50 auto-inferred
'accepted' outcomes with label-blinding for human review."
```

---

### Task 8: Outcome Inference Audit — Precision Computation Script

**Files:**
- Create: `scripts/experiments/compute_audit_precision.py`

**Interfaces:**
- Consumes: Reviewer's `scripts/experiments/output/audit_verdicts.jsonl` (manually created JSONL with `{outcome_id, verdict, rationale}`)
- Produces: Precision report to stdout

- [ ] **Step 1: Create the script**

```python
#!/usr/bin/env python3
"""Compute precision from human audit verdicts.

Reads audit_verdicts.jsonl (reviewer output) and computes:
- True positive rate (precision)
- 95% confidence interval (Wilson score interval)
- Breakdown by verdict category

Usage:
    python scripts/experiments/compute_audit_precision.py [--verdicts PATH]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def wilson_ci(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return ((centre - spread) / denom, (centre + spread) / denom)


def compute_precision(verdicts_path: str) -> dict:
    path = Path(verdicts_path)
    if not path.exists():
        print(f"Verdicts file not found: {path}", file=sys.stderr)
        sys.exit(1)

    verdicts = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                verdicts.append(json.loads(line))

    n = len(verdicts)
    if n == 0:
        return {"n": 0, "precision": None, "ci_lower": None, "ci_upper": None}

    counts = {"true_positive": 0, "false_positive": 0, "ambiguous": 0}
    for v in verdicts:
        verdict = v.get("verdict", "").lower()
        if verdict in counts:
            counts[verdict] += 1
        else:
            counts.setdefault(verdict, 0)
            counts[verdict] += 1

    evaluable = counts["true_positive"] + counts["false_positive"]
    if evaluable == 0:
        precision = None
        ci = (None, None)
    else:
        precision = counts["true_positive"] / evaluable
        ci = wilson_ci(precision, evaluable)

    return {
        "n": n,
        "evaluable": evaluable,
        "ambiguous": counts["ambiguous"],
        "true_positive": counts["true_positive"],
        "false_positive": counts["false_positive"],
        "precision": round(precision, 3) if precision is not None else None,
        "ci_95_lower": round(ci[0], 3) if ci[0] is not None else None,
        "ci_95_upper": round(ci[1], 3) if ci[1] is not None else None,
        "gate_pass": precision is not None and precision >= 0.5,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute audit precision")
    parser.add_argument(
        "--verdicts",
        default="scripts/experiments/output/audit_verdicts.jsonl",
    )
    args = parser.parse_args()

    result = compute_precision(args.verdicts)
    print(json.dumps(result, indent=2))

    if result["precision"] is not None:
        status = "PASS" if result["gate_pass"] else "FAIL"
        print(f"\nGate: precision={result['precision']:.1%} — {status} (threshold >=50%)")
        if result["ci_95_lower"] and result["ci_95_upper"]:
            print(f"95% CI: [{result['ci_95_lower']:.1%}, {result['ci_95_upper']:.1%}]")
        if 0.4 <= (result["precision"] or 0) <= 0.6:
            print("NOTE: Estimate in 0.4-0.6 range. Consider extending to N=100.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify script syntax**

Run: `uv run python -c "import ast; ast.parse(open('scripts/experiments/compute_audit_precision.py').read())"`
Expected: no error

- [ ] **Step 3: Commit**

```bash
git add scripts/experiments/compute_audit_precision.py
git commit -m "feat(experiments): add outcome audit precision computation script

Wilson CI, gate at precision >= 0.5, warns when estimate in 0.4-0.6."
```

---

### Task 9: Block Experiment — Analysis Script

**Files:**
- Create: `scripts/experiments/analyze_blocks.py`

**Interfaces:**
- Consumes: `scripts/experiments/output/experiment-blocks.jsonl` (manually maintained block log), `sessions` table, `retrieval_events` table
- Produces: Block-pair comparison report to stdout

- [ ] **Step 1: Create the script**

```python
#!/usr/bin/env python3
"""Analyze injection ON/OFF block experiment results.

Reads experiment-blocks.jsonl and joins with sessions DB to compute
paired block differences for quality proxies.

Block log format (one entry per block transition):
    {"block_id": 1, "injection": true, "started_at": "2026-07-10T00:00:00Z", "qualifying_sessions": 0}

Usage:
    python scripts/experiments/analyze_blocks.py [--db PATH] [--blocks PATH]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def load_blocks(blocks_path: str) -> list[dict]:
    path = Path(blocks_path)
    if not path.exists():
        print(f"Blocks file not found: {path}", file=sys.stderr)
        sys.exit(1)

    blocks = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                blocks.append(json.loads(line))
    return sorted(blocks, key=lambda b: b["started_at"])


def sessions_in_block(conn: sqlite3.Connection, start: str, end: str | None) -> list[dict]:
    """Get qualifying sessions (total_turns >= 5 AND has checkpoint) within a time window."""
    query = """
        SELECT s.id, s.total_turns, s.started_at, s.ended_at,
               (SELECT COUNT(*) FROM checkpoints c WHERE c.session_id = s.id) as checkpoint_count
        FROM sessions s
        WHERE s.total_turns >= 5
          AND s.started_at >= ?
    """
    params: list = [start]
    if end:
        query += " AND s.started_at < ?"
        params.append(end)

    rows = conn.execute(query, params).fetchall()
    return [
        dict(r) for r in rows
        if r["checkpoint_count"] > 0
    ]


def manual_retrieval_count(conn: sqlite3.Connection, session_ids: list[str]) -> int:
    """Count manual retrieval events (non-proactive) in given sessions."""
    if not session_ids:
        return 0
    placeholders = ",".join("?" for _ in session_ids)
    row = conn.execute(
        f"""
        SELECT COUNT(*) FROM retrieval_events
        WHERE session_id IN ({placeholders})
          AND search_type NOT IN ('session_start', 'post_tool_use', 'user_prompt')
        """,
        session_ids,
    ).fetchone()
    return row[0]


def analyze(conn: sqlite3.Connection, blocks: list[dict]) -> dict:
    block_results = []
    for i, block in enumerate(blocks):
        end = blocks[i + 1]["started_at"] if i + 1 < len(blocks) else None
        sessions = sessions_in_block(conn, block["started_at"], end)
        session_ids = [s["id"] for s in sessions]
        manual_count = manual_retrieval_count(conn, session_ids)

        block_results.append({
            "block_id": block["block_id"],
            "injection": block["injection"],
            "started_at": block["started_at"],
            "ended_at": end,
            "qualifying_sessions": len(sessions),
            "avg_turns": (
                sum(s["total_turns"] for s in sessions) / len(sessions)
                if sessions else None
            ),
            "manual_retrieval_events": manual_count,
        })

    on_blocks = [b for b in block_results if b["injection"]]
    off_blocks = [b for b in block_results if not b["injection"]]
    pairs = list(zip(on_blocks, off_blocks))

    return {
        "total_blocks": len(block_results),
        "block_details": block_results,
        "pairs": len(pairs),
        "compensation_check": {
            "on_manual_retrieval_avg": (
                sum(b["manual_retrieval_events"] for b in on_blocks) / len(on_blocks)
                if on_blocks else None
            ),
            "off_manual_retrieval_avg": (
                sum(b["manual_retrieval_events"] for b in off_blocks) / len(off_blocks)
                if off_blocks else None
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze block experiment")
    parser.add_argument("--db", default=".entirecontext/db/local.db")
    parser.add_argument(
        "--blocks",
        default="scripts/experiments/output/experiment-blocks.jsonl",
    )
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    conn = _connect(args.db)
    blocks = load_blocks(args.blocks)
    result = analyze(conn, blocks)
    print(json.dumps(result, indent=2))

    print(f"\n--- Summary ---")
    print(f"Blocks: {result['total_blocks']}, Pairs: {result['pairs']}")
    if result["pairs"] < 4:
        print("WARNING: <4 block pairs. Directional signal only; do not claim significance.")
    comp = result["compensation_check"]
    if comp["on_manual_retrieval_avg"] is not None and comp["off_manual_retrieval_avg"] is not None:
        if comp["off_manual_retrieval_avg"] > comp["on_manual_retrieval_avg"] * 1.5:
            print(
                "WARNING: OFF blocks show elevated manual retrieval — "
                "estimand shifts from 'injection vs nothing' to 'proactive vs on-demand'."
            )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify script syntax**

Run: `uv run python -c "import ast; ast.parse(open('scripts/experiments/analyze_blocks.py').read())"`
Expected: no error

- [ ] **Step 3: Commit**

```bash
git add scripts/experiments/analyze_blocks.py
git commit -m "feat(experiments): add block experiment analysis script

Joins sessions DB with block log, computes paired differences,
manual retrieval compensation check."
```

---

### Task 10: Integration Test — Full Capture-to-Purge Cycle

**Files:**
- Test: `tests/test_ranking_snapshot_integration.py` (new file)

**Interfaces:**
- Consumes: All product code from Tasks 1–5

- [ ] **Step 1: Write the integration test**

This test exercises the real code path — NO monkeypatch on config. It passes `_capture_snapshots=True` directly.

```python
# tests/test_ranking_snapshot_integration.py
"""Integration: full lifecycle — capture -> backpatch -> purge."""

import json
from datetime import datetime, timedelta, timezone

from entirecontext.core.decisions import (
    create_decision,
    link_decision_to_file,
    rank_related_decisions,
    backpatch_snapshot_event,
)
from entirecontext.core.purge import purge_ranking_snapshots


def test_full_snapshot_lifecycle(ec_db):
    conn, repo_path = ec_db

    # 1. Create decision
    decision = create_decision(conn, title="lifecycle test", rationale="test", scope="module")
    link_decision_to_file(conn, decision["id"], "src/app.py")

    # 2. Rank with capture enabled (direct param, no config mock)
    results, stats = rank_related_decisions(
        conn, file_paths=["src/app.py"], _return_stats=True, _capture_snapshots=True
    )
    snapshot_id = stats["snapshot_id"]

    # 3. Backpatch
    backpatch_snapshot_event(conn, snapshot_id=snapshot_id, retrieval_event_id="evt-test-1")
    row = conn.execute(
        "SELECT retrieval_event_id FROM ranking_snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()
    assert row["retrieval_event_id"] == "evt-test-1"

    # 4. Verify snapshot content
    row = conn.execute("SELECT * FROM ranking_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    candidates = json.loads(row["scored_candidates"])
    assert len(candidates) >= 1
    assert row["effective_limit"] == 10

    # 5. Purge (not yet old enough)
    result = purge_ranking_snapshots(conn, retention_days=90, dry_run=False)
    assert result["deleted"] == 0

    # 6. Manually age the snapshot
    old_date = (datetime.now(timezone.utc) - timedelta(days=100)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE ranking_snapshots SET created_at = ? WHERE id = ?", (old_date, snapshot_id))

    # 7. Purge (now old enough)
    result = purge_ranking_snapshots(conn, retention_days=90, dry_run=False)
    assert result["deleted"] == 1

    # 8. Verify gone
    row = conn.execute("SELECT * FROM ranking_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    assert row is None
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/test_ranking_snapshot_integration.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest --tb=short -q`
Expected: ALL PASS, no regressions

- [ ] **Step 4: Commit**

```bash
git add tests/test_ranking_snapshot_integration.py
git commit -m "test: add ranking snapshot full lifecycle integration test"
```

---

## Resolved Questions (from advisor review)

1. **Config access inside ranker → parameter instead**: Advisor correctly identified that `_load_config_for_capture` with DB lookup + try/except creates a silent-failure surface — tests would mock it away, and production failures would silently disable capture. **Resolution:** `_capture_snapshots: bool` and `_capture_config: dict | None` parameters on `rank_related_decisions()`. Callers already have config; they pass the bool. Tests exercise real code with no mocking.

2. **`get_memory_db(target_version=14)` doesn't exist**: Confirmed — fixture takes no params. **Resolution:** Follow existing pattern: manually create `schema_version` table + insert version 14 + create prerequisite tables, then call `check_and_migrate(conn)`.

3. **`link_decision_files` doesn't exist**: Confirmed — the actual function is `link_decision_to_file(conn, decision_id, file_path)` (singular). `create_decision()` returns `dict`, not id string. **Resolution:** All test code corrected.

4. **`purge_ranking_snapshots` not wired to CLI**: Brainstorm requires "cover with `ec purge`". **Resolution:** Task 5 now includes CLI subcommand `ec purge snapshots`.

## Resolved Design Questions

1. **`redact_content` config dependency — 현 방식 유지**: `filter_secrets()`가 always-on primary guard (sk-, ghp_, Bearer 패턴). `redact_content`는 사용자가 `capture.exclusions.enabled`를 설정했을 때만 추가 방어선. 스냅샷 캡처만을 위해 exclusion 강제 활성화하면 사용자 config 의도를 무시하게 됨. Task 6 seeded-secret 테스트가 `filter_secrets` 단독으로 주요 패턴을 잡는지 검증 — 실패하면 재검토.

2. **Post-tool-use handler 스냅샷 부재 — 수용**: `on_post_tool_use_decisions`는 `_gather_exact_file_matches()` fast path 사용, full ranker 미호출. Phase 2b benchmark에 tool-use 채널 데이터 없음. tool-use surfacing이 가장 미성숙한 채널이고, 나중에 ranker 경유로 전환하면 자연 해소. 지금 scope 확장 불필요.

3. **Snapshot INSERT commit boundary — 구현 시 검증**: 대부분의 caller가 `transaction(conn)` 안에서 rank + telemetry를 묶으므로 INSERT는 같은 트랜잭션에 포함됨. SQLite autocommit 모드(isolation_level=None)라면 즉시 반영. Task 3 구현자가 `ec_db` fixture로 INSERT → close → reopen → SELECT 테스트 1회 수행으로 확인.
