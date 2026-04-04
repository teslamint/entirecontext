# Decision Hooks — Auto-Detection, Extraction & Context Surfacing

**Date:** 2026-04-04
**Status:** Approved
**Scope:** hooks/decision_hooks.py, config, tests

## Summary

Add three decision-related hooks to EntireContext that automate the decision lifecycle:

1. **SessionStart** — Surface related and stale decisions as agent context
2. **SessionEnd (stale)** — Auto-detect stale decisions via git diff
3. **SessionEnd (extract)** — Hybrid keyword + LLM extraction of decisions from session turns

All hooks follow the existing `_maybe_*` pattern: config-gated, try/except wrapped, never crash the hook chain.

## Architecture

### New file

`src/entirecontext/hooks/decision_hooks.py` — all three hook functions.

Rationale: `session_lifecycle.py` is already 490 lines. Separate file follows the Architecture decision to separate responsibility boundaries (decision `7f791f28`).

### Integration points

```
handler.py
  SessionStart → session_lifecycle.on_session_start()
                   └── decision_hooks.on_session_start_decisions()

  SessionEnd   → session_lifecycle.on_session_end()
                   ├── ... (existing _maybe_* chain)
                   ├── decision_hooks.maybe_check_stale_decisions()
                   └── decision_hooks.maybe_extract_decisions()
```

`on_session_end()` calls the two new functions at the end of its `_maybe_*` chain. `on_session_start()` calls `on_session_start_decisions()` after session creation/resume.

### Config additions

```toml
[decisions]
auto_stale_check = false
auto_extract = false
show_related_on_start = false
extract_keywords = ["결정", "선택", "방식으로", "decided", "chose", "approach", "instead of"]
```

All default **off**. Added to `DEFAULT_CONFIG` in `core/config.py`.

## Hook 1: SessionStart — Related Decision Surfacing

### Function: `on_session_start_decisions(data) -> str | None`

Returns text to be included in hook stdout (agent context). Returns `None` when nothing to show.

**stdout contract (design assumption — to be validated):** The hook handler (`_handle_session_start`) will `print()` the returned string. The assumption is that Claude Code hooks capture stdout as `additionalContext` injected into the agent's system prompt. However, the current codebase has no prior example of SessionStart hooks producing stdout output (`handler.py:76` is a bare dispatch), and `docs/spec.md` does not formally define stdout injection semantics. This assumption MUST be validated during implementation:

1. Add an integration test that verifies `_handle_session_start` prints the return value to stdout
2. Manually verify that Claude Code surfaces the output as `additionalContext` in a real session
3. If stdout injection does not work, fall back to writing a `.entirecontext/decisions-context.md` file that agents can read via their file-reading tools

The Markdown format is deliberately agent-agnostic so that any agent receiving the text can parse it.

### Flow

1. Check config `decisions.show_related_on_start` — return if disabled
2. Run `git diff --name-only HEAD~5..HEAD` to get recently changed files (explicit range, not relative ref)
   - Falls back to `git log --name-only --pretty=format: -5` if diff fails (e.g. shallow clone with <5 commits)
3. Query `decision_files` table for decisions linked to those files
4. Query `list_decisions(staleness_status="stale")` for stale decisions
5. Deduplicate (a decision may appear in both sets)
6. Format as Markdown and return

### Output format (agent-agnostic)

```markdown
## Related Decisions

The following decisions are linked to recently changed files:

- [7f791f28] Architecture: Separate sync/MCP/cross-repo responsibility boundaries
  Status: fresh | Files: sync/coordinator.py, mcp/server.py
  Rationale: ...

## Stale Decisions (action needed)

- [629f4a79] Documentation: Emphasize product wedge over feature inventory
  Status: STALE | Changed: README.md (since 2026-03-11)
  Rationale: ...

Consider updating stale decisions or marking them as superseded.
```

- Markdown format — parseable by Claude, Codex, Gemini, Copilot
- 0 decisions → no output (no noise)
- Max 5 decisions (context budget)
- `git diff` failure → fallback to `git log`. Only if `git log` also fails → `_record_hook_warning`, return None

## Hook 2: SessionEnd — Stale Auto-Detection

### Function: `maybe_check_stale_decisions(repo_path: str) -> None`

### Flow

