# v1.0 Loop Gate — auto_extract Verification & Autonomous Loop E2E

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `auto_extract` pipeline so it produces candidates in production, then prove the full `capture→distill→retrieve→intervene→outcome` loop completes autonomously in a single E2E test.

**Architecture:** Diagnostic-driven — three root causes found and fixed in dependency order: (1) CLIBackend fails to unwrap `claude --output-format json` array response, (2) LLM response often wrapped in markdown fences, (3) SessionEnd doesn't fire on process-kill sessions. The loop gate E2E test wires all five stages in-process with mocked LLM, serving as a wiring regression test.

**Tech Stack:** Python 3.12+, uv, SQLite (WAL), pytest, monkeypatch (no new deps)

## Diagnostic Summary (2026-06-29)

| Finding | Evidence | Root Cause |
|---------|----------|------------|
| `decision_candidates = 0` despite `auto_extract = true` locally | DB query: 0 rows | CLIBackend unwrap bug + trigger gap |
| `bundles=3, drafts=0` on manual extraction | CLI output | CLIBackend returns raw 52-item JSON array instead of unwrapped result string |
| CLIBackend `isinstance(data, dict)` fails | `claude --output-format json` returns `[{...}, ...]` not `{...}` | Unwrap logic assumes dict envelope; actual output is JSON array with `{"type":"result","result":"..."}` item |
| LLM result is markdown-fenced | Result: `` ```json\n[...]\n``` `` | `parse_llm_response` does not strip fences |
| Recent Claude sessions `ended_at = NULL` | Sessions `7d8b2a4c`, `019ee362` | Process killed without `/exit` → SessionEnd hook skipped |
| `auto_extract` default is `False` | config.py:77 | Only local override activates |

## Root Cause Chain

```
claude --output-format json
  → output = [{type:system,...}, {type:assistant,...}, ..., {type:result, result:"```json\n[...]\n```"}]
  → CLIBackend.complete():
      json.loads(output) → list (not dict)
      isinstance(data, dict) → False → skip unwrap
      return raw 52-item array string
  → parse_llm_response():
      json.loads(raw) → 52-item list
      for item in list: item.get("title") → None for all → drafts=0
      parsed_ok=True, no warnings
  → candidates_extracted marker set → permanently blocks re-extraction
```

## Global Constraints

- No new external dependencies
- All existing tests must pass
- LLM calls must be mockable in tests (never call real LLM in CI)
- Changes must be backward-compatible with existing per-repo config overrides
- Hook timeout budget: SessionEnd 5s total; extraction must not block

---

### Task 1: Fix CLIBackend JSON Array Unwrap

The `claude --output-format json` command returns a JSON array of event objects, not a single dict. The `result` is in the last item with `"type": "result"`. The current unwrap logic only handles dict responses.

**Files:**
- Modify: `src/entirecontext/core/llm.py:91-99`
- Test: `tests/test_llm_backend.py` (create)

**Interfaces:**
- Consumes: `subprocess.run` output from `claude --output-format json`
- Produces: `CLIBackend.complete()` returns the unwrapped result string (not the event array)

- [ ] **Step 1: Write the failing test**

