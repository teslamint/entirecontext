# v0.8.0 Distill Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Break the 3-sprint distill=0 streak by auto-creating assessments on every checkpoint, with LLM enrichment and git-evidence feedback as complementary quality layers.

**Non-goal:** Maturity ≥75 — current ceiling is constrained by retrieve (17/25) and intervene (5/20), which this PR does not address. Maturity ≥75 requires separate work on those dimensions.

**Architecture:** 3-tier trigger (sync create → SessionEnd backfill+enrich → SessionStart catch-up). Rule-based verdict from conventional commit parsing. LLM enrichment via CLI backend (`claude -p`, headless confirmed). Git-evidence feedback as API-free fallback. All auto-assess logic in a new `core/auto_assess.py` module, wired into existing hook lifecycle.

**Tech Stack:** Python 3.12, SQLite, Typer CLI, existing LLM backend infrastructure (`core/llm.py`)

---

## Design Corrections (from advisor + code exploration)

1. **Call sites:** No MCP checkpoint-create tool exists. `sync/coordinator.py:372` calls `create_checkpoint()` but MUST be excluded (imported commits reference non-local git state). Tier 1 sites: CLI `checkpoint_cmds.py`, `_maybe_create_auto_checkpoint()`, `on_post_commit()`.
2. **Async enrichment:** LLM enrichment in SessionEnd MUST use background worker (`launch_worker` + `pid_name="worker-assess"`) — synchronous calls would block the hook for N×120s.
3. **Feedback validation:** `VALID_FEEDBACKS = ("agree", "disagree")` in `futures.py:13`. Use `feedback_reason` for detail: `"auto:llm-confirmed"`, `"auto:revised:neutral->expand"`, `"auto:committed"`.
4. **model_name accuracy:** CLI backend ignores model param. Write `model_name="claude-cli"` (or `"codex-cli"`) for enriched assessments, not the configured model string.

## File Structure

**New files:**
- `src/entirecontext/core/auto_assess.py` — all distill automation logic
- `tests/test_auto_assess.py` — unit tests
- `tests/test_distill_automation.py` — integration tests

**Modified files:**
- `core/config.py` — new config keys, default_backend change
- `core/git_utils.py` — `get_commit_messages()` helper
- `core/dashboard.py` — `enriched_rate` metric
- `hooks/session_lifecycle.py` — Tier 1/2/3 hook wiring
- `cli/checkpoint_cmds.py` — Tier 1 CLI path
- `cli/futures_cmds.py` — `enrich-backlog` command

---

### Task 1: `get_commit_messages()` in git_utils.py

**Files:**
- Modify: `src/entirecontext/core/git_utils.py`
- Test: `tests/test_auto_assess.py`

- [ ] **Step 1: Write failing tests**

```python
def test_get_commit_messages_returns_list(git_repo):
    subprocess.run(["git", "commit", "--allow-empty", "-m", "feat: add API"], cwd=git_repo, capture_output=True)
    msgs = get_commit_messages(str(git_repo), from_commit=None, to_commit="HEAD")
    # from_commit=None -> empty list (no range)
    assert msgs == []

def test_get_commit_messages_with_range(git_repo):
    r1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_repo, capture_output=True, text=True)
    base = r1.stdout.strip()
    subprocess.run(["git", "commit", "--allow-empty", "-m", "feat: add login"], cwd=git_repo, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "fix: typo"], cwd=git_repo, capture_output=True)
    msgs = get_commit_messages(str(git_repo), from_commit=base, to_commit="HEAD")
    assert "fix: typo" in msgs
    assert "feat: add login" in msgs
    assert len(msgs) == 2

def test_get_commit_messages_invalid_range(git_repo):
    msgs = get_commit_messages(str(git_repo), from_commit="deadbeef", to_commit="HEAD")
    assert msgs == []

def test_get_commit_messages_same_commit(git_repo):
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_repo, capture_output=True, text=True)
    sha = r.stdout.strip()
    msgs = get_commit_messages(str(git_repo), from_commit=sha, to_commit=sha)
    assert msgs == []
```

- [ ] **Step 2: Run tests, verify failure**

Run: `uv run pytest tests/test_auto_assess.py::test_get_commit_messages_returns_list -v`

- [ ] **Step 3: Implement**

