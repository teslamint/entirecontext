# v0.9.1 Measurement Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `applied_context_rate` formula to session-based metric so maturity scoring reflects reality, and register retro carry-forward items in ROADMAP.

**Architecture:** Change the `applied_context_rate` numerator/denominator from per-selection counts to per-session counts. Update dashboard query, telemetry output shape, maturity scoring, all tests, and ROADMAP/CHANGELOG docs.

**Tech Stack:** Python 3.12+, SQLite, pytest

---

## Callers / Blast Radius

| Caller | Impact |
|--------|--------|
| `core/aar.py` `pdi_delta` | **None** — AAR computes per-session `applied_count / surfaced_count` independently |
| `cli/dashboard_cmds.py:171` | **None** — reads `rates['applied_context_rate']` value only; label "applied-context rate" still accurate |
| `mcp/server.py` `ec_dashboard` | **None** — passes through `get_dashboard_stats()` dict; additive keys are safe |

## Invariants

1. `applied_context_rate` must stay in [0, 1] — enforced by existing `test_all_rate_metrics_in_valid_range`
2. Both numerator and denominator must filter `ended_at IS NOT NULL` — matches v0.8.1 normalization pattern (dashboard.py:173-177)
3. Prior retro carry-forwards: `reopen → sessions_ended` non-monotonic (v0.8.1), retro→ROADMAP transfer (v0.9.0)

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/entirecontext/core/dashboard.py:170-215` | Modify | Replace per-selection rate query with session-based query |
| `src/entirecontext/core/dashboard.py:340-375` | Modify | Update telemetry output dict to expose session-based counts |
| `tests/test_dashboard.py` | Modify | Update `_seed_telemetry`, rate assertions, `_mock_stats`, guard test |
| `ROADMAP.md` | Modify | Add v0.9.1 section, register carry-forward items |
| `CHANGELOG.md` | Modify | Add v0.9.1 entry (version bump deferred until auto_extract dogfooding confirmed) |

---

### Task 1: `applied_context_rate` Session-Based Formula

**Files:**
- Modify: `src/entirecontext/core/dashboard.py:182-214`
- Modify: `src/entirecontext/core/dashboard.py:354-374`
- Test: `tests/test_dashboard.py`

**Context:**

Current formula (line 213-214):
```python
applied_context_rate = (
    context_applications_with_selection / retrieval_selections_total if retrieval_selections_total > 0 else 0.0
)
```
This divides total context_applications (that have a selection FK) by total retrieval_selections. With ~15 selections per session and ~1 application per session, the rate converges to ~6.7% max — structurally cannot reach the 0.1 threshold.

New formula:
```python
applied_context_rate = (
    sessions_with_application / sessions_with_selection if sessions_with_selection > 0 else 0.0
)
```
Where:
- `sessions_with_selection` = COUNT(DISTINCT rs.session_id) FROM retrieval_selections rs JOIN sessions s ON rs.session_id = s.id WHERE s.ended_at IS NOT NULL
- `sessions_with_application` = COUNT(DISTINCT ca.session_id) FROM context_applications ca JOIN sessions s ON ca.session_id = s.id WHERE ca.retrieval_selection_id IS NOT NULL AND s.ended_at IS NOT NULL

**Critical**: both queries JOIN sessions and filter `ended_at IS NOT NULL` — matching the v0.8.1 normalization pattern. Without this, active/codex sessions inflate the denominator without contributing to the numerator (applications only recorded at SessionEnd).

- [ ] **Step 1: Write failing test for session-based rate**

In `tests/test_dashboard.py`, add a new test after `test_all_rate_metrics_in_valid_range`:

```python
def test_applied_context_rate_session_based(self, ec_repo, ec_db):
    """applied_context_rate uses session-based denominator, not selection count."""
    from entirecontext.core.project import get_project
    from entirecontext.core.session import create_session

    project = get_project(str(ec_repo))

    # Session 1: 10 selections, 1 application -> should count as 1 session with application
    s1 = create_session(ec_db, project["id"], session_id="acr-s1")
    ec_db.execute("UPDATE sessions SET ended_at = datetime('now') WHERE id = ?", (s1["id"],))
    ec_db.execute(
        "INSERT INTO retrieval_events (id, session_id, source, search_type, target, query, created_at)"
        " VALUES ('acr-re1', ?, 'hook', 'regex', 'turn', 'q', datetime('now'))",
        (s1["id"],),
    )
    for i in range(10):
        ec_db.execute(
            "INSERT INTO retrieval_selections (id, retrieval_event_id, session_id, result_type, result_id, rank, created_at)"
            f" VALUES ('acr-rs1-{i}', 'acr-re1', ?, 'turn', 'turn-{i}', {i + 1}, datetime('now'))",
            (s1["id"],),
        )
    ec_db.execute(
        "INSERT INTO context_applications (id, session_id, retrieval_selection_id, source_type, source_id, application_type, created_at)"
        " VALUES ('acr-ca1', ?, 'acr-rs1-0', 'decision', 'd1', 'decision_change', datetime('now'))",
        (s1["id"],),
    )

    # Session 2: 5 selections, 0 applications -> 1 session without application
    s2 = create_session(ec_db, project["id"], session_id="acr-s2")
    ec_db.execute("UPDATE sessions SET ended_at = datetime('now') WHERE id = ?", (s2["id"],))
    ec_db.execute(
        "INSERT INTO retrieval_events (id, session_id, source, search_type, target, query, created_at)"
        " VALUES ('acr-re2', ?, 'hook', 'regex', 'turn', 'q', datetime('now'))",
        (s2["id"],),
    )
    for i in range(5):
        ec_db.execute(
            "INSERT INTO retrieval_selections (id, retrieval_event_id, session_id, result_type, result_id, rank, created_at)"
            f" VALUES ('acr-rs2-{i}', 'acr-re2', ?, 'turn', 'turn-{i}', {i + 1}, datetime('now'))",
            (s2["id"],),
        )
    ec_db.commit()

    stats = get_dashboard_stats(ec_db)
    # Session-based: 1 session with app / 2 sessions with selections = 0.5
    # Old per-selection: 1 app / 15 selections = 0.067
    assert stats["telemetry"]["rates"]["applied_context_rate"] == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dashboard.py::TestGetDashboardStats::test_applied_context_rate_session_based -v`
Expected: FAIL — current formula returns ~0.067 instead of 0.5

- [ ] **Step 3: Replace queries in dashboard.py**

In `src/entirecontext/core/dashboard.py`, replace lines 182-214:

**Old** (lines 182-214):
```python
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
            + (" WHERE re.created_at >= ?" if since is not None else ""),
            since_params,
        ).fetchone()["total"]
        or 0
    )

    applications_row = conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(CASE WHEN retrieval_selection_id IS NOT NULL THEN 1 ELSE 0 END) AS with_selection,"
        " SUM(CASE WHEN source_type IN ('assessment', 'lesson') THEN 1 ELSE 0 END) AS lesson_reuse"
        f" FROM context_applications{since_clause_ca}",
        since_params,
    ).fetchone()
    context_applications_total = applications_row["total"] or 0
    context_applications_with_selection = applications_row["with_selection"] or 0
    lesson_reuse_count = applications_row["lesson_reuse"] or 0

    retrieval_assisted_session_rate = retrieval_sessions_total / sessions_ended if sessions_ended > 0 else 0.0
    search_to_selection_rate = events_with_selection / retrieval_events_total if retrieval_events_total > 0 else 0.0
    applied_context_rate = (
        context_applications_with_selection / retrieval_selections_total if retrieval_selections_total > 0 else 0.0
    )
    lesson_reuse_rate = lesson_reuse_count / context_applications_total if context_applications_total > 0 else 0.0
