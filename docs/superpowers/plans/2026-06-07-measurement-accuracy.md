# v0.8.1 Measurement Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix measurement infrastructure so maturity scores reflect reality — no new features, only corrections that enable trustworthy attribution for v0.9.0.

**Architecture:** Three sequential items: (1) auto-close stale codex sessions so they have valid `ended_at`, (2) normalize dashboard denominators so all session-based maturity metrics use ended sessions only, (3) build verdict accuracy reporting from existing enrichment feedback data. Item 1 is a data prerequisite for item 2's verification; item 3 is independent.

**Tech Stack:** Python 3.12+, SQLite, Typer CLI, pytest

**Key decision:** `retrieval_assisted_session_rate` currently uses `sessions_total` (all sessions including active) as denominator. After this change, it uses `sessions_ended` (only completed sessions), consistent with `checkpoint_coverage_rate`. Rationale: active sessions haven't completed their lifecycle and should not count toward maturity — a session that just started cannot be "retrieval-assisted" or not yet.

---

## Prior Retro Carryover Review (v0.8.0)

| v0.8.0 Retro Item | This Release? | Rationale |
|---|---|---|
| codex session lifecycle 누락 | Yes (Task 1) | Primary measurement distortion source |
| maturity 분모 왜곡 | Yes (Task 2) | Direct consequence of lifecycle gap |
| rule-based verdict 품질 의문 | Yes (Task 3) | Accuracy baseline before v0.9.0 tuning |
| intervene=5 gap | No → v0.9.0 | Feature work (auto-apply inference), blocked until measurement is trustworthy |
| PR blast radius 미확인 | N/A | Process improvement (plan checklist), already in memory |

## File Structure

| File | Role | Action |
|---|---|---|
| `src/entirecontext/core/session.py` | Session CRUD | Add `close_stale_sessions()` |
| `src/entirecontext/hooks/codex_ingest.py` | Codex notify handler | Call `close_stale_sessions()` after ingestion |
| `src/entirecontext/core/config.py` | Config defaults | Add `codex_session_idle_minutes` |
| `src/entirecontext/core/dashboard.py` | Maturity metrics | Change `retrieval_assisted_session_rate` numerator AND denominator to ended-session basis |
| `src/entirecontext/core/auto_assess.py` | Assessment logic | Add `compute_verdict_accuracy()` |
| `src/entirecontext/cli/checkpoint_cmds.py` | CLI commands | Add `ec assess accuracy` |
| `tests/test_codex_session_autoclose.py` | Tests for Task 1 | Create |
| `tests/test_dashboard.py` | Dashboard tests | Modify (denominator change) |
| `tests/test_verdict_accuracy.py` | Tests for Task 3 | Create |

## Callers & Invariants

### Changed Functions — Callers

| Function | Callers |
|---|---|
| `session.py` (new `close_stale_sessions`) | `codex_ingest.py:ingest_codex_notify_event()`, `session_cmds.py:session_backfill_ended_at()` |
| `dashboard.py:get_dashboard_stats()` | `cli/dashboard_cmds.py`, `mcp/tools/misc.py`, `tests/test_dashboard.py` |
| `auto_assess.py` (new `compute_verdict_accuracy`) | `cli/checkpoint_cmds.py` (new command) |
| `config.py:DEFAULT_CONFIG` | All `load_config()` callers (no breaking change — additive key) |

### Invariants

1. `close_stale_sessions` must use optimistic concurrency: re-check `ended_at IS NULL AND last_activity_at = ?` before UPDATE (same pattern as `session_cmds.py:520-524`)
2. `retrieval_assisted_session_rate` numerator and denominator must share the same population (`ended_at IS NOT NULL`) — a ratio where sides use different filters can exceed 1.0
3. Maturity grade thresholds unchanged (capture/distill/retrieve/intervene point allocation stays the same)
4. Active claude sessions (`ended_at IS NULL, session_type='claude'`) must NOT be auto-closed
5. `checkpoint_coverage_rate` formula unchanged — it already correctly filters on `ended_at IS NOT NULL`
6. Existing `ec session backfill-ended-at` command behavior unchanged — it remains a manual safety net for all session types
7. `feedback` column accepts only `"agree"` or `"disagree"` (validated by `VALID_FEEDBACKS`); `"auto:revised:..."` goes to `feedback_reason`

---