```python
def get_commit_messages(repo_path: str, from_commit: str | None, to_commit: str = "HEAD") -> list[str]:
    if not from_commit:
        return []
    try:
        result = subprocess.run(
            ["git", "log", "--format=%s", f"{from_commit}..{to_commit}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [line for line in result.stdout.strip().splitlines() if line.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []
```

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/core/git_utils.py tests/test_auto_assess.py
git commit -m "feat(git): add get_commit_messages helper for commit range parsing"
```

---

### Task 2: Rule-based verdict logic in auto_assess.py

**Files:**
- Create: `src/entirecontext/core/auto_assess.py`
- Test: `tests/test_auto_assess.py`

- [ ] **Step 1: Write failing tests**

```python
from entirecontext.core.auto_assess import compute_rule_verdict

def test_verdict_feat():
    assert compute_rule_verdict(["feat: add API"]) == "expand"

def test_verdict_feat_scoped():
    assert compute_rule_verdict(["feat(auth): add SSO"]) == "expand"

def test_verdict_revert():
    assert compute_rule_verdict(["revert: undo feature"]) == "narrow"

def test_verdict_fix():
    assert compute_rule_verdict(["fix: null check"]) == "neutral"

def test_verdict_mixed_feat_revert():
    assert compute_rule_verdict(["feat: add", "revert: undo"]) == "neutral"

def test_verdict_empty():
    assert compute_rule_verdict([]) == "neutral"

def test_verdict_case_insensitive():
    assert compute_rule_verdict(["FEAT: big thing"]) == "expand"

def test_verdict_non_conventional():
    assert compute_rule_verdict(["Update README"]) == "neutral"

def test_verdict_merge_commit():
    assert compute_rule_verdict(["Merge branch 'feature' into 'main'"]) == "neutral"
```

- [ ] **Step 2: Run tests, verify failure**
- [ ] **Step 3: Implement**

```python
from __future__ import annotations

import re

_EXPAND_RE = re.compile(r"^feat[\s(:]", re.IGNORECASE)
_NARROW_RE = re.compile(r"^revert[\s(:]", re.IGNORECASE)


def compute_rule_verdict(commit_messages: list[str]) -> str:
    has_expand = any(_EXPAND_RE.match(m.strip()) for m in commit_messages)
    has_narrow = any(_NARROW_RE.match(m.strip()) for m in commit_messages)
    if has_expand and has_narrow:
        return "neutral"
    if has_expand:
        return "expand"
    if has_narrow:
        return "narrow"
    return "neutral"
```

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/core/auto_assess.py tests/test_auto_assess.py
git commit -m "feat(assess): add rule-based verdict from conventional commits"
```

---

### Task 3: `auto_assess_checkpoint()` core function

**Files:**
- Modify: `src/entirecontext/core/auto_assess.py`
- Test: `tests/test_auto_assess.py`

- [ ] **Step 1: Write failing tests**

```python
def test_auto_assess_creates_assessment(ec_repo, ec_db):
    session_id = _create_test_session(ec_db)
    # Make a feat commit
    subprocess.run(["git", "commit", "--allow-empty", "-m", "feat: add endpoint"], cwd=ec_repo, capture_output=True)
    cp = create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    result = auto_assess_checkpoint(ec_db, cp["id"], str(ec_repo), session_id)
    assert result is not None
    assert result["verdict"] == "expand"
    assert result["model_name"] == "rule-based"

def test_auto_assess_no_prior_returns_neutral(ec_repo, ec_db):
    session_id = _create_test_session(ec_db)
    cp = create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    result = auto_assess_checkpoint(ec_db, cp["id"], str(ec_repo), session_id)
    assert result is not None
    assert result["verdict"] == "neutral"

def test_auto_assess_never_raises(ec_repo, ec_db):
    result = auto_assess_checkpoint(ec_db, "nonexistent", "/bad/path", "bad-session")
    assert result is None
```

- [ ] **Step 2: Run tests, verify failure**
- [ ] **Step 3: Implement**