1. Check config `decisions.auto_stale_check` — return if disabled
2. `list_decisions(conn, staleness_status="fresh", limit=50)`
3. For each: `check_staleness(conn, decision_id, repo_path)`
4. If stale: `update_decision_staleness(conn, decision_id, "stale")`

### Constraints

- Limit 50 fresh decisions per run (performance)
- Each `check_staleness` runs `git log` subprocess — already has 10s timeout
- All exceptions caught → `_record_hook_warning(repo_path, "auto_stale_check", exc)`

## Hook 3: SessionEnd — Hybrid Decision Extraction (Background)

### Function: `maybe_extract_decisions(repo_path: str, session_id: str) -> None`

**Critical constraint:** SessionEnd hook timeout is **5 seconds** (`project_cmds.py:246`). LLM calls take 10-120 seconds. Therefore LLM extraction MUST run as a **background process**.

### Worker slot contention

The current `async_worker` uses a single `worker.pid` file per repo. `auto_embed` already occupies this slot (`session_lifecycle.py:458`). To avoid contention without over-engineering:

- **Use a named PID file**: `decision_hooks.py` uses `.entirecontext/worker-decision.pid` instead of the shared `worker.pid`. Introduce a `pid_name` parameter to `launch_worker` (or use a thin wrapper that writes to a decision-specific PID file).
- **Check decision-specific PID**: `worker_status` checks `.entirecontext/worker-decision.pid` only.
- This keeps the existing `auto_embed` worker unaffected and avoids building a full queue system (YAGNI).

### Idempotency

To prevent duplicate decision extraction when the hook re-fires or the worker retries:

- Before launching the background worker, check for an **extraction marker** in session metadata:
  `sessions.metadata` JSON field gets `"decisions_extracted": true` after successful extraction.
- The `extract-from-session` CLI command checks this marker at startup and exits early if already set.
- The marker is set AFTER all decisions are created (not before), so a crashed extraction can be retried.

### Flow

```
1. Config gate: decisions.auto_extract
2. Idempotency check:
   - SELECT metadata FROM sessions WHERE id = ?
   - If metadata contains "decisions_extracted": true → early return
3. Collect turn summaries (inline, fast — DB query only):
   SELECT assistant_summary FROM turns
   WHERE session_id = ? AND assistant_summary IS NOT NULL
   ORDER BY turn_number ASC
4. Keyword filter (1st pass, inline):
   - Compile config extract_keywords as regex pattern (OR-joined)
   - Match against each summary
   - 0 matches → early return (no background process spawned)
5. Check decision-specific worker status:
   - If worker-decision.pid is running → early return
6. Launch background worker:
   - launch to worker-decision.pid
   - Command: [sys.executable, "-m", "entirecontext.cli",
     "decision", "extract-from-session", session_id]
   - Returns immediately
```

### New CLI command: `ec decision extract-from-session <session_id>`

Runs in background. No hook timeout constraint.

```
1. Load config, open DB
2. Idempotency check (same as above — guard against race)
3. Collect turn summaries with files_touched data:
   SELECT assistant_summary, files_touched FROM turns
   WHERE session_id = ? AND assistant_summary IS NOT NULL
   ORDER BY turn_number ASC
4. Keyword filter (re-run, since this is a separate process)
5. LLM extraction:
   - Use existing futures.default_backend / futures.default_model
   - System prompt:
     "Extract architectural/technical decisions from this coding session.
      Return a JSON array: [{title, rationale, scope, rejected_alternatives}]
      Only include actual decisions (choosing one approach over another),
      not tasks, plans, or status updates.
      Return [] if no decisions were made."
   - Input: matched summaries joined with newlines
6. Parse JSON response:
   - Invalid JSON → log warning, exit
   - Empty array → mark extracted, exit
   - Truncate to max 5 items
7. For each extracted decision:
   - create_decision(conn, title=..., rationale=..., scope=...)
   - Auto-link files: collect all files_touched from session turns,
     call link_decision_to_file for each unique file path.
     This ensures auto-extracted decisions are discoverable by
     SessionStart relevance and stale checks.
   - On individual failure: skip, continue to next
8. Set idempotency marker (null-safe):
   - UPDATE sessions SET metadata = json_set(COALESCE(metadata, '{}'), '$.decisions_extracted', true)
     WHERE id = ?
```