### Task 1: Codex Session Auto-Close

**Files:**
- Modify: `src/entirecontext/core/session.py`
- Modify: `src/entirecontext/core/config.py:11-17`
- Modify: `src/entirecontext/hooks/codex_ingest.py:258-336`
- Create: `tests/test_codex_session_autoclose.py`

- [ ] **Step 1: Write the failing test — `close_stale_sessions` basic behavior**

```python
# tests/test_codex_session_autoclose.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from entirecontext.core.session import close_stale_sessions, create_session
from entirecontext.core.project import get_project


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_close_stale_sessions_closes_idle_codex(ec_repo, ec_db):
    project = get_project(str(ec_repo))
    s = create_session(ec_db, project["id"], session_type="codex", session_id="codex-stale-1")
    two_hours_ago = _iso(datetime.now(timezone.utc) - timedelta(hours=2))
    ec_db.execute(
        "UPDATE sessions SET last_activity_at = ? WHERE id = ?",
        (two_hours_ago, s["id"]),
    )
    ec_db.commit()

    closed = close_stale_sessions(ec_db, idle_minutes=60)

    assert closed == 1
    row = ec_db.execute("SELECT ended_at FROM sessions WHERE id = ?", (s["id"],)).fetchone()
    assert row["ended_at"] == two_hours_ago
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_codex_session_autoclose.py::test_close_stale_sessions_closes_idle_codex -v`
Expected: FAIL — `ImportError: cannot import name 'close_stale_sessions'`

- [ ] **Step 3: Implement `close_stale_sessions` in `core/session.py`**

Add to the end of `src/entirecontext/core/session.py`:

```python
def close_stale_sessions(
    conn,
    idle_minutes: int = 60,
    session_type: str = "codex",
) -> int:
    """Auto-close stale sessions: set ended_at = last_activity_at for idle sessions.

    Uses optimistic concurrency to avoid clobbering sessions resumed between
    SELECT and UPDATE.
    """
    rows = conn.execute(
        "SELECT id, last_activity_at FROM sessions"
        " WHERE ended_at IS NULL"
        " AND session_type = ?"
        " AND last_activity_at IS NOT NULL"
        " AND datetime(last_activity_at) < datetime('now', ?)",
        (session_type, f"-{idle_minutes} minutes"),
    ).fetchall()

    closed = 0
    for row in rows:
        cursor = conn.execute(
            "UPDATE sessions SET ended_at = last_activity_at"
            " WHERE id = ? AND ended_at IS NULL AND last_activity_at = ?",
            (row["id"], row["last_activity_at"]),
        )
        closed += cursor.rowcount
    if closed:
        conn.commit()
    return closed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_codex_session_autoclose.py::test_close_stale_sessions_closes_idle_codex -v`
Expected: PASS

- [ ] **Step 5: Write test — does NOT close active codex sessions**

```python
def test_close_stale_sessions_skips_recent_codex(ec_repo, ec_db):
    project = get_project(str(ec_repo))
    s = create_session(ec_db, project["id"], session_type="codex", session_id="codex-active-1")
    # last_activity_at is set to now by create_session — should NOT be closed
    ec_db.commit()

    closed = close_stale_sessions(ec_db, idle_minutes=60)

    assert closed == 0
    row = ec_db.execute("SELECT ended_at FROM sessions WHERE id = ?", (s["id"],)).fetchone()
    assert row["ended_at"] is None
```

- [ ] **Step 6: Run test — should pass without code changes**

Run: `uv run pytest tests/test_codex_session_autoclose.py::test_close_stale_sessions_skips_recent_codex -v`
Expected: PASS

- [ ] **Step 7: Write test — does NOT close claude sessions**

```python
def test_close_stale_sessions_skips_claude_sessions(ec_repo, ec_db):
    project = get_project(str(ec_repo))
    s = create_session(ec_db, project["id"], session_type="claude", session_id="claude-stale-1")
    two_hours_ago = _iso(datetime.now(timezone.utc) - timedelta(hours=2))
    ec_db.execute(
        "UPDATE sessions SET last_activity_at = ? WHERE id = ?",
        (two_hours_ago, s["id"]),
    )
    ec_db.commit()

    closed = close_stale_sessions(ec_db, idle_minutes=60)

    assert closed == 0
    row = ec_db.execute("SELECT ended_at FROM sessions WHERE id = ?", (s["id"],)).fetchone()
    assert row["ended_at"] is None
```