```python
"""Tests for LLM backend output parsing."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from entirecontext.core.llm import CLIBackend


class TestCLIBackendClaude:
    """CLIBackend must unwrap claude --output-format json output."""

    def _make_claude_output(self, result_text: str) -> str:
        """Build a realistic claude --output-format json response."""
        events = [
            {"type": "system", "subtype": "init", "session_id": "test-123", "tools": []},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": result_text}]}},
            {"type": "result", "subtype": "success", "result": result_text, "session_id": "test-123"},
        ]
        return json.dumps(events)

    @patch("entirecontext.core.llm.subprocess.run")
    def test_unwraps_json_array_response(self, mock_run):
        """claude output is a JSON array; result is in the {type:result} item."""
        result_text = '[{"title": "Use Redis", "rationale": "faster"}]'
        mock_run.return_value = type("Result", (), {
            "returncode": 0,
            "stdout": self._make_claude_output(result_text),
            "stderr": "",
        })()

        backend = CLIBackend(command="claude")
        output = backend.complete("system prompt", "user text")

        assert output == result_text

    @patch("entirecontext.core.llm.subprocess.run")
    def test_unwraps_dict_response(self, mock_run):
        """Backward compat: dict envelope still works."""
        result_text = "[]"
        mock_run.return_value = type("Result", (), {
            "returncode": 0,
            "stdout": json.dumps({"result": result_text, "type": "result"}),
            "stderr": "",
        })()

        backend = CLIBackend(command="claude")
        output = backend.complete("system prompt", "user text")

        assert output == result_text

    @patch("entirecontext.core.llm.subprocess.run")
    def test_returns_raw_on_unparseable(self, mock_run):
        """If output is not valid JSON, return as-is."""
        mock_run.return_value = type("Result", (), {
            "returncode": 0,
            "stdout": "not json at all",
            "stderr": "",
        })()

        backend = CLIBackend(command="claude")
        output = backend.complete("system prompt", "user text")

        assert output == "not json at all"

    @patch("entirecontext.core.llm.subprocess.run")
    def test_codex_backend_passthrough(self, mock_run):
        """Codex backend should not apply claude unwrap logic."""
        mock_run.return_value = type("Result", (), {
            "returncode": 0,
            "stdout": "raw codex output",
            "stderr": "",
        })()

        backend = CLIBackend(command="codex")
        output = backend.complete("system prompt", "user text")

        assert output == "raw codex output"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm_backend.py -v`
Expected: `test_unwraps_json_array_response` FAILS — returns raw array instead of result

- [ ] **Step 3: Fix CLIBackend.complete() unwrap logic**

In `src/entirecontext/core/llm.py`, replace lines 91-99:

```python
        output = result.stdout.strip()
        # claude --output-format json wraps in JSON
        if self.command == "claude":
            try:
                data = json.loads(output)
                if isinstance(data, dict) and "result" in data:
                    return data["result"]
                if isinstance(data, list):
                    for item in reversed(data):
                        if isinstance(item, dict) and item.get("type") == "result" and "result" in item:
                            return item["result"]
            except json.JSONDecodeError:
                pass
        return output
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_backend.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/entirecontext/core/llm.py tests/test_llm_backend.py
git commit -m "fix: CLIBackend unwrap for claude JSON array output

claude --output-format json returns a JSON array of event objects,
not a single dict. The result text is in the item with type=result.
Previous logic only handled dict envelope, causing extraction to
silently receive the raw event array instead of the LLM response."
```

---

### Task 2: Strip Markdown Fences from LLM Response

The `claude` backend returns results wrapped in markdown fences (`` ```json\n...\n``` ``). `parse_llm_response` calls `json.loads()` which fails on fenced content. Add fence stripping before JSON parsing.

**Files:**
- Modify: `src/entirecontext/core/decision_extraction.py:576-583` (`parse_llm_response`)
- Test: `tests/test_decision_extraction.py` (add test)

**Interfaces:**
- Consumes: raw LLM response string (may be fenced)
- Produces: `parse_llm_response` handles fenced JSON input

- [ ] **Step 1: Write the failing test**

```python
# tests/test_decision_extraction.py — add to existing file

class TestParseFencedResponse:
    """parse_llm_response should handle markdown-fenced JSON."""

    def test_strips_json_fence(self):
        from entirecontext.core.decision_extraction import parse_llm_response, SignalBundle

        bundle = SignalBundle(
            source_type="session",
            source_id="s1",
            session_id="s1",
            checkpoint_id=None,
            assessment_id=None,
            text_blocks=["test"],
            files=["src/db.py"],
        )

        fenced = '```json\n[{"title": "Use WAL mode", "rationale": "concurrent reads", "scope": "database"}]\n```'
        drafts = parse_llm_response(fenced, bundle)

        assert len(drafts) == 1
        assert drafts[0].title == "Use WAL mode"

    def test_strips_plain_fence(self):
        from entirecontext.core.decision_extraction import parse_llm_response, SignalBundle

        bundle = SignalBundle(
            source_type="session",
            source_id="s1",
            session_id="s1",
            checkpoint_id=None,
            assessment_id=None,
            text_blocks=["test"],
            files=[],
        )

        fenced = '```\n[{"title": "Use WAL mode", "rationale": "concurrent reads", "scope": "database"}]\n```'
        drafts = parse_llm_response(fenced, bundle)

        assert len(drafts) == 1

    def test_handles_unfenced_json(self):
        from entirecontext.core.decision_extraction import parse_llm_response, SignalBundle

        bundle = SignalBundle(
            source_type="session",
            source_id="s1",
            session_id="s1",
            checkpoint_id=None,
            assessment_id=None,
            text_blocks=["test"],
            files=[],
        )

        raw = '[{"title": "Use WAL mode", "rationale": "concurrent reads", "scope": "database"}]'
        drafts = parse_llm_response(raw, bundle)

        assert len(drafts) == 1
```