`auto_assess_checkpoint(conn, checkpoint_id, repo_path, session_id)`:
1. Get checkpoint record → extract `git_commit_hash`
2. Find previous checkpoint in same session → get its `git_commit_hash` as `from_commit`
3. Fallback: session metadata `start_git_commit`
4. `get_commit_messages(repo_path, from_commit, to_commit)`
5. `compute_rule_verdict(messages)`
6. Build impact_summary from first commit message (truncate 120 chars) or `"Auto-assessed checkpoint"`
7. `create_assessment(conn, checkpoint_id=checkpoint_id, verdict=verdict, impact_summary=impact_summary, diff_summary=checkpoint_diff_summary, model_name="rule-based")`
8. Wrap entire body in try/except → return None on any error

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/core/auto_assess.py tests/test_auto_assess.py
git commit -m "feat(assess): auto_assess_checkpoint with commit-based verdict"
```

---

### Task 4: Backfill + enrichment candidate queries

**Files:**
- Modify: `src/entirecontext/core/auto_assess.py`
- Test: `tests/test_auto_assess.py`

- [ ] **Step 1: Write failing tests**

```python
def test_backfill_creates_missing_assessments(ec_repo, ec_db):
    session_id = _create_test_session(ec_db)
    cp1 = create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    cp2 = create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    # cp1 has assessment, cp2 does not
    create_assessment(ec_db, checkpoint_id=cp1["id"], verdict="neutral")
    count = backfill_unassessed_checkpoints(ec_db, str(ec_repo), session_id=session_id)
    assert count == 1  # only cp2

def test_backfill_respects_window(ec_repo, ec_db):
    # checkpoint with old created_at should not be backfilled
    session_id = _create_test_session(ec_db)
    cp = create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    ec_db.execute("UPDATE checkpoints SET created_at = datetime('now', '-30 days') WHERE id = ?", (cp["id"],))
    count = backfill_unassessed_checkpoints(ec_db, str(ec_repo), window_days=7)
    assert count == 0

def test_get_enrichment_candidates_only_rule_based(ec_repo, ec_db):
    session_id = _create_test_session(ec_db)
    cp = create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    create_assessment(ec_db, checkpoint_id=cp["id"], verdict="neutral", model_name="rule-based")
    create_assessment(ec_db, checkpoint_id=None, verdict="expand", model_name="gpt-4o-mini")
    candidates = get_enrichment_candidates(ec_db)
    assert len(candidates) == 1
    assert candidates[0]["model_name"] == "rule-based"
```

- [ ] **Step 2: Run tests, verify failure**
- [ ] **Step 3: Implement**

`backfill_unassessed_checkpoints(conn, repo_path, session_id=None, window_days=7)`:
- Query: `checkpoints LEFT JOIN assessments WHERE a.id IS NULL AND created_at >= window`
- Optional session_id filter, LIMIT 50
- For each: call `auto_assess_checkpoint()`, count successes

`get_enrichment_candidates(conn, session_id=None, window_days=7, limit=10)`:
- Query: `assessments a JOIN checkpoints c ON a.checkpoint_id = c.id WHERE a.model_name = 'rule-based' AND a.created_at >= window`
- Returns list of dicts with assessment + checkpoint info

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/core/auto_assess.py tests/test_auto_assess.py
git commit -m "feat(assess): backfill and enrichment candidate queries"
```

---

### Task 5: Git-evidence feedback

**Files:**
- Modify: `src/entirecontext/core/auto_assess.py`
- Test: `tests/test_auto_assess.py`

- [ ] **Step 1: Write failing test**

```python
def test_git_evidence_feedback(ec_repo, ec_db):
    session_id = _create_test_session(ec_db)
    cp = create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    create_assessment(ec_db, checkpoint_id=cp["id"], verdict="neutral", model_name="rule-based")
    # Make a commit after checkpoint
    subprocess.run(["git", "commit", "--allow-empty", "-m", "fix: something"], cwd=ec_repo, capture_output=True)
    count = apply_git_evidence_feedback(ec_db, str(ec_repo), session_id=session_id)
    assert count == 1
    row = ec_db.execute("SELECT feedback, feedback_reason FROM assessments WHERE checkpoint_id = ?", (cp["id"],)).fetchone()
    assert row["feedback"] == "agree"
    assert "committed" in row["feedback_reason"]
```

- [ ] **Step 2: Run tests, verify failure**
- [ ] **Step 3: Implement**