- [ ] **Step 8: Run test — should pass without code changes**

Run: `uv run pytest tests/test_codex_session_autoclose.py::test_close_stale_sessions_skips_claude_sessions -v`
Expected: PASS

- [ ] **Step 9: Write test — does NOT close already-closed sessions**

```python
def test_close_stale_sessions_skips_already_closed(ec_repo, ec_db):
    project = get_project(str(ec_repo))
    s = create_session(ec_db, project["id"], session_type="codex", session_id="codex-closed-1")
    two_hours_ago = _iso(datetime.now(timezone.utc) - timedelta(hours=2))
    ec_db.execute(
        "UPDATE sessions SET last_activity_at = ?, ended_at = ? WHERE id = ?",
        (two_hours_ago, two_hours_ago, s["id"]),
    )
    ec_db.commit()

    closed = close_stale_sessions(ec_db, idle_minutes=60)

    assert closed == 0
```

- [ ] **Step 10: Run test — should pass**

Run: `uv run pytest tests/test_codex_session_autoclose.py::test_close_stale_sessions_skips_already_closed -v`
Expected: PASS

- [ ] **Step 11: Write test — optimistic concurrency guard**

This test exercises the UPDATE's `WHERE last_activity_at = ?` guard by monkeypatching the function to inject a concurrent modification between SELECT and UPDATE.

```python
def test_close_stale_sessions_optimistic_concurrency(ec_repo, ec_db, monkeypatch):
    """If last_activity_at changes between SELECT and UPDATE, row is skipped."""
    from unittest.mock import patch

    project = get_project(str(ec_repo))
    s = create_session(ec_db, project["id"], session_type="codex", session_id="codex-race-1")
    two_hours_ago = _iso(datetime.now(timezone.utc) - timedelta(hours=2))
    ec_db.execute(
        "UPDATE sessions SET last_activity_at = ? WHERE id = ?",
        (two_hours_ago, s["id"]),
    )
    ec_db.commit()

    original_execute = ec_db.execute
    injected = False

    def intercepting_execute(sql, params=None):
        nonlocal injected
        # After the SELECT but before the first UPDATE, change last_activity_at
        if not injected and "UPDATE sessions SET ended_at" in sql:
            injected = True
            fresh = _iso(datetime.now(timezone.utc))
            original_execute(
                "UPDATE sessions SET last_activity_at = ? WHERE id = ?",
                (fresh, s["id"]),
            )
        return original_execute(sql, params) if params else original_execute(sql)

    ec_db.execute = intercepting_execute

    closed = close_stale_sessions(ec_db, idle_minutes=60)

    # The UPDATE's WHERE clause requires last_activity_at = <old_value>,
    # but the concurrent update changed it, so rowcount = 0
    assert closed == 0
    # Session should still be open
    row = original_execute("SELECT ended_at FROM sessions WHERE id = ?", (s["id"],)).fetchone()
    assert row["ended_at"] is None
```

- [ ] **Step 12: Run test — should pass**

Run: `uv run pytest tests/test_codex_session_autoclose.py::test_close_stale_sessions_optimistic_concurrency -v`
Expected: PASS

- [ ] **Step 13: Add config default**

In `src/entirecontext/core/config.py`, add to `DEFAULT_CONFIG["capture"]`:

```python
"codex_session_idle_minutes": 60,
```

- [ ] **Step 14: Write test — auto-close triggered from codex ingest**

