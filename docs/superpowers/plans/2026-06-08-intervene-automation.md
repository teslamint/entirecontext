# v0.9.0 Intervene Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate the weakest maturity dimension (intervene=5) so the `capture→distill→retrieve→intervene` loop can close without manual `ec_context_apply`. Maturity ≥75 is a measurement outcome, not a code target — leave unchecked (per v0.8.0 lesson).

**Architecture:** SessionEnd hook detects file-overlap between surfaced decisions and session-modified files, auto-records `context_application` + `accepted` outcome. Both writes are atomic (single transaction). A backfill command bootstraps historical data. Measurement fixes (search_to_selection_rate DISTINCT) and Signal C activation ship alongside.

**Tech Stack:** Python 3.12+, SQLite (WAL, autocommit), Typer CLI, pytest

**Maturity gap analysis:**

| Dimension | Current | Max | Gap |
|-----------|---------|-----|-----|
| capture | 22 | 30 | 8 |
| distill | 25 | 25 | 0 |
| retrieve | 17 | 25 | 8 |
| intervene | 5 | 20 | 15 |
| **Total** | **69** | **100** | — |

Auto-apply targets `applied_context_rate >= 0.1` (currently 0.011, threshold +8 pts). Ceiling query: 154 candidate (session, decision) pairs vs 48 needed — feasible from historical data, but actual overlap filtering will reduce it.

`lesson_reuse_rate` has no automated path in v0.9.0 (auto-apply creates `source_type='decision'`, not assessment/lesson). BUT not blocking: intervene=13 (5+8) → total 77 ≥ 75 Closed Loop without lesson reuse.

Verdict mapping tuning deferred: `compute_verdict_accuracy()` counts 0 new-format enrichments (10 old gpt-4o-mini exist but use free-text reason, excluded by `LIKE 'auto:%'` filter). Running `ec futures enrich-backlog` on 8 pending rule-based assessments would produce new-format data, but still under n≥30 gate.

**NOTE on outcome type:** File-overlap is weaker evidence than explicit `ec_context_apply`. The project boundary ("outcome attribution, not behavior judgment") accepts this tradeoff — the agent modified files that a surfaced decision references. False positives are possible (agent may have contradicted the decision). This is a conscious design choice: activating the intervene dimension with imperfect signal is preferable to leaving it at zero with no signal.

**NOTE on Signal C model load:** Flipping `auto_embed=True` means `create_decision()` calls `generate_embeddings(decisions_only=True)` on every decision creation, which loads a SentenceTransformer model. `create_decision` is NOT on any hook hot path — it's called from CLI/MCP explicit commands and candidate confirmation. Acceptable for v0.9.0; 2-pass async batching deferred.

**Callers of modified functions:**

| Function | Callers |
|----------|---------|
| `dashboard.compute_dashboard()` | `cli/dashboard_cmds.py`, `mcp/tools/dashboard.py`, `cli/repo_cmds.py` |
| `session_lifecycle.on_session_end()` | `hooks/handler.py` (SessionEnd dispatch) |
| `session.close_stale_sessions()` | `hooks/codex_ingest.py` (after ingest) |
| `telemetry.record_context_application()` | `mcp/tools/session.py`, `cli/context_cmds.py` |
| `decisions.record_decision_outcome()` | `mcp/tools/decision.py`, `cli/decision_cmds.py`, `hooks/session_lifecycle.py` |
| `config.DEFAULT_CONFIG` | `config.load_config()` → all hook/core callers |

**Invariants:**

1. `_rate` metrics in dashboard MUST be in [0, 1] range
2. Auto-apply MUST run BEFORE ignored inference — applied decisions must not be double-marked as ignored
3. `record_decision_outcome` requires a valid `decision_id` that exists in the decisions table
4. `record_context_application` requires valid `selection_id` when provided, and `application_type` in `VALID_APPLICATION_TYPES`
5. Codex sessions never call `on_session_end()` — only Claude Code sessions do. Codex stale cleanup uses idle-timeout heuristic triggered separately.
6. `generate_embeddings()` raises `ImportError` when `sentence-transformers` is not installed — `create_decision()` wraps this in bare except

**Prior retro carry-forward coverage:**

| v0.8.1 retro item | Task |
|--------------------|------|
| search_to_selection_rate DISTINCT fix | A |
| Dashboard _rate metrics audit | A (guard test) |
| SessionEnd codex stale cleanup trigger expansion | B |
| Duplicate notify regression test | D |
| Decision record enforcement mechanism | Deferred (needs hook-based gate design) |
| SessionEnd auto apply inference | B + C |
| Reopen → sessions_ended non-monotonic | Deferred (measurement study, not code) |

---

### Task A: search_to_selection_rate DISTINCT Fix

**Files:**
- Modify: `src/entirecontext/core/dashboard.py:166-204`
- Modify: `tests/test_dashboard.py`

- [ ] **Step 1: Write the failing test**

Create a test that seeds multiple selections per event and asserts the rate is a fraction in [0,1].