- [ ] **Step 2: Run tests to verify the fenced ones fail**

Run: `uv run pytest tests/test_decision_extraction.py::TestParseFencedResponse -v`
Expected: `test_strips_json_fence` and `test_strips_plain_fence` FAIL

- [ ] **Step 3: Add fence stripping to parse_llm_response**

In `src/entirecontext/core/decision_extraction.py`, modify `parse_llm_response`:

```python
def parse_llm_response(raw: str, bundle: SignalBundle) -> list[CandidateDraft]:
    if raw is None:
        raise DecisionExtractionError("llm returned None")
    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        # Remove first line (```json or ```) and last line (```)
        if lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError) as exc:
        raise DecisionExtractionError(f"llm output is not valid JSON: {exc}") from exc
    # ... rest unchanged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decision_extraction.py::TestParseFencedResponse -v`
Expected: All PASS

- [ ] **Step 5: Run full extraction tests**

Run: `uv run pytest tests/test_decision_extraction.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/entirecontext/core/decision_extraction.py tests/test_decision_extraction.py
git commit -m "fix: strip markdown fences from LLM extraction response

claude backend returns results wrapped in \`\`\`json fences.
parse_llm_response now strips these before JSON parsing."
```

---

### Task 3: Extraction Observability — Warn on Empty Drafts

Add a warning when bundles are collected but zero drafts are parsed, making the `bundles=3, drafts=0` scenario visible. Also clear stale `candidates_extracted` markers on previously-broken sessions so they can be re-extracted.

**Files:**
- Modify: `src/entirecontext/core/decision_extraction.py:1138` (add warning after bundle loop)
- Test: `tests/test_decision_extraction.py` (add test)

**Interfaces:**
- Consumes: `ExtractionOutcome` dataclass
- Produces: `ExtractionOutcome.warnings` populated when bundles > 0 but drafts == 0

- [ ] **Step 1: Write the failing test**

```python
# tests/test_decision_extraction.py — add to existing file

class TestExtractionEmptyDraftWarning:
    """run_extraction should warn when bundles collected but no drafts."""

    def test_warns_on_empty_drafts(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.core.decision_extraction import run_extraction
        from entirecontext.core.session import create_session
        from entirecontext.core.turn import create_turn

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id)
        turn = create_turn(
            ec_db,
            session_id=session["id"],
            turn_number=1,
            user_message="should we use Redis?",
            assistant_summary="We decided to use Redis for caching",
            turn_status="completed",
        )
        ec_db.execute(
            "UPDATE turns SET files_touched = ? WHERE id = ?",
            (json.dumps(["src/cache.py"]), turn["id"]),
        )
        ec_db.commit()

        monkeypatch.setattr(
            "entirecontext.core.decision_extraction.call_extraction_llm",
            lambda text, repo, source_type="session": "[]",
        )

        outcome = run_extraction(ec_db, session["id"], str(ec_repo))

        assert outcome.bundles_collected > 0
        assert outcome.drafts_parsed == 0
        assert any("no_drafts" in w for w in outcome.warnings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decision_extraction.py::TestExtractionEmptyDraftWarning -v`
Expected: FAIL

- [ ] **Step 3: Add warning in run_extraction**

In `src/entirecontext/core/decision_extraction.py`, after the bundle loop (before the `if outcome.parsed_ok:` check):

```python
    if outcome.bundles_collected > 0 and outcome.drafts_parsed == 0:
        outcome.warnings.append(
            f"no_drafts: {outcome.bundles_collected} bundles collected but 0 drafts parsed"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_decision_extraction.py::TestExtractionEmptyDraftWarning -v`