### Safety guards

- Config default off
- Keyword gate prevents unnecessary background process spawns
- LLM call runs in background — never blocks hook chain
- Named PID file (`worker-decision.pid`) — no contention with auto_embed
- Idempotency marker prevents duplicate extraction on re-fire/retry
- Auto-linked files from `files_touched` — extracted decisions participate in lifecycle
- Max 5 decisions per session
- Invalid LLM response → warning, no crash
- LLM network failure → warning, no crash
- Each decision creation is independent — one failure doesn't block others

## Config Integration

In `core/config.py` `DEFAULT_CONFIG`:

```python
"decisions": {
    "auto_stale_check": False,
    "auto_extract": False,
    "show_related_on_start": False,
    "extract_keywords": [
        "결정", "선택", "방식으로",
        "decided", "chose", "approach", "instead of",
    ],
},
```

Follows TOML deep merge: defaults ← global config ← per-repo config.

## Test Strategy

### Test file: `tests/test_decision_hooks.py`

### SessionStart tests

| Case | Expected |
|------|----------|
| Changed files linked to decisions | Markdown output with Related Decisions section |
| Changed files, no linked decisions | None output |
| Stale decisions exist | Stale Decisions section included |
| Config disabled | None output, no DB/git calls |
| git diff failure | Fallback to git log |
| git log also fails | Warning recorded, None output |
| stdout output is printed by handler | Verify `_handle_session_start` prints non-None return |

### SessionEnd stale check tests

| Case | Expected |
|------|----------|
| Fresh decision, linked file changed | Status updated to stale |
| Fresh decision, no file changes | Status stays fresh |
| Config disabled | No DB queries |
| 0 decisions | Early return |

### SessionEnd LLM extraction tests

| Case | Expected |
|------|----------|
| 0 keyword matches | No background process spawned |
| Keywords match | Background worker launched to worker-decision.pid |
| Decision worker already running | Skip, no second worker |
| Embed worker running (different PID) | Decision worker still launches |
| Session already has decisions_extracted marker | Early return, no worker |
| CLI: LLM returns valid JSON | Decisions created + files auto-linked |
| CLI: LLM returns empty array | No decisions, marker still set |
| CLI: LLM returns invalid JSON | Warning logged, no marker set (retryable) |
| CLI: LLM call fails (network) | Warning logged, no marker set (retryable) |
| CLI: LLM returns >5 decisions | Only first 5 created |
| CLI: Same session extracted twice | Second run exits early (marker check) |
| CLI: files_touched present on turns | Linked to created decisions |
| CLI: files_touched empty | Decisions created without file links |

### Mock targets

- `subprocess.run` — git commands
- `LLM backend.complete()` — LLM calls
- DB — real SQLite via existing `ec_db` fixture

## Error Handling

All functions follow the existing `_maybe_*` contract:

```python
def maybe_check_stale_decisions(repo_path: str) -> None:
    try:
        # ... logic
    except Exception as exc:
        _record_hook_warning(repo_path, "auto_stale_check", exc)
```

**No decision hook function ever propagates exceptions.** Hook failure must never block session start/end.

## Files Changed

| File | Change |
|------|--------|
| `src/entirecontext/hooks/decision_hooks.py` | NEW — all 3 hook functions (SessionStart inline, SessionEnd stale inline, SessionEnd extract launches background via named PID) |
| `src/entirecontext/hooks/handler.py` | `_handle_session_start` prints `on_session_start_decisions()` return value to stdout when non-None |
| `src/entirecontext/hooks/session_lifecycle.py` | Add calls to `maybe_check_stale_decisions` and `maybe_extract_decisions` at end of `on_session_end` |
| `src/entirecontext/core/config.py` | Add `decisions` section to `DEFAULT_CONFIG` |
| `src/entirecontext/core/async_worker.py` | Add `pid_name` parameter to `launch_worker` / `worker_status` (or thin wrapper in decision_hooks.py) |
| `src/entirecontext/cli/decisions_cmds.py` | Add `extract-from-session` subcommand with idempotency check and auto file linking |
| `tests/test_decision_hooks.py` | NEW — test suite including idempotency, worker contention, and file linking tests |