```python
# tests/test_dashboard.py — add to existing file

def test_search_to_selection_rate_distinct_events(ec_db, ec_repo):
    """search_to_selection_rate must be DISTINCT events with >=1 selection / total events."""
    conn = ec_db
    from entirecontext.core.session import create_session
    from entirecontext.core.turn import create_turn
    from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection

    project = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
    session = create_session(conn, project_id=project["id"])
    turn = create_turn(conn, session_id=session["id"], turn_number=1, user_message="test")

    # Event 1: 3 selections (same event)
    ev1 = record_retrieval_event(conn, source="hook", search_type="session_start", target="decisions",
                                  query="test", result_count=3, latency_ms=10,
                                  session_id=session["id"], turn_id=turn["id"])
    for i in range(3):
        record_retrieval_selection(conn, ev1["id"], "decision", f"d{i}",
                                    session_id=session["id"], turn_id=turn["id"])

    # Event 2: 0 selections
    record_retrieval_event(conn, source="hook", search_type="user_prompt", target="decisions",
                           query="test2", result_count=0, latency_ms=5,
                           session_id=session["id"], turn_id=turn["id"])

    # Mark session ended
    conn.execute("UPDATE sessions SET ended_at = datetime('now') WHERE id = ?", (session["id"],))

    from entirecontext.core.dashboard import compute_dashboard
    result = compute_dashboard(conn)
    rate = result["telemetry"]["rates"]["search_to_selection_rate"]

    # 1 event with selections / 2 total events = 0.5
    assert rate == 0.5, f"Expected 0.5, got {rate}"
    assert 0.0 <= rate <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dashboard.py::test_search_to_selection_rate_distinct_events -v`
Expected: FAIL — current formula returns 3/2 = 1.5

- [ ] **Step 3: Fix dashboard.py — replace total selections / total events with DISTINCT events**

```python
# src/entirecontext/core/dashboard.py — replace lines 182-204

    retrieval_selections_total = (
        conn.execute(
            f"SELECT COUNT(*) AS total FROM retrieval_selections{since_clause_ca}",
            since_params,
        ).fetchone()["total"]
        or 0
    )

    events_with_selection = (
        conn.execute(
            "SELECT COUNT(DISTINCT re.id) AS total"
            " FROM retrieval_events re"
            " JOIN retrieval_selections rs ON rs.retrieval_event_id = re.id"
            + (f" WHERE re.created_at >= ?" if since is not None else ""),
            since_params,
        ).fetchone()["total"]
        or 0
    )

    # ... keep existing applications_row query ...

    retrieval_assisted_session_rate = retrieval_sessions_total / sessions_ended if sessions_ended > 0 else 0.0
    search_to_selection_rate = (
        events_with_selection / retrieval_events_total if retrieval_events_total > 0 else 0.0
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dashboard.py::test_search_to_selection_rate_distinct_events -v`
Expected: PASS

- [ ] **Step 5: Add _rate range guard test**

```python
def test_all_rate_metrics_in_unit_range(ec_db, ec_repo):
    """All _rate metrics must be in [0, 1] range."""
    conn = ec_db
    from entirecontext.core.session import create_session
    from entirecontext.core.turn import create_turn
    from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection

    project = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
    session = create_session(conn, project_id=project["id"])
    turn = create_turn(conn, session_id=session["id"], turn_number=1, user_message="test")
    ev = record_retrieval_event(conn, source="hook", search_type="session_start", target="decisions",
                                 query="q", result_count=10, latency_ms=10,
                                 session_id=session["id"], turn_id=turn["id"])
    for i in range(10):
        record_retrieval_selection(conn, ev["id"], "decision", f"d{i}",
                                    session_id=session["id"], turn_id=turn["id"])
    conn.execute("UPDATE sessions SET ended_at = datetime('now') WHERE id = ?", (session["id"],))

    from entirecontext.core.dashboard import compute_dashboard
    result = compute_dashboard(conn)
    rate_keys = [
        "retrieval_assisted_session_rate",
        "search_to_selection_rate",
        "applied_context_rate",
        "lesson_reuse_rate",
        "checkpoint_anchored_assessment_rate",
    ]
    for key in rate_keys:
        val = result["telemetry"]["rates"][key]
        assert 0.0 <= val <= 1.0, f"{key} = {val} is outside [0, 1]"
```

- [ ] **Step 6: Run full test suite for dashboard**

Run: `uv run pytest tests/test_dashboard.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/entirecontext/core/dashboard.py tests/test_dashboard.py
git commit -m "fix(dashboard): use DISTINCT event count for search_to_selection_rate

The metric was computed as total_selections / total_events (541/191 = 2.83),
which exceeds 1.0. Correct formula: DISTINCT events with ≥1 selection /
total events = [0, 1] fraction. Maturity scoring threshold (≥0.25) happens
to be unchanged but the semantic bug is fixed.

Adds guard test asserting all _rate metrics stay in [0, 1] range."
```

---

### Task B: SessionEnd Auto-Apply Inference