`apply_git_evidence_feedback(conn, repo_path, session_id=None, window_days=7)`:
- Query: assessments WHERE `feedback IS NULL AND model_name = 'rule-based'` AND within window
- For each: check `git log --format=%H {checkpoint_commit}..HEAD` returns commits
- If yes: `add_feedback(conn, a_id, "agree", feedback_reason="auto:committed")`
- Return count

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/core/auto_assess.py tests/test_auto_assess.py
git commit -m "feat(assess): git-evidence feedback for API-free environments"
```

---

### Task 6: LLM enrichment function

**Files:**
- Modify: `src/entirecontext/core/auto_assess.py`
- Test: `tests/test_auto_assess.py`

- [ ] **Step 1: Write failing test**

```python
def test_enrich_assessment_updates_model_name(ec_repo, ec_db, monkeypatch):
    session_id = _create_test_session(ec_db)
    cp = create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    a = create_assessment(ec_db, checkpoint_id=cp["id"], verdict="neutral", model_name="rule-based")

    # Mock LLM backend
    mock_response = json.dumps({"verdict": "expand", "impact_summary": "Added new feature", "roadmap_alignment": "Aligns with v0.8", "tidy_suggestion": "None"})
    monkeypatch.setattr("entirecontext.core.auto_assess.get_backend", lambda *a, **kw: type("B", (), {"complete": lambda s, sys, usr: mock_response})())

    config = {"futures": {"default_backend": "claude", "default_model": ""}}
    ok = enrich_assessment(ec_db, a, str(ec_repo), config)
    assert ok is True
    row = ec_db.execute("SELECT model_name, verdict, feedback, feedback_reason FROM assessments WHERE id = ?", (a["id"],)).fetchone()
    assert row["model_name"] != "rule-based"
    assert row["verdict"] == "expand"
    assert row["feedback"] == "disagree"
    assert "revised" in row["feedback_reason"]
```

- [ ] **Step 2: Run tests, verify failure**
- [ ] **Step 3: Implement**

`enrich_assessment(conn, assessment, repo_path, config)`:
1. Load backend from `config["futures"]["default_backend"]`
2. Build prompt: `ASSESS_SYSTEM_PROMPT` + ROADMAP.md + diff_summary
3. Call `backend.complete(system, user)`, parse JSON
4. Validate verdict against `VALID_VERDICTS`
5. Compare LLM verdict with `assessment["verdict"]` (rule-based)
6. UPDATE: verdict, impact_summary, roadmap_alignment, tidy_suggestion, `model_name=f"{backend_name}-cli"`
7. `add_feedback()`: `"agree"` + `"auto:llm-confirmed"` if same, `"disagree"` + `f"auto:revised:{old}->{new}"` if different
8. Return True/False, never raises

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/core/auto_assess.py tests/test_auto_assess.py
git commit -m "feat(assess): LLM enrichment with auto-feedback generation"
```

---

### Task 7: Config changes

**Files:**
- Modify: `src/entirecontext/core/config.py`
- Test: `tests/test_auto_assess.py`

- [ ] **Step 1: Write failing test**

```python
def test_config_defaults():
    from entirecontext.core.config import DEFAULT_CONFIG
    futures = DEFAULT_CONFIG["futures"]
    assert futures["default_backend"] == "claude"
    assert futures["assess_enrich"] is True
    assert futures["assess_backfill_window_days"] == 7
```

- [ ] **Step 2: Run tests, verify failure**
- [ ] **Step 3: Implement**

In `DEFAULT_CONFIG["futures"]`:
- Change `"default_backend": "openai"` → `"default_backend": "claude"`
- Add `"assess_enrich": True`
- Add `"assess_backfill_window_days": 7`

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Run existing config tests for regression**

Run: `uv run pytest tests/ -k "config" -v`

- [ ] **Step 6: Commit**

```bash
git add src/entirecontext/core/config.py tests/test_auto_assess.py
git commit -m "feat(config): add assess_enrich, backfill window; default backend to claude"
```

---

### Task 8: Tier 1 — hook wiring (post-commit + auto-checkpoint + CLI)

**Files:**
- Modify: `src/entirecontext/hooks/session_lifecycle.py`
- Modify: `src/entirecontext/cli/checkpoint_cmds.py`
- Test: `tests/test_distill_automation.py`

- [ ] **Step 1: Write integration test**

```python
def test_post_commit_creates_assessment(ec_repo, ec_db):
    """on_post_commit creates checkpoint AND assessment."""
    subprocess.run(["git", "commit", "--allow-empty", "-m", "feat: endpoint"], cwd=ec_repo, capture_output=True)
    on_post_commit({"cwd": str(ec_repo)})
    checkpoints = list_checkpoints(ec_db)
    assert len(checkpoints) >= 1
    cp_id = checkpoints[0]["id"]
    a = ec_db.execute("SELECT * FROM assessments WHERE checkpoint_id = ?", (cp_id,)).fetchone()
    assert a is not None
    assert a["model_name"] == "rule-based"
```