```python
def test_codex_ingest_auto_closes_stale_sessions(ec_repo, ec_db):
    """ingest_codex_notify_event closes stale codex sessions as a side effect."""
    import json
    from pathlib import Path

    from entirecontext.core.project import get_project
    from entirecontext.hooks.codex_ingest import _save_state, ingest_codex_notify_event

    project = get_project(str(ec_repo))
    # Create a stale codex session
    s = create_session(ec_db, project["id"], session_type="codex", session_id="codex-old-1")
    two_hours_ago = _iso(datetime.now(timezone.utc) - timedelta(hours=2))
    ec_db.execute(
        "UPDATE sessions SET last_activity_at = ? WHERE id = ?",
        (two_hours_ago, s["id"]),
    )
    ec_db.commit()
    ec_db.close()

    # Enable codex notify
    _save_state(str(ec_repo), {})

    # Write codex session file
    codex_home = ec_repo.parent / "codex-home"
    session_dir = codex_home / "sessions" / "2026" / "06" / "07"
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / "rollout-2026-06-07T00-00-00-new-session.jsonl"
    records = [
        {"timestamp": "2026-06-07T00:00:00Z", "type": "session_meta",
         "payload": {"id": "codex-new-1", "timestamp": "2026-06-07T00:00:00Z", "cwd": str(ec_repo)}},
        {"timestamp": "2026-06-07T00:00:01Z", "type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "hello"}]}},
        {"timestamp": "2026-06-07T00:00:02Z", "type": "response_item",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "hi"}]}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    ingest_codex_notify_event(
        {"thread_id": "codex-new-1", "cwd": str(ec_repo), "codex_home": str(codex_home)},
        payload_text="{}",
    )

    from entirecontext.db import get_db
    conn = get_db(str(ec_repo))
    row = conn.execute("SELECT ended_at FROM sessions WHERE id = ?", (s["id"],)).fetchone()
    conn.close()
    assert row["ended_at"] is not None
```

- [ ] **Step 15: Integrate auto-close into `codex_ingest.py`**

In `src/entirecontext/hooks/codex_ingest.py`, add after the `conn.execute("UPDATE sessions SET total_turns...")` block (line 334), before `finally`:

```python
        try:
            from ..core.config import load_config
            config = load_config(repo_path)
            idle_minutes = config.get("capture", {}).get("codex_session_idle_minutes", 60)
            from ..core.session import close_stale_sessions
            close_stale_sessions(conn, idle_minutes=idle_minutes, session_type="codex")
        except Exception:
            pass
```

- [ ] **Step 16: Run all Task 1 tests**

Run: `uv run pytest tests/test_codex_session_autoclose.py -v`
Expected: ALL PASS

- [ ] **Step 17: Run existing codex ingest tests for regression**

Run: `uv run pytest tests/test_codex_ingest.py -v`
Expected: ALL PASS

- [ ] **Step 18: Commit**

```bash
git add src/entirecontext/core/session.py src/entirecontext/core/config.py \
  src/entirecontext/hooks/codex_ingest.py tests/test_codex_session_autoclose.py
git commit -m "feat(session): auto-close stale codex sessions on ingest

Codex sessions created by codex_ingest.py had no termination logic, leaving
374+ sessions with ended_at IS NULL. Add close_stale_sessions() that sets
ended_at = last_activity_at for codex sessions idle > N minutes (default 60).

Called automatically during codex notify ingestion. Uses optimistic
concurrency (re-check ended_at IS NULL AND last_activity_at = ?) to
avoid clobbering resumed sessions."
```

---

### Task 2: Dashboard Retrieval Rate Normalization

**Files:**
- Modify: `src/entirecontext/core/dashboard.py:173-178,199`
- Modify: `tests/test_dashboard.py`

**Design decision:** Change `retrieval_assisted_session_rate` to use ended sessions for BOTH numerator and denominator. Currently the numerator counts `COUNT(DISTINCT session_id) FROM retrieval_events` (no `ended_at` filter) and the denominator is `sessions_total` (also no filter). Both sides are inconsistent with `checkpoint_coverage_rate` which uses `ended_at IS NOT NULL`.

Rationale:
- `checkpoint_coverage_rate` already filters on `ended_at IS NOT NULL` (lines 213, 240)
- Active sessions haven't completed their lifecycle — including them in either side is misleading
- After Task 1, codex sessions gain `ended_at` and enter both sides correctly
- Both sides must share the same population — a retrieval event in an active session must NOT count in the numerator when the denominator excludes active sessions, or the rate can exceed 1.0

**Expected metric change:**
- Before: `59 / 535 = 0.110` (both sides unfiltered)
- After (all sessions ended): ended sessions with retrieval / ended sessions ≈ similar rate
- The fix is about **coherence**, not inflating the score

- [ ] **Step 1: Write the failing test — rate excludes active sessions from BOTH sides**