**Files:**
- Create: `src/entirecontext/core/auto_apply.py`
- Modify: `src/entirecontext/hooks/session_lifecycle.py:281-290`
- Modify: `src/entirecontext/core/config.py:73-95`
- Create: `tests/test_auto_apply.py`

**Design notes:**
- Runs on SessionEnd, BEFORE `_maybe_infer_ignored_decisions` (ordering invariant #2)
- For each decision surfaced via PDI in this session, check if session-modified files overlap with `decision_files`
- If overlap found: record `context_application` (type `decision_change`) + `accepted` outcome
- The `accepted` outcome prevents ignored inference from double-marking
- Also adds `close_stale_sessions` call on SessionEnd (codex stale cleanup trigger expansion)

- [ ] **Step 1: Write the core inference function test**

```python
# tests/test_auto_apply.py

import pytest

from entirecontext.core.session import create_session
from entirecontext.core.turn import create_turn
from entirecontext.core.decisions import create_decision, link_decision_to_file, record_decision_outcome
from entirecontext.core.telemetry import record_retrieval_event, record_retrieval_selection


@pytest.fixture
def auto_apply_setup(ec_db, ec_repo):
    """Seed: 1 session, 1 turn with files_touched, 1 decision linked to overlapping file, 1 surfaced selection."""
    conn = ec_db
    project = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
    project_id = project["id"]

    session = create_session(conn, project_id=project_id, session_type="claude")
    conn.execute("UPDATE sessions SET ended_at = datetime('now') WHERE id = ?", (session["id"],))

    turn = create_turn(conn, session_id=session["id"], turn_number=1, user_message="implement feature",
                       files_touched='["src/core/foo.py", "src/core/bar.py"]')

    decision = create_decision(conn, title="Use foo pattern", rationale="Because reasons")
    link_decision_to_file(conn, decision["id"], "src/core/foo.py")

    ev = record_retrieval_event(conn, source="hook", search_type="user_prompt", target="decisions",
                                 query="test", result_count=1, latency_ms=10,
                                 session_id=session["id"], turn_id=turn["id"])
    sel = record_retrieval_selection(conn, ev["id"], "decision", decision["id"],
                                      session_id=session["id"], turn_id=turn["id"])

    return {
        "conn": conn,
        "session_id": session["id"],
        "turn_id": turn["id"],
        "decision_id": decision["id"],
        "event_id": ev["id"],
        "selection_id": sel["id"],
    }


def test_infer_applied_creates_application_and_outcome(auto_apply_setup):
    s = auto_apply_setup
    from entirecontext.core.auto_apply import infer_applied_decisions

    result = infer_applied_decisions(s["conn"], s["session_id"])

    assert result["applied_count"] == 1
    assert result["applied_decisions"][0]["decision_id"] == s["decision_id"]

    app = s["conn"].execute(
        "SELECT * FROM context_applications WHERE session_id = ?", (s["session_id"],)
    ).fetchone()
    assert app is not None
    assert app["application_type"] == "decision_change"
    assert app["source_type"] == "decision"
    assert app["source_id"] == s["decision_id"]
    assert app["retrieval_selection_id"] == s["selection_id"]

    outcome = s["conn"].execute(
        "SELECT * FROM decision_outcomes WHERE decision_id = ? AND session_id = ?",
        (s["decision_id"], s["session_id"]),
    ).fetchone()
    assert outcome is not None
    assert outcome["outcome_type"] == "accepted"
    assert "auto: session_end file_overlap" in outcome["note"]


def test_infer_applied_atomicity_both_or_neither(auto_apply_setup, monkeypatch):
    """If outcome write fails, application must also be rolled back."""
    s = auto_apply_setup
    from entirecontext.core import auto_apply as mod

    original_record = mod.record_decision_outcome
    def failing_record(*args, **kwargs):
        raise RuntimeError("simulated outcome failure")
    monkeypatch.setattr(mod, "record_decision_outcome", failing_record)

    from entirecontext.core.auto_apply import infer_applied_decisions
    result = infer_applied_decisions(s["conn"], s["session_id"])
    assert result["applied_count"] == 0

    apps = s["conn"].execute(
        "SELECT COUNT(*) FROM context_applications WHERE session_id = ?", (s["session_id"],)
    ).fetchone()[0]
    assert apps == 0, "Application must not persist when outcome write fails"


def test_infer_applied_skips_existing_outcome(auto_apply_setup):
    s = auto_apply_setup
    record_decision_outcome(s["conn"], s["decision_id"], outcome_type="ignored",
                            session_id=s["session_id"], note="manual")

    from entirecontext.core.auto_apply import infer_applied_decisions
    result = infer_applied_decisions(s["conn"], s["session_id"])
    assert result["applied_count"] == 0


def test_infer_applied_skips_no_file_overlap(auto_apply_setup):
    s = auto_apply_setup
    s["conn"].execute("DELETE FROM decision_files WHERE decision_id = ?", (s["decision_id"],))
    link_decision_to_file(s["conn"], s["decision_id"], "unrelated/path.py")

    from entirecontext.core.auto_apply import infer_applied_decisions
    result = infer_applied_decisions(s["conn"], s["session_id"])
    assert result["applied_count"] == 0


def test_infer_applied_deduplicates_across_turns(auto_apply_setup):
    s = auto_apply_setup
    turn2 = create_turn(s["conn"], session_id=s["session_id"], turn_number=2, user_message="continue",
                        files_touched='["src/core/foo.py"]')
    ev2 = record_retrieval_event(s["conn"], source="hook", search_type="user_prompt", target="decisions",
                                  query="test2", result_count=1, latency_ms=5,
                                  session_id=s["session_id"], turn_id=turn2["id"])
    record_retrieval_selection(s["conn"], ev2["id"], "decision", s["decision_id"],
                                session_id=s["session_id"], turn_id=turn2["id"])

    from entirecontext.core.auto_apply import infer_applied_decisions
    result = infer_applied_decisions(s["conn"], s["session_id"])
    assert result["applied_count"] == 1

    apps = s["conn"].execute(
        "SELECT COUNT(*) FROM context_applications WHERE session_id = ? AND source_id = ?",
        (s["session_id"], s["decision_id"]),
    ).fetchone()[0]
    assert apps == 1


def test_infer_applied_dry_run_writes_nothing(auto_apply_setup):
    """dry_run=True must detect overlaps but not persist any records."""
    s = auto_apply_setup
    from entirecontext.core.auto_apply import infer_applied_decisions

    result = infer_applied_decisions(s["conn"], s["session_id"], dry_run=True)
    assert result["applied_count"] == 1

    apps = s["conn"].execute(
        "SELECT COUNT(*) FROM context_applications WHERE session_id = ?", (s["session_id"],)
    ).fetchone()[0]
    assert apps == 0

    outcomes = s["conn"].execute(
        "SELECT COUNT(*) FROM decision_outcomes WHERE session_id = ?", (s["session_id"],)
    ).fetchone()[0]
    assert outcomes == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auto_apply.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'entirecontext.core.auto_apply'`

- [ ] **Step 3: Implement `core/auto_apply.py`**

```python
# src/entirecontext/core/auto_apply.py
"""SessionEnd auto-apply inference: detect file overlap between surfaced decisions and session-modified files."""

from __future__ import annotations

import json
import sqlite3
from pathlib import PurePosixPath


def _collect_session_modified_files(conn: sqlite3.Connection, session_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT files_touched FROM turns WHERE session_id = ? AND files_touched IS NOT NULL",
        (session_id,),
    ).fetchall()
    paths: set[str] = set()
    for row in rows:
        raw = row["files_touched"]
        if not raw or raw.strip() in ("", "[]"):
            continue
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for p in parsed:
                    if isinstance(p, str) and p.strip():
                        paths.add(str(PurePosixPath(p.strip())))
        except (json.JSONDecodeError, TypeError):
            pass
    return paths


def _detect_overlapping_decisions(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    """Pure detection: find surfaced decisions with file overlap. No writes."""
    modified_files = _collect_session_modified_files(conn, session_id)
    if not modified_files:
        return []

    rows = conn.execute(
        """
        SELECT rs.id AS selection_id, rs.result_id AS decision_id, rs.turn_id
        FROM retrieval_selections rs
        JOIN retrieval_events re ON re.id = rs.retrieval_event_id
        WHERE rs.session_id = ?
          AND rs.result_type = 'decision'
          AND NOT EXISTS (
              SELECT 1 FROM decision_outcomes do
              WHERE do.decision_id = rs.result_id
                AND do.session_id = ?
          )
        ORDER BY rs.result_id, rs.created_at ASC
        """,
        (session_id, session_id),
    ).fetchall()

    seen: set[str] = set()
    matches: list[dict] = []

    for row in rows:
        decision_id = row["decision_id"]
        if decision_id in seen:
            continue
        seen.add(decision_id)

        decision_files_rows = conn.execute(
            "SELECT file_path FROM decision_files WHERE decision_id = ?",
            (decision_id,),
        ).fetchall()
        decision_paths = {r["file_path"] for r in decision_files_rows}

        overlap = modified_files & decision_paths
        if not overlap:
            continue

        matches.append({
            "decision_id": decision_id,
            "selection_id": row["selection_id"],
            "turn_id": row["turn_id"],
            "overlap_files": sorted(overlap),
        })

    return matches


def infer_applied_decisions(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    dry_run: bool = False,
) -> dict:
    matches = _detect_overlapping_decisions(conn, session_id)
    if not matches or dry_run:
        return {"applied_count": len(matches), "applied_decisions": matches}

    from .context import transaction
    from .telemetry import record_context_application
    from .decisions import record_decision_outcome

    applied: list[dict] = []

    for match in matches:
        note = f"auto: session_end file_overlap ({', '.join(match['overlap_files'][:3])})"
        with transaction(conn):
            record_context_application(
                conn,
                application_type="decision_change",
                selection_id=match["selection_id"],
                session_id=session_id,
                turn_id=match["turn_id"],
                note=note,
            )
            record_decision_outcome(
                conn,
                match["decision_id"],
                outcome_type="accepted",
                retrieval_selection_id=match["selection_id"],
                session_id=session_id,
                turn_id=match["turn_id"],
                note=note,
            )
        applied.append(match)

    return {"applied_count": len(applied), "applied_decisions": applied}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auto_apply.py -v`
Expected: ALL PASS

- [ ] **Step 5: Add config key**

```python
# src/entirecontext/core/config.py — add to decisions section (after "infer_ignored_on_session_end")
        "infer_applied_on_session_end": True,
```

- [ ] **Step 6: Wire into SessionEnd hook**

```python
# src/entirecontext/hooks/session_lifecycle.py — add _maybe_infer_applied_decisions BEFORE _maybe_infer_ignored_decisions

def _maybe_infer_applied_decisions(repo_path: str, session_id: str) -> None:
    """Infer 'accepted' outcome for decisions with file overlap. Config-gated."""
    try:
        from ..core.config import load_config

        config = load_config(repo_path)
        if not config.get("decisions", {}).get("infer_applied_on_session_end", True):
            return

        from ..core.auto_apply import infer_applied_decisions
        from ..db import get_db

        conn = get_db(repo_path)
        try:
            infer_applied_decisions(conn, session_id)
        finally:
            conn.close()
    except Exception as exc:
        _record_hook_warning(repo_path, "infer_applied_decisions", exc)
```

In `on_session_end()`, insert the call BEFORE `_maybe_infer_ignored_decisions`:

```python
    _maybe_infer_applied_decisions(repo_path, session_id)
    _maybe_infer_ignored_decisions(repo_path, session_id)
```

- [ ] **Step 7: Add codex stale cleanup trigger in SessionEnd**

```python
# src/entirecontext/hooks/session_lifecycle.py — add to on_session_end(), after the _maybe_* calls

def _maybe_close_stale_codex_sessions(repo_path: str) -> None:
    """Trigger codex session auto-close from SessionEnd as additional trigger surface."""
    try:
        from ..core.config import load_config
        from ..core.session import close_stale_sessions
        from ..db import get_db

        config = load_config(repo_path)
        idle_minutes = config["capture"]["codex_session_idle_minutes"]

        conn = get_db(repo_path)
        try:
            close_stale_sessions(conn, idle_minutes=idle_minutes, session_type="codex")
        finally:
            conn.close()
    except Exception as exc:
        _record_hook_warning(repo_path, "close_stale_codex_sessions", exc)
```

Add to the `on_session_end` call chain:

```python
    _maybe_close_stale_codex_sessions(repo_path)
    _maybe_emit_aar(repo_path, session_id)
```

- [ ] **Step 8: Write integration test for hook ordering**

```python
# tests/test_auto_apply.py — add (already included in auto_apply_setup fixture block above)

def test_auto_apply_prevents_ignored_double_marking(auto_apply_setup):
    """Applied decisions must not also be marked as ignored."""
    s = auto_apply_setup
    from entirecontext.core.auto_apply import infer_applied_decisions

    result = infer_applied_decisions(s["conn"], s["session_id"])
    assert result["applied_count"] == 1

    # Simulate ignored inference query (same as _maybe_infer_ignored_decisions)
    remaining = s["conn"].execute(
        """
        SELECT rs.result_id AS decision_id
        FROM retrieval_selections rs
        JOIN retrieval_events re ON re.id = rs.retrieval_event_id
        WHERE rs.session_id = ?
          AND rs.result_type = 'decision'
          AND NOT EXISTS (
              SELECT 1 FROM decision_outcomes do
              WHERE do.decision_id = rs.result_id
                AND do.session_id = ?
          )
        """,
        (s["session_id"], s["session_id"]),
    ).fetchall()

    decision_ids = {r["decision_id"] for r in remaining}
    assert s["decision_id"] not in decision_ids
```

- [ ] **Step 9: Run full test suite**

Run: `uv run pytest tests/test_auto_apply.py -v`
Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
git add src/entirecontext/core/auto_apply.py src/entirecontext/core/config.py \
  src/entirecontext/hooks/session_lifecycle.py tests/test_auto_apply.py
git commit -m "feat(intervene): SessionEnd auto-apply inference for file-overlap decisions

On SessionEnd, check intersection of surfaced decision files and
session-modified files. When overlap is detected, auto-record
context_application (decision_change) + accepted outcome. Runs BEFORE
ignored inference so applied decisions are not double-marked.

Config: decisions.infer_applied_on_session_end (default true).

Also adds close_stale_codex_sessions trigger on SessionEnd (retro
carry-forward: codex stale cleanup trigger expansion)."
```

---

### Task C: Auto-Apply Backfill Command

**Files:**
- Modify: `src/entirecontext/cli/session_cmds.py`
- Create: `tests/test_auto_apply_backfill.py`

**Design:** Iterate over ended sessions with retrieval events, run `infer_applied_decisions()` per session, report results. Pattern follows `ec session backfill-ended-at`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auto_apply_backfill.py

from typer.testing import CliRunner
from entirecontext.cli.main import app

runner = CliRunner()


def test_backfill_applied_dry_run(ec_db, ec_repo, monkeypatch):
    conn = ec_db
    conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', ?)", (ec_repo,))
    conn.execute(
        "INSERT INTO sessions (id, project_id, session_type, started_at, ended_at, last_activity_at)"
        " VALUES ('s1', 'p1', 'claude', datetime('now', '-2 hours'), datetime('now', '-1 hour'), datetime('now', '-1 hour'))"
    )
    conn.execute(
        "INSERT INTO turns (id, session_id, turn_number, user_message, files_touched)"
        " VALUES ('t1', 's1', 1, 'fix bug', '[\"src/core/foo.py\"]')"
    )
    conn.execute(
        "INSERT INTO decisions (id, title, rationale, created_at)"
        " VALUES ('d1', 'Foo pattern', 'Reasons', datetime('now', '-7 days'))"
    )
    conn.execute("INSERT INTO decision_files (decision_id, file_path) VALUES ('d1', 'src/core/foo.py')")
    conn.execute(
        "INSERT INTO retrieval_events (id, session_id, turn_id, search_type, search_query, created_at)"
        " VALUES ('re1', 's1', 't1', 'user_prompt', 'q', datetime('now', '-90 minutes'))"
    )
    conn.execute(
        "INSERT INTO retrieval_selections (id, retrieval_event_id, session_id, turn_id, result_type, result_id, created_at)"
        " VALUES ('rs1', 're1', 's1', 't1', 'decision', 'd1', datetime('now', '-90 minutes'))"
    )
    conn.close()

    result = runner.invoke(app, ["session", "backfill-applied", "--dry-run"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "1 session" in result.output.lower() or "1" in result.output
    assert "dry run" in result.output.lower() or "dry" in result.output.lower()


def test_backfill_applied_apply(ec_db, ec_repo, monkeypatch):
    conn = ec_db
    conn.execute("INSERT INTO projects (id, name, repo_path) VALUES ('p1', 'test', ?)", (ec_repo,))
    conn.execute(
        "INSERT INTO sessions (id, project_id, session_type, started_at, ended_at, last_activity_at)"
        " VALUES ('s1', 'p1', 'claude', datetime('now', '-2 hours'), datetime('now', '-1 hour'), datetime('now', '-1 hour'))"
    )
    conn.execute(
        "INSERT INTO turns (id, session_id, turn_number, user_message, files_touched)"
        " VALUES ('t1', 's1', 1, 'fix bug', '[\"src/core/foo.py\"]')"
    )
    conn.execute(
        "INSERT INTO decisions (id, title, rationale, created_at)"
        " VALUES ('d1', 'Foo pattern', 'Reasons', datetime('now', '-7 days'))"
    )
    conn.execute("INSERT INTO decision_files (decision_id, file_path) VALUES ('d1', 'src/core/foo.py')")
    conn.execute(
        "INSERT INTO retrieval_events (id, session_id, turn_id, search_type, search_query, created_at)"
        " VALUES ('re1', 's1', 't1', 'user_prompt', 'q', datetime('now', '-90 minutes'))"
    )
    conn.execute(
        "INSERT INTO retrieval_selections (id, retrieval_event_id, session_id, turn_id, result_type, result_id, created_at)"
        " VALUES ('rs1', 're1', 's1', 't1', 'decision', 'd1', datetime('now', '-90 minutes'))"
    )

    from entirecontext.db import get_db
    monkeypatch.setattr("entirecontext.cli.session_cmds._get_repo_path", lambda: ec_repo)

    result = runner.invoke(app, ["session", "backfill-applied", "--apply"], catch_exceptions=False)
    assert result.exit_code == 0

    reconn = get_db(ec_repo)
    try:
        app_count = reconn.execute(
            "SELECT COUNT(*) FROM context_applications WHERE session_id = 's1'"
        ).fetchone()[0]
        assert app_count == 1
    finally:
        reconn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auto_apply_backfill.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the CLI command**

```python
# src/entirecontext/cli/session_cmds.py — add to existing session command group

@session_app.command("backfill-applied")
def session_backfill_applied(
    dry_run: bool = typer.Option(True, "--dry-run/--apply", help="Preview without changes (default) or apply."),
):
    """Retroactively infer applied decisions for ended sessions with retrieval events.

    Detects file overlap between surfaced decisions and session-modified files.
    Safe default is --dry-run; pass --apply to commit changes.
    """
    from ..core.project import find_git_root, get_project
    from ..db import get_db
    from ..core.auto_apply import infer_applied_decisions

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
        session_ids = [
            r[0]
            for r in conn.execute(
                """
                SELECT DISTINCT s.id
                FROM sessions s
                JOIN retrieval_events re ON re.session_id = s.id
                JOIN retrieval_selections rs ON rs.retrieval_event_id = re.id
                                             AND rs.result_type = 'decision'
                WHERE s.ended_at IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM context_applications ca
                      WHERE ca.session_id = s.id
                        AND ca.note LIKE 'auto: session_end file_overlap%'
                  )
                """
            ).fetchall()
        ]

        if not session_ids:
            console.print("[dim]No eligible sessions found.[/dim]")
            return

        total_applied = 0
        sessions_with_applies = 0

        for sid in session_ids:
            result = infer_applied_decisions(conn, sid, dry_run=dry_run)
            if result["applied_count"] > 0:
                sessions_with_applies += 1
                total_applied += result["applied_count"]

        mode = "Dry run" if dry_run else "Applied"
        console.print(
            f"[bold]{mode}: {total_applied} applications across "
            f"{sessions_with_applies}/{len(session_ids)} sessions[/bold]"
        )
        if dry_run:
            console.print("[dim]Use --apply to commit changes.[/dim]")
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auto_apply_backfill.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/cli/session_cmds.py tests/test_auto_apply_backfill.py
git commit -m "feat(cli): ec session backfill-applied for historical auto-apply

Retroactively runs auto-apply inference on ended sessions with retrieval
events. Bootstraps context_applications from historical PDI data.
Options: --dry-run (preview) or --apply (write)."
```

---

### Task D: Duplicate Notify Regression Test

**Files:**
- Modify: `tests/test_codex_ingest.py`

- [ ] **Step 1: Write the regression test**

```python
# tests/test_codex_ingest.py — add to existing file

def test_duplicate_notify_does_not_refresh_last_activity_at(ec_db, ec_repo, tmp_path):
    """Commit 150faab: duplicate notify events must not update last_activity_at."""
    import json
    import time

    notify_data = {
        "meta": {"session_id": "dup-test", "cwd": ec_repo},
        "turns": [
            {"user_message": "hello", "assistant_summary": "world", "timestamp": "2026-01-01T00:00:00Z"}
        ],
    }
    notify_file = tmp_path / "notify.json"
    notify_file.write_text(json.dumps(notify_data))

    from entirecontext.hooks.codex_ingest import ingest_codex_notify_event

    # First ingest
    ingest_codex_notify_event(str(notify_file), ec_repo)

    from entirecontext.db import get_db
    conn = get_db(ec_repo)
    try:
        row1 = conn.execute(
            "SELECT last_activity_at, total_turns FROM sessions WHERE id = 'dup-test'"
        ).fetchone()
        assert row1 is not None
        assert row1["total_turns"] == 1
        first_activity = row1["last_activity_at"]
    finally:
        conn.close()

    time.sleep(0.05)

    # Second ingest with same data — duplicate
    ingest_codex_notify_event(str(notify_file), ec_repo)

    conn = get_db(ec_repo)
    try:
        row2 = conn.execute(
            "SELECT last_activity_at, total_turns FROM sessions WHERE id = 'dup-test'"
        ).fetchone()
        assert row2["total_turns"] == 1, "Turn count should not change on duplicate"
        assert row2["last_activity_at"] == first_activity, "last_activity_at must not change on duplicate"
    finally:
        conn.close()
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_codex_ingest.py::test_duplicate_notify_does_not_refresh_last_activity_at -v`
Expected: PASS (the fix from 150faab should already handle this)

- [ ] **Step 3: Commit**

```bash
git add tests/test_codex_ingest.py
git commit -m "test(codex): regression test for duplicate notify skip (150faab)

Verifies that calling ingest_codex_notify_event twice with the same event
does not update last_activity_at or increment total_turns. Guards the
auto-close accuracy invariant."
```

---

### Task E: Signal C Config Activation

**Files:**
- Modify: `src/entirecontext/core/config.py:126`
- Modify: `tests/test_decision_embedding.py`

- [ ] **Step 1: Write failing test for default-on behavior**

```python
# tests/test_decision_embedding.py — add to existing file

def test_auto_embed_default_is_true():
    """Signal C activation: auto_embed should default to True in v0.9.0."""
    from entirecontext.core.config import DEFAULT_CONFIG
    assert DEFAULT_CONFIG["decisions"]["auto_embed"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decision_embedding.py::test_auto_embed_default_is_true -v`
Expected: FAIL — current default is False

- [ ] **Step 3: Flip the config default**

```python
# src/entirecontext/core/config.py line 126 — change:
        "auto_embed": False,
# to:
        "auto_embed": True,
```

- [ ] **Step 4: Write test for graceful fallback without sentence-transformers**

```python
# tests/test_decision_embedding.py — add

def test_create_decision_auto_embed_graceful_without_transformers(ec_db, ec_repo, monkeypatch):
    """auto_embed=True must not crash create_decision when sentence-transformers is missing."""
    import builtins
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "sentence_transformers" or name.startswith("sentence_transformers."):
            raise ImportError("mocked: no sentence_transformers")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    from entirecontext.core.decisions import create_decision

    result = create_decision(
        ec_db,
        title="Test decision",
        rationale="Test rationale",
        repo_path=ec_repo,
    )
    assert result["title"] == "Test decision"

    embed_count = ec_db.execute(
        "SELECT COUNT(*) FROM embeddings WHERE source_type = 'decision'"
    ).fetchone()[0]
    assert embed_count == 0
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_decision_embedding.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/entirecontext/core/config.py tests/test_decision_embedding.py
git commit -m "feat(signal-c): flip auto_embed default to True

Decisions are now auto-embedded on creation when sentence-transformers
is available. Gracefully falls back (no-op) when the semantic extra is
not installed. Foundation for future 2-pass async ranking."
```

---

### Task F: ROADMAP + CHANGELOG

**Files:**
- Modify: `ROADMAP.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update ROADMAP.md v0.9.0 section**

Replace the current v0.9.0 section with checked items:

```markdown
## v0.9.0 — Intervene Automation (Shipped YYYY-MM-DD)

Theme: automate the weakest maturity dimension (intervene=5), activate deferred signal depth, and fix measurement gaps — all measured against v0.8.1's corrected baseline.

- [x] **SessionEnd auto-apply inference** — on SessionEnd, check intersection of surfaced decision-linked files and session-modified files; auto-record `context_application` + `accepted` outcome for matches. Inverse of `_maybe_infer_ignored_decisions`. Config: `decisions.infer_applied_on_session_end` (default true).
- [x] **Auto-apply backfill** — `ec session backfill-applied` retroactively infers applied decisions for historical sessions. Options: `--dry-run` / `--apply`.
- [x] **search_to_selection_rate DISTINCT fix** — formula changed from `total_selections / total_events` to `DISTINCT events with ≥1 selection / total_events`. Now a proper [0,1] fraction.
- [x] **Signal C default ON** — `[decisions] auto_embed` flipped to `true` by default. Graceful no-op without `entirecontext[semantic]`.
- [x] **Codex stale cleanup trigger expansion** — `close_stale_sessions()` now also triggered on SessionEnd, not just codex notify ingestion.
- [x] **Duplicate notify regression test** — guards 150faab auto-close accuracy invariant.
- [ ] **Rule-based verdict mapping tuning** — deferred to n≥30 enriched assessments (current: n=10).
```

- [ ] **Step 2: Update CHANGELOG.md**

Add `## [0.9.0] - Intervene Automation` section above `## [0.8.1]`:

```markdown
## [0.9.0] - Intervene Automation

### Added

- **SessionEnd auto-apply inference** — on SessionEnd, detects file overlap between surfaced decisions (`decision_files`) and session-modified files (`turns.files_touched`), auto-records `context_application` (type `decision_change`) and `accepted` outcome. Runs before ignored inference to prevent double-marking. Config: `decisions.infer_applied_on_session_end` (default true).
- **`ec session backfill-applied`** — retroactive auto-apply inference for historical ended sessions with retrieval events. Options: `--dry-run` (preview), `--apply` (write).
- **Codex stale cleanup on SessionEnd** — `close_stale_sessions()` now also fires during SessionEnd hook, expanding trigger surface beyond codex notify ingestion.
- **Dashboard _rate metric guard test** — asserts all `_rate` metrics in `compute_dashboard()` output stay in [0, 1] range.
- **Duplicate notify regression test** — guards commit 150faab invariant (duplicate codex notify does not refresh `last_activity_at`).

### Fixed

- **`search_to_selection_rate` semantic bug** — formula changed from `total_selections / total_events` (could exceed 1.0 due to 1:N selection relationship) to `DISTINCT events with ≥1 selection / total_events`, a proper [0, 1] fraction. Maturity scoring threshold (≥0.25) and current score unchanged.

### Changed

- **`[decisions] auto_embed`** — default flipped from `false` to `true`. Decisions are now auto-embedded on creation when `entirecontext[semantic]` is installed. Graceful no-op without the optional dependency.
```

- [ ] **Step 3: Commit**

```bash
git add ROADMAP.md CHANGELOG.md
git commit -m "docs: v0.9.0 Intervene Automation roadmap and changelog"
```

---

## Parallelization

```
Task A (measurement fix) ───┐
Task B (auto-apply) ────────┼──> Task F (docs)
Task C (backfill CLI) ──────┤    (sequential after A-E)
Task D (regression test) ───┤
Task E (Signal C config) ───┘
```

Task C depends on Task B (uses `infer_applied_decisions`). All others are independent. Config edits in Task B and E both touch `config.py` — execute B before E to avoid merge conflicts.

## Verification

1. `uv run pytest` — all tests pass
2. `uv run ruff check . && uv run ruff format --check .` — lint clean
3. `uv run ec dashboard` — verify maturity ≥69 maintained (pre-backfill)
4. `uv run ec session backfill-applied --dry-run` — verify candidate count (ceiling: 154 pairs, expect ≥48 after overlap filter)
5. `uv run ec session backfill-applied --apply` — bootstrap historical data
6. `uv run ec dashboard` — measure post-backfill maturity (mechanism is the deliverable; score is a measurement outcome)