```

**New:**
```python
    retrieval_selections_total = (
        conn.execute(
            f"SELECT COUNT(*) AS total FROM retrieval_selections{since_clause_ca}",
            since_params,
        ).fetchone()["total"]
        or 0
    )
    sessions_with_selection = (
        conn.execute(
            "SELECT COUNT(DISTINCT rs.session_id) AS total"
            " FROM retrieval_selections rs"
            " JOIN sessions s ON rs.session_id = s.id"
            " WHERE s.ended_at IS NOT NULL"
            + (" AND rs.created_at >= ?" if since is not None else ""),
            since_params,
        ).fetchone()["total"]
        or 0
    )
    events_with_selection = (
        conn.execute(
            "SELECT COUNT(DISTINCT re.id) AS total"
            " FROM retrieval_events re"
            " JOIN retrieval_selections rs ON rs.retrieval_event_id = re.id"
            + (" WHERE re.created_at >= ?" if since is not None else ""),
            since_params,
        ).fetchone()["total"]
        or 0
    )

    applications_row = conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(CASE WHEN retrieval_selection_id IS NOT NULL THEN 1 ELSE 0 END) AS with_selection,"
        " SUM(CASE WHEN source_type IN ('assessment', 'lesson') THEN 1 ELSE 0 END) AS lesson_reuse"
        f" FROM context_applications{since_clause_ca}",
        since_params,
    ).fetchone()
    context_applications_total = applications_row["total"] or 0
    context_applications_with_selection = applications_row["with_selection"] or 0
    lesson_reuse_count = applications_row["lesson_reuse"] or 0
    sessions_with_application = (
        conn.execute(
            "SELECT COUNT(DISTINCT ca.session_id) AS total"
            " FROM context_applications ca"
            " JOIN sessions s ON ca.session_id = s.id"
            " WHERE ca.retrieval_selection_id IS NOT NULL"
            " AND s.ended_at IS NOT NULL"
            + (" AND ca.created_at >= ?" if since is not None else ""),
            since_params,
        ).fetchone()["total"]
        or 0
    )

    retrieval_assisted_session_rate = retrieval_sessions_total / sessions_ended if sessions_ended > 0 else 0.0
    search_to_selection_rate = events_with_selection / retrieval_events_total if retrieval_events_total > 0 else 0.0
    applied_context_rate = (
        sessions_with_application / sessions_with_selection if sessions_with_selection > 0 else 0.0
    )
    lesson_reuse_rate = lesson_reuse_count / context_applications_total if context_applications_total > 0 else 0.0