```python
# In tests/test_dashboard.py, add these tests

def test_retrieval_rate_excludes_active_sessions(ec_repo, ec_db):
    """retrieval_assisted_session_rate uses ended sessions for both numerator and denominator."""
    from entirecontext.core.project import get_project
    from entirecontext.core.session import create_session

    project = get_project(str(ec_repo))

    # 2 ended sessions, 1 active
    s1 = create_session(ec_db, project["id"], session_id="rate-s1")
    s2 = create_session(ec_db, project["id"], session_id="rate-s2")
    s3 = create_session(ec_db, project["id"], session_id="rate-s3")
    ec_db.execute("UPDATE sessions SET ended_at = datetime('now') WHERE id = ?", (s1["id"],))
    ec_db.execute("UPDATE sessions SET ended_at = datetime('now') WHERE id = ?", (s2["id"],))
    ec_db.commit()

    # 1 retrieval event in ended session s1
    from uuid import uuid4
    ec_db.execute(
        "INSERT INTO retrieval_events (id, session_id, query, source, created_at)"
        " VALUES (?, ?, 'test', 'hook', datetime('now'))",
        (str(uuid4()), s1["id"]),
    )
    ec_db.commit()

    stats = get_dashboard_stats(ec_db)

    # rate = 1 ended session with retrieval / 2 ended sessions = 0.5
    # NOT 1/3 (which would include the active session in denominator)
    assert stats["retrieval"]["assisted_session_rate"] == 0.5


def test_retrieval_rate_ignores_active_session_retrieval(ec_repo, ec_db):
    """Retrieval event in an active session must NOT inflate the numerator."""
    from entirecontext.core.project import get_project
    from entirecontext.core.session import create_session

    project = get_project(str(ec_repo))

    # 1 ended session (no retrieval), 1 active session (with retrieval)
    s1 = create_session(ec_db, project["id"], session_id="rate-ended-1")
    s2 = create_session(ec_db, project["id"], session_id="rate-active-1")
    ec_db.execute("UPDATE sessions SET ended_at = datetime('now') WHERE id = ?", (s1["id"],))
    ec_db.commit()

    # Retrieval event only in the ACTIVE session
    from uuid import uuid4
    ec_db.execute(
        "INSERT INTO retrieval_events (id, session_id, query, source, created_at)"
        " VALUES (?, ?, 'test', 'hook', datetime('now'))",
        (str(uuid4()), s2["id"]),
    )
    ec_db.commit()

    stats = get_dashboard_stats(ec_db)

    # rate = 0 ended sessions with retrieval / 1 ended session = 0.0
    # The active session's retrieval event must NOT count
    assert stats["retrieval"]["assisted_session_rate"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dashboard.py::test_retrieval_rate_excludes_active_sessions tests/test_dashboard.py::test_retrieval_rate_ignores_active_session_retrieval -v`
Expected: FAIL — both tests fail because current formula uses unfiltered populations

- [ ] **Step 3: Fix BOTH numerator and denominator in `dashboard.py`**

In `src/entirecontext/core/dashboard.py`, change the numerator query (lines 173-178):

Old:
```python
    retrieval_sessions_row = conn.execute(
        "SELECT COUNT(DISTINCT session_id) AS total FROM retrieval_events"
        + (" WHERE created_at >= ?" if since is not None else ""),
        since_params,
    ).fetchone()
```

New:
```python
    retrieval_sessions_row = conn.execute(
        "SELECT COUNT(DISTINCT re.session_id) AS total FROM retrieval_events re"
        " JOIN sessions s ON re.session_id = s.id"
        " WHERE s.ended_at IS NOT NULL"
        + (" AND re.created_at >= ?" if since is not None else ""),
        since_params,
    ).fetchone()
```

And change the denominator (line 199):

Old:
```python
    retrieval_assisted_session_rate = retrieval_sessions_total / sessions_total if sessions_total > 0 else 0.0
```

New:
```python
    retrieval_assisted_session_rate = retrieval_sessions_total / sessions_ended if sessions_ended > 0 else 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dashboard.py::test_retrieval_rate_excludes_active_sessions tests/test_dashboard.py::test_retrieval_rate_ignores_active_session_retrieval -v`
Expected: PASS

- [ ] **Step 5: Run ALL dashboard tests for regression**

Run: `uv run pytest tests/test_dashboard.py -v`
Expected: ALL PASS (existing tests may need adjustment — see step 6)

- [ ] **Step 6: Fix any failing existing tests**

If existing tests fail due to the denominator change, update their expected values. The `_seed_db` helper creates 1 ended session (`dash-s2`) and 1 active session (`dash-s1`). Check each failing test and update expected values to match the new formula (ended sessions only, both sides).