Expected: PASS

- [ ] **Step 5: Run full extraction tests**

Run: `uv run pytest tests/test_decision_extraction.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/entirecontext/core/decision_extraction.py tests/test_decision_extraction.py
git commit -m "fix: warn when extraction collects bundles but produces no drafts

Previous behavior silently succeeded with bundles=3, drafts=0 and
no warnings, making production debugging impossible."
```

---

### Task 4: Clear Stale Extraction Markers

Sessions previously processed by the broken CLIBackend have `candidates_extracted = true` markers but zero actual candidates. These markers permanently block re-extraction. Add a CLI command to clear stale markers, and clear them for this repo.

**Files:**
- Modify: `src/entirecontext/cli/decisions_cmds.py` (add `decision reset-extraction-markers` command)
- Test: `tests/test_decision_extraction.py` (add test for marker clearing)

**Interfaces:**
- Consumes: `sessions.metadata` JSON field with `candidates_extracted` key
- Produces: CLI command that clears markers on sessions with 0 candidates

- [ ] **Step 1: Write the failing test**

```python
# tests/test_decision_extraction.py — add

class TestClearStaleMarkers:
    """Clearing stale extraction markers allows re-extraction."""

    def test_clears_marker_on_session_with_no_candidates(self, ec_repo, ec_db):
        from entirecontext.core.decision_extraction import (
            is_session_extracted,
            mark_session_extracted,
            clear_stale_extraction_markers,
        )
        from entirecontext.core.session import create_session

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id)

        mark_session_extracted(ec_db, session["id"])
        assert is_session_extracted(ec_db, session["id"]) is True

        count = clear_stale_extraction_markers(ec_db)

        assert count == 1
        assert is_session_extracted(ec_db, session["id"]) is False

    def test_preserves_marker_on_session_with_candidates(self, ec_repo, ec_db):
        from entirecontext.core.decision_extraction import (
            is_session_extracted,
            mark_session_extracted,
            clear_stale_extraction_markers,
        )
        from entirecontext.core.session import create_session

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id)

        mark_session_extracted(ec_db, session["id"])

        # Insert a candidate linked to this session
        ec_db.execute(
            "INSERT INTO decision_candidates "
            "(id, session_id, title, rationale, confidence_score, status) "
            "VALUES (?, ?, 'test', 'test', 0.5, 'pending')",
            ("cand-1", session["id"]),
        )
        ec_db.commit()

        count = clear_stale_extraction_markers(ec_db)

        assert count == 0
        assert is_session_extracted(ec_db, session["id"]) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decision_extraction.py::TestClearStaleMarkers -v`
Expected: FAIL — `clear_stale_extraction_markers` not defined

- [ ] **Step 3: Implement clear_stale_extraction_markers**

In `src/entirecontext/core/decision_extraction.py`, add:

```python
def clear_stale_extraction_markers(conn) -> int:
    """Clear candidates_extracted markers on sessions with zero candidates.

    Returns count of markers cleared.
    """
    rows = conn.execute(
        "SELECT id, metadata FROM sessions WHERE metadata IS NOT NULL"
    ).fetchall()

    cleared = 0
    for row in rows:
        meta_raw = row["metadata"]
        if not meta_raw:
            continue
        try:
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(meta, dict) or not meta.get("candidates_extracted"):
            continue

        candidate_count = conn.execute(
            "SELECT COUNT(*) FROM decision_candidates WHERE session_id = ?",
            (row["id"],),
        ).fetchone()[0]

        if candidate_count == 0:
            meta.pop("candidates_extracted", None)
            conn.execute(
                "UPDATE sessions SET metadata = ? WHERE id = ?",
                (json.dumps(meta), row["id"]),
            )
            cleared += 1

    conn.commit()
    return cleared
```

- [ ] **Step 4: Add CLI command**

In `src/entirecontext/cli/decisions_cmds.py`, add:

```python
@decision_app.command("reset-extraction-markers")
def decision_reset_extraction_markers():
    """Clear stale extraction markers on sessions with zero candidates."""
    conn, repo_path = get_repo_connection()
    try:
        from ..core.decision_extraction import clear_stale_extraction_markers

        count = clear_stale_extraction_markers(conn)
        console.print(f"[green]Cleared {count} stale extraction marker(s)[/green]")
    finally:
        conn.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_decision_extraction.py::TestClearStaleMarkers -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All pass

- [ ] **Step 7: Clear stale markers on this repo**

Run: `uv run ec decision reset-extraction-markers`
Expected: Clears the marker on session `7d8b2a4c`

- [ ] **Step 8: Commit**

```bash
git add src/entirecontext/core/decision_extraction.py src/entirecontext/cli/decisions_cmds.py tests/test_decision_extraction.py
git commit -m "feat: add reset-extraction-markers command for stale marker cleanup

Sessions processed by the broken CLIBackend had candidates_extracted=true
but zero actual candidates, permanently blocking re-extraction."
```

---

### Task 5: Production Verification — Real Extraction Produces Candidates

With Tasks 1-4 complete (CLIBackend fixed, fences stripped, markers cleared), re-run extraction on a real session and verify candidates are produced. This is the ROADMAP gate: "confirm SessionEnd → background worker → decision_candidates path produces candidates."

**Files:**
- No code changes — manual verification

**Interfaces:**
- Consumes: fixed CLIBackend, cleared markers
- Produces: `decision_candidates` with `inserted > 0`

- [ ] **Step 1: Re-run extraction on the previously-broken session**

Run: `uv run ec decision extract-candidates --session 7d8b2a4c-2bb1-442a-a78e-54b3ea3a0949`
Expected: `bundles=N drafts=M inserted=K` where K > 0

If `inserted=0`, check warnings. If `candidates_extracted` marker blocks it, run `uv run ec decision reset-extraction-markers` first.

- [ ] **Step 2: Verify candidates in DB**

Run: `sqlite3 .entirecontext/db/local.db "SELECT id, title, confidence_score, status FROM decision_candidates LIMIT 5"`
Expected: At least one row with `status=pending`

- [ ] **Step 3: Record verification result**

If Step 1 produces candidates: gate met. If not: investigate warnings and iterate (out of scope for this plan — escalate).

---

### Task 6: Flip `auto_extract` Default to True

Only after Task 5 confirms candidates are produced on real sessions.

**Files:**
- Modify: `src/entirecontext/core/config.py:77`
- Modify: `tests/test_decision_hooks.py:23` (update default assertion)
- Modify: `ROADMAP.md:274`

**Interfaces:**
- Consumes: `DEFAULT_CONFIG["decisions"]["auto_extract"]`
- Produces: extraction enabled by default

- [ ] **Step 1: Update assertion test**

In `tests/test_decision_hooks.py`, find the assertion for `auto_extract` default and change `False` to `True`.

- [ ] **Step 2: Flip the default**

In `src/entirecontext/core/config.py:77`:

```python
"auto_extract": True,
```

- [ ] **Step 3: Update ROADMAP**

In `ROADMAP.md:274`:

```markdown
- [x] **`auto_extract` default true** — CLIBackend unwrap bug fixed, markdown fence stripping added, stale markers cleared, production verification confirmed candidates produced
```

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/entirecontext/core/config.py tests/test_decision_hooks.py ROADMAP.md
git commit -m "feat: flip auto_extract default to true

Production verified: CLIBackend unwrap bug fixed (JSON array response),
markdown fence stripping added, stale extraction markers cleared.
Manual extraction on real session produced candidates. Closes ROADMAP
v1.0 prerequisite."
```

---

### Task 7: SessionEnd Resilience — Extract on Stop Hook as Fallback

**Files:**
- Modify: `src/entirecontext/hooks/session_lifecycle.py` (add extraction call in Stop path)
- Test: `tests/test_session_lifecycle.py`

**Interfaces:**
- Consumes: `_maybe_extract_decisions(repo_path, session_id)` from session_lifecycle
- Produces: extraction triggered on Stop when session has enough turns