```

- [ ] **Step 4: Update telemetry output dict**

In `src/entirecontext/core/dashboard.py`, update the telemetry section (lines ~354-374) to expose session-based counts:

**Old:**
```python
        "retrieval_selections": {
            "total": retrieval_selections_total,
        },
        "context_applications": {
            "total": context_applications_total,
            "with_selection": context_applications_with_selection,
        },
```

**New:**
```python
        "retrieval_selections": {
            "total": retrieval_selections_total,
            "sessions_with_selection": sessions_with_selection,
        },
        "context_applications": {
            "total": context_applications_total,
            "with_selection": context_applications_with_selection,
            "sessions_with_application": sessions_with_application,
        },
```

- [ ] **Step 5: Update existing tests**

In `tests/test_dashboard.py`:

1. Update `test_telemetry_rates` (line 253-261) — `_seed_telemetry` seeds 1 session with 1 selection and 1 application, so session-based rate is still 1.0. **No change needed to assertion.**

2. Update `_mock_stats()` (around line 491-498) — add the new keys to the mock:

```python
"retrieval_selections": {"total": 1, "sessions_with_selection": 1},
"context_applications": {"total": 1, "with_selection": 1, "sessions_with_application": 1},
```

3. Update `test_empty_stats_renders_without_error` (around line 554-555) — add new keys:

```python
"retrieval_selections": {"total": 0, "sessions_with_selection": 0},
"context_applications": {"total": 0, "with_selection": 0, "sessions_with_application": 0},
```

- [ ] **Step 6: Run all dashboard tests**

Run: `uv run pytest tests/test_dashboard.py -v`
Expected: ALL PASS

- [ ] **Step 7: Run rate guard test specifically**

Run: `uv run pytest tests/test_dashboard.py::TestGetDashboardStats::test_all_rate_metrics_in_valid_range -v`
Expected: PASS — session-based rate still in [0, 1]

- [ ] **Step 8: Commit**

```bash
git add src/entirecontext/core/dashboard.py tests/test_dashboard.py
git commit -m "fix(dashboard): change applied_context_rate to session-based formula