- [ ] **Step 7: Run full dashboard test suite**

Run: `uv run pytest tests/test_dashboard.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add src/entirecontext/core/dashboard.py tests/test_dashboard.py
git commit -m "fix(dashboard): normalize retrieval rate to ended-session basis

Both numerator (retrieval_sessions_total) and denominator were using
unfiltered session counts, while checkpoint_coverage_rate filters on
ended_at IS NOT NULL. This caused: (a) 383 codex sessions with
ended_at=NULL inflating the denominator, (b) retrieval events in
active sessions counting in the numerator but not the denominator,
allowing rates >1.0 in edge cases. Both sides now join sessions and
filter on ended_at IS NOT NULL."
```

---

### Task 3: Verdict Accuracy Baseline

**Files:**
- Modify: `src/entirecontext/core/auto_assess.py`
- Modify: `src/entirecontext/cli/checkpoint_cmds.py`
- Create: `tests/test_verdict_accuracy.py`

**Data source:** `enrich_assessment()` (auto_assess.py:168-171) records `agree`/`disagree` feedback when LLM confirms or revises the rule verdict. Disagreement rate on rule-based assessments IS the false-positive baseline. No new labeling process needed.

**Known correction:** The v0.8.0 retro claimed "chore(deps): bump → expand" was a false positive. Verified against code: `compute_rule_verdict` only matches `^feat` (expand) and `^revert` (narrow). `chore(deps)` returns `neutral`. The retro's example was inaccurate — the actual false-positive cases need to be identified from enrichment feedback data.

- [ ] **Step 1: Write the failing test — `compute_verdict_accuracy` returns structured report**

```python
# tests/test_verdict_accuracy.py
from __future__ import annotations

from entirecontext.core.auto_assess import compute_verdict_accuracy
from entirecontext.core.futures import create_assessment


def test_compute_verdict_accuracy_empty(ec_repo, ec_db):
    result = compute_verdict_accuracy(ec_db)

    assert result["total_rule_based"] == 0
    assert result["total_enriched"] == 0
    assert result["agreement_rate"] is None
    assert result["per_verdict"] == {}


def test_compute_verdict_accuracy_with_feedback(ec_repo, ec_db):
    # 2 rule-based assessments enriched: 1 agree, 1 disagree
    ec_db.execute(
        "INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch, created_at)"
        " VALUES ('ckp-va-1', 'sess-va', 'abc', 'main', datetime('now'))"
    )
    ec_db.execute(
        "INSERT INTO assessments (id, checkpoint_id, verdict, model_name, feedback, impact_summary, created_at)"
        " VALUES ('asmt-va-1', 'ckp-va-1', 'expand', 'claude-cli', 'agree', 'feat: add X', datetime('now'))"
    )
    ec_db.execute(
        "INSERT INTO assessments (id, checkpoint_id, verdict, model_name, feedback, impact_summary, created_at)"
        " VALUES ('asmt-va-2', 'ckp-va-1', 'neutral', 'claude-cli', 'disagree', 'chore: bump', datetime('now'))"
    )
    # 1 pure rule-based (no enrichment yet)
    ec_db.execute(
        "INSERT INTO assessments (id, checkpoint_id, verdict, model_name, impact_summary, created_at)"
        " VALUES ('asmt-va-3', 'ckp-va-1', 'expand', 'rule-based', 'feat: login', datetime('now'))"
    )
    ec_db.commit()

    result = compute_verdict_accuracy(ec_db)

    assert result["total_rule_based"] == 1
    assert result["total_enriched"] == 2
    assert result["agreement_rate"] == 0.5
    assert result["per_verdict"]["expand"]["agree"] == 1
    assert result["per_verdict"]["neutral"]["disagree"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_verdict_accuracy.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_verdict_accuracy'`

- [ ] **Step 3: Implement `compute_verdict_accuracy` in `auto_assess.py`**

Add to `src/entirecontext/core/auto_assess.py`:

```python
def compute_verdict_accuracy(conn: sqlite3.Connection) -> dict:
    """Compute verdict accuracy from enrichment feedback data.

    Returns structured report with agreement rate and per-verdict breakdown.
    """
    rule_count = conn.execute(
        "SELECT COUNT(*) FROM assessments WHERE model_name = 'rule-based'"
    ).fetchone()[0]

    enriched_rows = conn.execute(
        "SELECT verdict, feedback FROM assessments"
        " WHERE model_name IS NOT NULL AND model_name != 'rule-based'"
        " AND feedback IS NOT NULL"
    ).fetchall()

    if not enriched_rows:
        return {
            "total_rule_based": rule_count,
            "total_enriched": 0,
            "agreement_rate": None,
            "per_verdict": {},
        }

    per_verdict: dict[str, dict[str, int]] = {}
    agree_count = 0
    for row in enriched_rows:
        verdict = row["verdict"]
        feedback = row["feedback"]
        if verdict not in per_verdict:
            per_verdict[verdict] = {"agree": 0, "disagree": 0}
        if feedback == "agree":
            per_verdict[verdict]["agree"] += 1
            agree_count += 1
        elif feedback == "disagree":
            per_verdict[verdict]["disagree"] += 1

    total = len(enriched_rows)
    return {
        "total_rule_based": rule_count,
        "total_enriched": total,
        "agreement_rate": agree_count / total if total > 0 else None,
        "per_verdict": per_verdict,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_verdict_accuracy.py -v`
Expected: PASS

- [ ] **Step 5: Write test — disagree feedback with reason is counted correctly**

Note: `add_feedback()` validates that `feedback` is either `"agree"` or `"disagree"` only (see `VALID_FEEDBACKS` in futures.py:13). The detail string like `"auto:revised:neutral->expand"` goes to `feedback_reason`, not `feedback`. So the `compute_verdict_accuracy` function only needs to check `feedback = "agree"` or `feedback = "disagree"`.

```python
def test_compute_verdict_accuracy_disagree_with_reason(ec_repo, ec_db):
    ec_db.execute(
        "INSERT INTO checkpoints (id, session_id, git_commit_hash, git_branch, created_at)"
        " VALUES ('ckp-va-rev', 'sess-va-rev', 'def', 'main', datetime('now'))"
    )
    ec_db.execute(
        "INSERT INTO assessments (id, checkpoint_id, verdict, model_name, feedback, feedback_reason, impact_summary, created_at)"
        " VALUES ('asmt-rev-1', 'ckp-va-rev', 'expand', 'claude-cli', 'disagree', 'auto:revised:neutral->expand', 'revised', datetime('now'))"
    )
    ec_db.commit()

    result = compute_verdict_accuracy(ec_db)

    assert result["per_verdict"]["expand"]["disagree"] == 1
    assert result["agreement_rate"] == 0.0
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_verdict_accuracy.py::test_compute_verdict_accuracy_disagree_with_reason -v`
Expected: PASS

- [ ] **Step 7: Add CLI command `ec assess accuracy`**

In `src/entirecontext/cli/checkpoint_cmds.py`, add near the end (before `register()`):

```python
@checkpoint_app.command("assess-accuracy")
def assess_accuracy():
    """Show verdict accuracy baseline from enrichment feedback."""
    from ..core.auto_assess import compute_verdict_accuracy
    from ..core.project import find_git_root, get_project
    from ..db import get_db

    repo_path = find_git_root()
    if not repo_path:
        console.print("[red]Not in a git repository.[/red]")
        raise typer.Exit(1)

    project = get_project(repo_path)
    if not project:
        console.print("[yellow]Not initialized. Run 'ec init'.[/yellow]")
        raise typer.Exit(1)

    conn = get_db(repo_path)
    try:
        result = compute_verdict_accuracy(conn)
    finally:
        conn.close()

    console.print(f"\n[bold]Verdict Accuracy Baseline[/bold]")
    console.print(f"  Rule-based assessments (pending enrichment): {result['total_rule_based']}")
    console.print(f"  Enriched assessments (with feedback): {result['total_enriched']}")

    if result["agreement_rate"] is not None:
        rate_pct = result["agreement_rate"] * 100
        console.print(f"  Agreement rate: {rate_pct:.1f}%")
    else:
        console.print("  Agreement rate: [dim]no data[/dim]")

    if result["per_verdict"]:
        table = Table(title="Per-Verdict Breakdown")
        table.add_column("Verdict")
        table.add_column("Agree", justify="right")
        table.add_column("Disagree", justify="right")
        for verdict, counts in sorted(result["per_verdict"].items()):
            table.add_row(verdict, str(counts["agree"]), str(counts["disagree"]))
        console.print(table)
```