**Design note:** `maybe_extract_decisions` sets the `candidates_extracted` marker after first successful extraction. Calling it on Stop means extraction runs on a session prefix if the session continues. This is acceptable: (a) the marker prevents re-extraction of the same session, (b) decisions made in the first N turns are captured, (c) if SessionEnd later fires, the marker skip is correct since those turns are already processed, (d) a new session starts fresh. For sessions killed without SessionEnd, this is strictly better than no extraction at all.

- [ ] **Step 1: Verify `on_stop` exists and its signature**

Run: `grep -n "def on_stop" src/entirecontext/hooks/session_lifecycle.py`

Note the function signature and where extraction should be added.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_session_lifecycle.py — add

class TestStopHookExtraction:
    """Stop hook triggers extraction as SessionEnd fallback."""

    def test_stop_triggers_extraction(self, ec_repo, ec_db, monkeypatch):
        from entirecontext.hooks.session_lifecycle import on_stop
        from entirecontext.core.session import create_session
        from entirecontext.core.turn import create_turn

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        session = create_session(ec_db, project_id)
        for i in range(4):
            turn = create_turn(
                ec_db,
                session_id=session["id"],
                turn_number=i + 1,
                user_message=f"msg {i}",
                assistant_summary="We decided to use Redis" if i == 0 else f"done {i}",
                turn_status="completed",
            )
            ec_db.execute(
                "UPDATE turns SET files_touched = ? WHERE id = ?",
                (json.dumps(["src/cache.py"]), turn["id"]),
            )
        ec_db.commit()

        extracted = []
        monkeypatch.setattr(
            "entirecontext.hooks.session_lifecycle._maybe_extract_decisions",
            lambda repo, sid: extracted.append(sid),
        )

        on_stop({"session_id": session["id"], "cwd": str(ec_repo)})

        assert session["id"] in extracted
```

- [ ] **Step 3: Add extraction call in on_stop**

Add `_maybe_extract_decisions(repo_path, session_id)` at the end of `on_stop`, after existing logic. The existing gates inside `maybe_extract_decisions` (config check, noise gate, keyword gate, marker, worker-running) handle all filtering.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_session_lifecycle.py::TestStopHookExtraction -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/entirecontext/hooks/session_lifecycle.py tests/test_session_lifecycle.py
git commit -m "fix: trigger extraction on Stop hook as SessionEnd fallback

Claude Code sessions often terminate via process kill without /exit,
skipping SessionEnd entirely. Calling maybe_extract_decisions on Stop
ensures extraction triggers for qualifying sessions. The function is
idempotent (marker + worker guard)."
```

---

### Task 8: Autonomous Loop E2E Wiring Test

A mocked E2E test that proves all five stages (`capture→distill→retrieve→intervene→outcome`) are mechanically wired and complete in-process. LLM is mocked — this is a wiring regression test, not a production observability proof.

**Files:**
- Create: `tests/test_e2e_autonomous_loop.py`

**Interfaces:**
- Consumes: `create_session`, `create_turn`, `auto_assess_checkpoint`, `run_extraction`, `rank_related_decisions`, `infer_applied_decisions`, `create_decision`, `link_decision_to_file`, `get_decision`
- Produces: proof that all five stages complete without human intervention

- [ ] **Step 1: Write the E2E test**