Old formula: context_applications_with_selection / retrieval_selections_total
converges to ~6.7% max (structurally cannot reach 0.1 threshold).

New formula: sessions_with_application / sessions_with_selection
counts at session granularity, making the rate semantically meaningful."
```

---

### Task 2: ROADMAP v0.9.1 Section + Carry-Forward Registration

**Files:**
- Modify: `ROADMAP.md:221-231`

**Context:** v0.9.0 retro identified two carry-forward items that were never registered in ROADMAP:
1. `reopen → sessions_ended` non-monotonic impact (deferred since v0.8.1)
2. Retro → ROADMAP transfer rule (process gap discovered in v0.9.0 retro)

- [ ] **Step 1: Add v0.9.1 section after v0.9.0 in ROADMAP.md**

After line 231 (end of v0.9.0 section), insert:

```markdown

## v0.9.1 — Measurement Calibration

Theme: fix measurement formulas so maturity scores reflect actual loop completion, and establish the retro carry-forward process.

- [ ] **`applied_context_rate` session-based formula** — numerator/denominator changed from per-selection counts to per-session counts. Old formula structurally capped at ~6.7%; new formula `sessions_with_application / sessions_with_selection` reaches threshold naturally. ec decision `b09d1aed`.
- [ ] **`auto_extract` default true** — pending local dogfooding confirmation (config flip in v0.3.0 code, never enabled). ec decision `309d472a`.
- [ ] **Retro carry-forward → ROADMAP registration rule** — v0.9.0 retro finding: deferred items were not transferred to ROADMAP, causing 4-release drift. Rule: retro completion must register carry-forwards in ROADMAP or mark explicit won't-fix.
- [ ] **`reopen → sessions_ended` non-monotonic evaluation** — deferred from v0.8.1, v0.9.0. Evaluate whether session reopen can make `sessions_ended` count decrease and whether this matters for rate stability. Resolve as fix or won't-fix.
```

- [ ] **Step 2: Run no tests (docs-only change)**

- [ ] **Step 3: Commit**

```bash
git add ROADMAP.md
git commit -m "docs(roadmap): add v0.9.1 Measurement Calibration section

Registers carry-forward items from v0.9.0 retro:
- applied_context_rate formula fix
- auto_extract default flip (pending dogfooding)
- retro→ROADMAP transfer rule
- reopen non-monotonic evaluation (deferred since v0.8.1)"
```

---

### Task 3: CHANGELOG v0.9.1 Entry

**Files:**
- Modify: `CHANGELOG.md:1-8`

Note: version bump in pyproject.toml and tag/push are deferred to the release step — `auto_extract` dogfooding must confirm before shipping.

- [ ] **Step 1: Add v0.9.1 entry above v0.9.0**

Insert after line 7 (before `## [0.9.0]`):

```markdown
## [Unreleased]

### Fixed

- **`applied_context_rate` session-based formula** — numerator/denominator changed from per-selection counts (`context_applications_with_selection / retrieval_selections_total`, structurally capped at ~6.7%) to per-session counts (`sessions_with_application / sessions_with_selection`). Both queries filter `ended_at IS NOT NULL` (v0.8.1 normalization pattern). Maturity intervene dimension now reachable.

### Changed

- Telemetry output adds `sessions_with_selection` and `sessions_with_application` counters for transparency.

```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): add applied_context_rate formula fix entry"
```

---

## Parallelization

```
Task 1 (formula fix) ──> Task 2 (ROADMAP) ──> Task 3 (CHANGELOG)
```

Sequential: Task 2 depends on Task 1 being committed (ROADMAP references the fix). Task 3 depends on both.

## Verification

1. `uv run pytest tests/test_dashboard.py -v` — all tests pass
2. `uv run ruff check . && uv run ruff format --check .` — lint clean
3. New `test_applied_context_rate_session_based` proves session-based math
4. Rate guard test confirms [0, 1] range preserved
5. `uv run ec dashboard` on dogfooding DB — verify intervene score reaches 13 (5 base + 8 from rate≥0.1)
6. No schema changes — still v14