- [ ] **Step 2: Run test, verify failure**
- [ ] **Step 3: Wire Tier 1 into `on_post_commit()` (session_lifecycle.py:517)**

After `create_checkpoint()` call, capture return value and call `auto_assess_checkpoint()`.
Pattern: try/except wrapping, `_record_hook_warning` on failure.

- [ ] **Step 4: Wire Tier 1 into `_maybe_create_auto_checkpoint()` (session_lifecycle.py:459)**

Same pattern: capture `create_checkpoint()` return value, call `auto_assess_checkpoint()`.

- [ ] **Step 5: Wire Tier 1 into `checkpoint_cmds.py` CLI**

After `create_checkpoint()`, call `auto_assess_checkpoint()` and print verdict.

- [ ] **Step 6: Run integration test, verify pass**
- [ ] **Step 7: Run existing checkpoint/hook tests for regression**

Run: `uv run pytest tests/test_checkpoint_cmds.py tests/test_post_commit_hook.py tests/test_hooks.py -v`

- [ ] **Step 8: Commit**

```bash
git add src/entirecontext/hooks/session_lifecycle.py src/entirecontext/cli/checkpoint_cmds.py tests/test_distill_automation.py
git commit -m "feat(hooks): wire Tier 1 auto-assess into post-commit, auto-checkpoint, CLI"
```

---

### Task 9: Tier 2 — SessionEnd backfill + enrichment worker

**Files:**
- Modify: `src/entirecontext/hooks/session_lifecycle.py`
- Modify: `src/entirecontext/cli/futures_cmds.py`
- Test: `tests/test_distill_automation.py`

- [ ] **Step 1: Write integration tests**

```python
def test_session_end_backfills_unassessed(ec_repo, ec_db):
    session_id = _create_test_session(ec_db)
    cp = create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    # No assessment exists
    on_session_end({"session_id": session_id, "cwd": str(ec_repo)})
    a = ec_db.execute("SELECT * FROM assessments WHERE checkpoint_id = ?", (cp["id"],)).fetchone()
    assert a is not None

def test_enrichment_worker_launched_by_default(ec_repo, ec_db, monkeypatch):
    """assess_enrich=True by default, worker should launch."""
    launched = []
    monkeypatch.setattr("entirecontext.hooks.session_lifecycle.launch_worker", lambda *a, **kw: launched.append(1))
    monkeypatch.setattr("entirecontext.hooks.session_lifecycle.worker_status", lambda *a, **kw: {"running": False})
    session_id = _create_test_session(ec_db)
    create_checkpoint(ec_db, session_id, _get_head(ec_repo))
    on_session_end({"session_id": session_id, "cwd": str(ec_repo)})
    assert len(launched) >= 1
```

- [ ] **Step 2: Run tests, verify failure**
- [ ] **Step 3: Add `_maybe_backfill_assessments()` to session_lifecycle.py**

Insert after `_maybe_create_auto_checkpoint()` at line 280, before `_maybe_trigger_auto_sync()`.
Synchronous: backfill rule-based assessments + git-evidence feedback.
Async: launch `worker-assess` if `assess_enrich=True`.

- [ ] **Step 4: Add `futures enrich-backlog` CLI command**

New command in `futures_cmds.py` that the background worker runs:
- Load config, get enrichment candidates
- For each: call `enrich_assessment()`
- If LLM fails: fall back to `apply_git_evidence_feedback()`

- [ ] **Step 5: Run tests, verify pass**
- [ ] **Step 6: Commit**

```bash
git add src/entirecontext/hooks/session_lifecycle.py src/entirecontext/cli/futures_cmds.py tests/test_distill_automation.py
git commit -m "feat(hooks): Tier 2 SessionEnd backfill + async enrichment worker"
```

---

### Task 10: Tier 3 — SessionStart catch-up

**Files:**
- Modify: `src/entirecontext/hooks/session_lifecycle.py`
- Test: `tests/test_distill_automation.py`

- [ ] **Step 1: Write integration test**

```python
def test_session_start_catches_up(ec_repo, ec_db):
    # Simulate crashed session: checkpoint exists, no assessment, session ended
    old_session = _create_test_session(ec_db, ended=True)
    cp = create_checkpoint(ec_db, old_session, _get_head(ec_repo))
    # Start new session
    new_session = str(uuid4())
    on_session_start({"session_id": new_session, "cwd": str(ec_repo)})
    a = ec_db.execute("SELECT * FROM assessments WHERE checkpoint_id = ?", (cp["id"],)).fetchone()
    assert a is not None
    assert a["model_name"] == "rule-based"
```