```python
"""E2E wiring test: capture→distill→retrieve→intervene→outcome.

Proves the v1.0 loop gate mechanically: all five stages complete in-process
without human intervention. LLM mocked; everything else runs through real
business logic. This is a wiring regression test, not a production proof.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest

from entirecontext.core.auto_apply import infer_applied_decisions
from entirecontext.core.auto_assess import auto_assess_checkpoint
from entirecontext.core.decisions import (
    create_decision,
    get_decision,
    link_decision_to_file,
    rank_related_decisions,
    _load_ranking_weights,
)
from entirecontext.core.session import create_session
from entirecontext.core.turn import create_turn


def _write_repo_config(repo: Path, body: str) -> None:
    cfg = repo / ".entirecontext" / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(body, encoding="utf-8")


_MOCK_LLM_RESPONSE = json.dumps([
    {
        "title": "Use SQLite WAL mode for concurrent reads",
        "rationale": "WAL allows readers and writers to operate concurrently",
        "scope": "database",
        "rejected_alternatives": [
            {"alternative": "Default journal mode", "reason": "Blocks concurrent readers"}
        ],
    }
])


class TestAutonomousLoopE2E:
    """Wiring test: all five loop stages complete in-process."""

    def test_full_loop(self, ec_repo, ec_db, monkeypatch):
        repo_path = str(ec_repo)

        _write_repo_config(ec_repo, "\n".join([
            "[decisions]",
            "auto_extract = true",
            "infer_applied_on_session_end = true",
            "infer_outcome_type = true",
            "",
            "[decisions.ranking]",
            "file_exact_weight = 10.0",
        ]))

        (ec_repo / "src").mkdir(exist_ok=True)
        (ec_repo / "src" / "db.py").write_text("# database module\n")
        subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feat: add WAL mode"],
            cwd=repo_path, capture_output=True,
        )
        commit_hash = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path, capture_output=True, text=True,
        ).stdout.strip()

        project_id = ec_db.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]

        # ── CAPTURE ──
        session1 = create_session(ec_db, project_id)
        for i, (user, assistant) in enumerate([
            ("How should we configure SQLite?", "We decided to use WAL mode"),
            ("What about the journal?", "WAL lets readers not block writers"),
            ("Update src/db.py", "Updated src/db.py with WAL pragma"),
        ], 1):
            turn = create_turn(
                ec_db,
                session_id=session1["id"],
                turn_number=i,
                user_message=user,
                assistant_summary=assistant,
                turn_status="completed",
            )
            ec_db.execute(
                "UPDATE turns SET files_touched = ?, tools_used = ? WHERE id = ?",
                (json.dumps(["src/db.py"]), json.dumps(["Edit"]), turn["id"]),
            )
        ec_db.commit()

        cp_id = str(uuid.uuid4())
        ec_db.execute(
            "INSERT INTO checkpoints (id, session_id, git_commit_hash, diff_summary) "
            "VALUES (?, ?, ?, ?)",
            (cp_id, session1["id"], commit_hash, "src/db.py | 3 +++"),
        )
        ec_db.commit()

        # ── DISTILL ──
        assessment = auto_assess_checkpoint(ec_db, cp_id, repo_path, session1["id"])
        assert assessment is not None

        monkeypatch.setattr(
            "entirecontext.core.decision_extraction.call_extraction_llm",
            lambda text, repo, source_type="session": _MOCK_LLM_RESPONSE,
        )

        from entirecontext.core.decision_extraction import run_extraction

        extraction = run_extraction(ec_db, session1["id"], repo_path)
        assert extraction.candidates_inserted > 0, (
            f"Expected candidates, got: {extraction.__dict__}"
        )

        # Confirm candidate → decision
        candidate = ec_db.execute(
            "SELECT id, title, rationale, scope FROM decision_candidates "
            "WHERE status = 'pending' LIMIT 1"
        ).fetchone()
        assert candidate is not None

        decision = create_decision(
            ec_db,
            title=candidate["title"],
            rationale=candidate["rationale"] or "",
            scope=candidate["scope"] or "",
        )
        decision_id = decision["id"]
        ec_db.execute(
            "UPDATE decision_candidates SET status = 'confirmed', decision_id = ? WHERE id = ?",
            (decision_id, candidate["id"]),
        )
        ec_db.commit()

        link_decision_to_file(ec_db, decision_id, "src/db.py")

        # ── RETRIEVE ──
        from entirecontext.core.config import load_config

        config = load_config(repo_path)
        weights = _load_ranking_weights(config)

        ranked = rank_related_decisions(ec_db, changed_files=["src/db.py"], weights=weights)
        assert any(r["id"] == decision_id for r in ranked), (
            f"Decision {decision_id} not found in ranked: {[r['id'] for r in ranked]}"
        )

        # Simulate retrieval_selection (what PDI does)
        selection_id = str(uuid.uuid4())
        session2 = create_session(ec_db, project_id)
        ec_db.execute(
            "INSERT INTO retrieval_selections "
            "(id, session_id, result_type, result_id, rank, score) "
            "VALUES (?, ?, 'decision', ?, 1, 10.0)",
            (selection_id, session2["id"], decision_id),
        )
        ec_db.commit()

        # ── INTERVENE ──
        turn2 = create_turn(
            ec_db,
            session_id=session2["id"],
            turn_number=1,
            user_message="Optimize WAL checkpoint interval",
            assistant_summary="Set WAL auto-checkpoint to 1000 pages",
            turn_status="completed",
        )
        ec_db.execute(
            "UPDATE turns SET files_touched = ?, tools_used = ? WHERE id = ?",
            (json.dumps(["src/db.py"]), json.dumps(["Edit"]), turn2["id"]),
        )
        ec_db.commit()

        # ── OUTCOME ──
        result = infer_applied_decisions(ec_db, session2["id"], repo_path=repo_path)
        assert result["applied_count"] > 0, f"No applications inferred: {result}"

        outcomes = ec_db.execute(
            "SELECT outcome_type FROM decision_outcomes WHERE decision_id = ?",
            (decision_id,),
        ).fetchall()
        assert any(o["outcome_type"] == "accepted" for o in outcomes), (
            f"Expected 'accepted', got: {[o['outcome_type'] for o in outcomes]}"
        )
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_e2e_autonomous_loop.py -v`
Expected: PASS