Also add the missing import at the top of the file if not present:
```python
from rich.table import Table
```

- [ ] **Step 8: Write CLI test**

```python
# Add to tests/test_verdict_accuracy.py

from typer.testing import CliRunner

from entirecontext.cli import app

runner = CliRunner()


def test_assess_accuracy_cli(ec_repo, ec_db, monkeypatch):
    monkeypatch.chdir(ec_repo)
    result = runner.invoke(app, ["checkpoint", "assess-accuracy"])
    assert result.exit_code == 0
    assert "Verdict Accuracy Baseline" in result.output
```

- [ ] **Step 9: Run CLI test**

Run: `uv run pytest tests/test_verdict_accuracy.py::test_assess_accuracy_cli -v`
Expected: PASS

- [ ] **Step 10: Run all Task 3 tests**

Run: `uv run pytest tests/test_verdict_accuracy.py -v`
Expected: ALL PASS

- [ ] **Step 11: Run existing auto_assess tests for regression**

Run: `uv run pytest tests/test_auto_assess.py -v`
Expected: ALL PASS

- [ ] **Step 12: Commit**

```bash
git add src/entirecontext/core/auto_assess.py src/entirecontext/cli/checkpoint_cmds.py \
  tests/test_verdict_accuracy.py
git commit -m "feat(assess): add verdict accuracy baseline reporting

compute_verdict_accuracy() aggregates agree/disagree feedback from LLM
enrichment to measure rule-based verdict accuracy. CLI: ec checkpoint
assess-accuracy. Uses existing enrichment feedback data — no new
labeling process.

Current data: 10 enriched (all agree), 8 rule-based pending. Baseline
will grow as auto-enrichment processes more assessments."
```

---

### Task 4: Integration Verification + Docs

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md`

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -x -q`
Expected: ALL PASS, zero failures

- [ ] **Step 2: Lint check**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: Clean

- [ ] **Step 3: Verify dashboard after auto-close (manual)**

Run: `uv run ec session backfill-ended-at --max-age-hours 1 --apply` first to close existing stale sessions, then:

Run: `uv run ec dashboard`
Expected: maturity score reflects corrected denominators

- [ ] **Step 4: Verify verdict accuracy (manual)**

Run: `uv run ec checkpoint assess-accuracy`
Expected: shows current accuracy data

- [ ] **Step 5: Update CHANGELOG.md**

Add under `## [Unreleased]` (or create `## [0.8.1]` section):

```markdown
## [0.8.1] - Measurement Accuracy

### Fixed
- Codex sessions auto-closed on notify ingestion (stale > 60min idle)
- `retrieval_assisted_session_rate` denominator changed from all sessions to ended sessions only, consistent with `checkpoint_coverage_rate`

### Added
- `ec checkpoint assess-accuracy` — verdict accuracy baseline from enrichment feedback
- `close_stale_sessions()` in `core/session.py` — reusable auto-close with optimistic concurrency
- Config: `[capture] codex_session_idle_minutes` (default 60)
```

- [ ] **Step 6: Update ROADMAP.md**

Mark v0.8.1 items as completed:

```markdown
## v0.8.1 — Measurement Accuracy (Shipped YYYY-MM-DD)

- [x] **Codex session auto-close** — ...
- [x] **Maturity calculation normalization** — ...
- [x] **Verdict accuracy baseline** — ...
```

- [ ] **Step 7: Commit docs**

```bash
git add CHANGELOG.md ROADMAP.md
git commit -m "docs: v0.8.1 changelog and roadmap updates"
```

---

## Unresolved Questions

1. **42 codex sessions have retrieval events — how?** `codex_ingest.py` doesn't create retrieval events. These may originate from PDI hooks that fire in the same repo and coincidentally use codex session IDs, or from manual `ec search` commands during codex sessions. Understanding the source would clarify whether codex sessions should contribute to `retrieval_sessions_total` or be filtered out entirely. **Impact on this plan:** low — the denominator fix (ended sessions) is correct regardless.

2. **Enrichment sample size (n=10) too small for statistical confidence.** The accuracy baseline infrastructure is correct, but the number will only become meaningful after more assessments are enriched. **Mitigation:** v0.9.0's verdict tuning should gate on n≥30 before making mapping changes.