- [ ] **Step 2: Run test, verify failure**
- [ ] **Step 3: Add `_maybe_catchup_assessments()` to on_session_start()**

At end of `on_session_start()` (after line 131), add catch-up call.
Only synchronous rule-based backfill (no LLM at SessionStart — keep it fast).
Scoped by `assess_backfill_window_days`.

- [ ] **Step 4: Run test, verify pass**
- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/hooks/session_lifecycle.py tests/test_distill_automation.py
git commit -m "feat(hooks): Tier 3 SessionStart catch-up for crashed sessions"
```

---

### Task 11: Dashboard enriched_rate

**Files:**
- Modify: `src/entirecontext/core/dashboard.py`
- Test: `tests/test_dashboard.py` (extend existing)

- [ ] **Step 1: Write failing test**

```python
def test_enriched_rate(ec_db):
    create_assessment(ec_db, verdict="neutral", model_name="rule-based")
    create_assessment(ec_db, verdict="expand", model_name="gpt-4o-mini")
    create_assessment(ec_db, verdict="neutral", model_name="mcp-agent")
    stats = get_dashboard_stats(ec_db)
    assert stats["assessments"]["enriched_rate"] == pytest.approx(2 / 3)
```

- [ ] **Step 2: Run test, verify failure**
- [ ] **Step 3: Implement**

Add to `get_dashboard_stats()` in the assessments section:

```python
enriched = conn.execute(
    "SELECT COUNT(*) FROM assessments WHERE model_name IS NOT NULL AND model_name != 'rule-based'"
).fetchone()[0]
total_a = conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0]
enriched_rate = enriched / total_a if total_a > 0 else 0.0
```

Add `"enriched_count": enriched, "enriched_rate": enriched_rate` to returned dict.

- [ ] **Step 4: Run test, verify pass**
- [ ] **Step 5: Run full dashboard tests**

Run: `uv run pytest tests/test_dashboard.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/entirecontext/core/dashboard.py tests/test_dashboard.py
git commit -m "feat(dashboard): add enriched_rate metric for assessment quality tracking"
```

---

### Task 12: Regression + full suite verification

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest --timeout=30 -x
```

- [ ] **Step 2: Lint**

```bash
uv run ruff check src/entirecontext/core/auto_assess.py src/entirecontext/core/git_utils.py src/entirecontext/hooks/session_lifecycle.py src/entirecontext/cli/checkpoint_cmds.py src/entirecontext/cli/futures_cmds.py src/entirecontext/core/dashboard.py src/entirecontext/core/config.py
uv run ruff format --check .
```

- [ ] **Step 3: Manual smoke test (use temp repo, not dogfooding DB)**

```bash
cd $(mktemp -d) && git init && git commit --allow-empty -m "init"
ec init
ec checkpoint create -m "test auto-assess"
ec futures list  # Should show rule-based assessment
ec dashboard     # Should show enriched_rate
```

- [ ] **Step 4: Verify maturity regression protection**

```bash
# In the real repo: compare maturity before/after
ec dashboard  # Record maturity_breakdown BEFORE
# Run a session cycle with auto-assess enabled
ec dashboard  # Verify distill did not decrease
```

- [ ] **Step 5: Verify sync import path excluded**

```bash
# sync/coordinator.py:372 must NOT call auto_assess_checkpoint
grep -n "auto_assess" src/entirecontext/sync/coordinator.py  # Should return nothing
```

- [ ] **Step 6: Commit any fixes, then final pass**

```bash
uv run pytest --timeout=30
```

---

## Verification Summary

| Check | Command |
|-------|---------|
| Unit tests | `uv run pytest tests/test_auto_assess.py -v` |
| Integration tests | `uv run pytest tests/test_distill_automation.py -v` |
| Checkpoint regression | `uv run pytest tests/test_checkpoint_cmds.py tests/test_post_commit_hook.py -v` |
| Hook regression | `uv run pytest tests/test_hooks.py tests/test_session_lifecycle_ordering.py -v` |
| Dashboard regression | `uv run pytest tests/test_dashboard.py -v` |
| Full suite | `uv run pytest --timeout=30` |
| Lint | `uv run ruff check . && uv run ruff format --check .` |
| Smoke test | `ec checkpoint create -m "test" && ec futures list && ec dashboard` |