- [ ] **Step 3: Run all E2E tests**

Run: `uv run pytest tests/test_e2e_feed_the_loop.py tests/test_e2e_autonomous_loop.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_autonomous_loop.py
git commit -m "test: E2E wiring test — capture→distill→retrieve→intervene→outcome

Proves all five loop stages complete in-process without human
intervention. LLM mocked; this is a wiring regression test, not
a production observability proof."
```

---

### Task 9: Full Suite + ROADMAP Final Update

**Files:**
- Modify: `ROADMAP.md`

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All pass, zero failures

- [ ] **Step 2: Update ROADMAP**

```markdown
## v1.0 — Loop Completes Autonomously

Qualitative gate: the `capture→distill→retrieve→intervene→outcome` loop completes without human intervention and is repeatably observable across sessions.

- [x] **`auto_extract` default true** — CLIBackend unwrap bug fixed, markdown fence stripping added, stale markers cleared, production verification confirmed candidates produced
- [x] **Git-evidence-based outcome inference** — shipped in v0.10.0
- [x] **Autonomous loop E2E wiring test** — `test_e2e_autonomous_loop.py` proves all five stages complete in-process
- [ ] **Alpha → stable status** — flip README badge and pyproject classifier once production observability confirms loop completion across multiple real sessions
```

- [ ] **Step 3: Commit**

```bash
git add ROADMAP.md
git commit -m "docs: update ROADMAP — v1.0 loop gate prerequisites met"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - CLIBackend unwrap bug → Task 1 (root cause fix)
   - Markdown fence stripping → Task 2
   - Empty-draft observability → Task 3
   - Stale marker cleanup → Task 4
   - Production verification → Task 5 (manual, gate-blocking)
   - auto_extract default flip → Task 6 (only after Task 5 succeeds)
   - SessionEnd fallback → Task 7
   - Loop E2E wiring test → Task 8
   - ROADMAP update → Task 9

2. **Placeholder scan:** No TBDs, TODOs, or "implement later".

3. **Type consistency:** `clear_stale_extraction_markers(conn) -> int` used consistently.

4. **Gate ordering:** Default flip (Task 6) happens ONLY after production verification (Task 5) confirms candidates produced. The ROADMAP `[x]` is justified by actual evidence.

## Dependency Graph

```
Task 1 (CLIBackend fix) ─┐
Task 2 (fence strip) ────┤
Task 3 (observability) ──┼→ Task 4 (clear markers) → Task 5 (verify) → Task 6 (flip default)
                          │
Task 7 (Stop fallback) ──┘
Task 8 (E2E test) ───────→ Task 9 (ROADMAP)
```

Tasks 1-3 are independent and can run in parallel. Task 4 depends on 1-3. Task 5 depends on 4. Task 6 depends on 5. Tasks 7-8 are independent of 1-6.

## Framing Note

Task 5 is a manual production verification, not an automated test. If it fails (insertion=0), the plan does not proceed to Task 6. The failure would require debugging the actual LLM interaction (prompt quality, model capability), which is outside this plan's scope. Task 8's E2E test uses a mocked LLM and serves as a wiring regression — it does not substitute for production verification.
