# v1.0 Release Plan — v0.10.0 Tag + Observation Gate + v1.0.0 Beta

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tag v0.10.0 for all unreleased code on main, verify auto_extract works in real sessions, then ship v1.0.0 as a status-only release (Alpha → Beta).

**Architecture:** Two-phase release. Phase 1 tags v0.10.0 on HEAD — this necessarily includes both the original v0.10.0 features (lesson surfacing, compact) AND the loop gate fixes (CLIBackend, auto_extract, Stop hook), since both are already merged to main. The CHANGELOG reflects this honestly. Phase 2 waits for the observation gate (3-5 sessions with auto-extracted candidates), then bumps to v1.0.0 with classifier/badge changes only — zero code delta between v0.10.0 and v1.0.0. Task 1 and Task 2 are parallel — observation runs during normal development regardless of the tag.

**Tech Stack:** Python 3.12+, uv, git tags, PyPI (OIDC), GitHub Releases

## Global Constraints

- `CHANGELOG.md` must have `[X.Y.Z] - YYYY-MM-DD` section before tagging (RELEASE_RULE.md)
- Codex pre-release review gate: run Codex review before tagging, fix all findings (RELEASE_RULE.md, retro 3-peat)
- Version must match in `pyproject.toml` AND `src/entirecontext/__init__.py`
- Tag format: `vX.Y.Z` (triggers `.github/workflows/release.yml`)
- Pre-release gate: `uv run ruff check .` + `uv run pytest` must pass
- README badge version must match pyproject.toml version
- PyPI is immutable — verify correctness before tagging

---

### Task 1: Tag v0.10.0 — all unreleased code

Tags HEAD with v0.10.0. HEAD contains both v0.10.0 features and loop gate fixes — the CHANGELOG covers both honestly. This is the "last pre-1.0" release.

**Files:**
- Modify: `pyproject.toml:3` — version bump
- Modify: `src/entirecontext/__init__.py:3` — version bump
- Modify: `CHANGELOG.md:8-22` — rename [Unreleased], add all missing entries
- Modify: `README.md:5` — badge version

**Interfaces:**
- Consumes: current `[Unreleased]` CHANGELOG section
- Produces: `v0.10.0` git tag triggering PyPI release

- [ ] **Step 1: Update pyproject.toml version**

```toml
version = "0.10.0"
```

- [ ] **Step 2: Update __init__.py version**

```python
__version__ = "0.10.0"
```

- [ ] **Step 3: Update README badge**

Replace:

```markdown
![Version 0.9.3](https://img.shields.io/badge/version-0.9.3-green)
```

With:

```markdown
![Version 0.10.0](https://img.shields.io/badge/version-0.10.0-green)
```

- [ ] **Step 4: Finalize CHANGELOG**

Replace `## [Unreleased]` and add a complete section covering ALL code on main since v0.9.3:

```markdown
## [Unreleased]

## [0.10.0] - 2026-06-29

The autonomous decision-memory loop (`capture→distill→retrieve→intervene→outcome`) now completes without human intervention. This release ships the full loop gate: auto_extract default-on, CLIBackend fix, Stop hook fallback, and retry cap.

### Added

- **Lesson surfacing: SessionStart** — broad-context surfacing with file-overlap ranking from checkpoint `files_snapshot`. Config gate `capture.surface_lessons_on_start` (default true).
- **Lesson surfacing: PDI** — narrow-context injection into `additionalContext`. Decisions take priority; lessons fill remaining token budget. Timeout-isolated (100ms) to never block decision output.
- **Git-evidence outcome inference: Layer 2** — `refined`/`replaced` classification via new-decision gate + diff pattern analysis. Config gate `decisions.infer_outcome_type` (default true).
- **Auto-apply lesson extension** — lesson/assessment file-overlap detection using checkpoint `files_snapshot` at SessionEnd. Drives `lesson_reuse_rate` for maturity 75.
- **`ec compact`** — storage compaction command: consolidate old turns, remove orphans, vacuum DB. Options: `--execute` (apply changes; default is dry-run), `--retention-days` (consolidate turns older than N days), `--limit` (max turns per run).
- **`auto_extract` default true** — decision candidate extraction runs automatically on SessionEnd and Stop hooks.
- **`ec decision reset-extraction-markers`** — clear stale extraction markers on sessions with zero candidates.
- **Extraction empty-draft warning** — `run_extraction` warns when bundles are collected but zero drafts parsed.
- **Stop hook extraction fallback** — `on_stop` triggers `maybe_extract_decisions` for sessions killed without `/exit`.
- **Extraction retry cap** — `extract_max_attempts` config (default 3) prevents unbounded extraction worker spawns when LLM is unavailable. Source-aware gating: Stop respects the cap, SessionEnd bypasses it.
- **Autonomous loop E2E wiring test** — `test_e2e_autonomous_loop.py` proves all five loop stages complete in-process.

### Fixed

- **CLIBackend JSON array unwrap** — `claude --output-format json` returns a JSON array; previous logic only handled dict envelope.
- **Markdown fence stripping** — `parse_llm_response` strips `` ```json `` fences before JSON parsing.
- **Lifecycle delegation resilience** — SessionEnd delegation moved into `finally` block.
- **compact VACUUM WAL** — VACUUM executes outside WAL mode; execute guard prevents concurrent runs.
- **Codex notify fork loop** — prevent infinite fork loop when codex notify hook re-invokes itself.

### Changed

- **Documentation surface refresh** — README/spec aligned with schema v14, CLI groups, 29-tool MCP surface.
- Performance test threshold: 250ms → 300ms.
- `.omc/RELEASE_RULE.md`: added Codex review pre-release gate.
```

- [ ] **Step 5: Run lint + test**

Run: `uv run ruff check . && uv run pytest -x -q`
Expected: All pass

- [ ] **Step 6: Codex pre-release review**

Run Codex review on the release commit. Fix all findings before proceeding to tag. (RELEASE_RULE.md gate — do not skip; this is a 3-sprint retro repeat.)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/entirecontext/__init__.py CHANGELOG.md README.md
git commit -m "chore(release): v0.10.0 — autonomous loop gate, lesson surfacing, compact

Includes: dual-channel lesson surfacing (SessionStart + PDI), Layer 2
git-evidence outcome inference, auto-apply lesson extension, ec compact,
auto_extract default true, CLIBackend JSON array unwrap, Stop hook
extraction fallback, extraction retry cap, E2E wiring test."
```

- [ ] **Step 8: Tag and push**

```bash
git tag v0.10.0
git push origin main --tags
```

Wait for CI to confirm release pipeline passes (lint → test → build → publish → release).

---

### Task 2: Observation gate — verify auto_extract in real sessions

Parallel with Task 1. `auto_extract` was flipped to default-true on 2026-06-29. The observation gate verifies that real sessions produce decision candidates via the Stop/SessionEnd hook path automatically.

**Files:**
- No code changes — manual verification

**Interfaces:**
- Consumes: `decision_candidates` table, `sessions.metadata` extraction_attempts field
- Produces: verified evidence that automatic extraction works in production

**Gate criteria:** At least 3 distinct ended sessions produce `decision_candidates` rows via the automatic hook path (not `ec decision extract-candidates` CLI). Evidence: `decision_candidates.created_at` timestamps after 2026-06-29, with `session_id` values matching sessions that ended naturally.

- [ ] **Step 1: Record baseline**

Run:

```bash
sqlite3 .entirecontext/db/local.db "SELECT COUNT(*) FROM decision_candidates"
```

Record the count (currently 1). All candidates above this baseline after the gate period are from automatic extraction.

- [ ] **Step 2: Continue normal development**

Each session that ends triggers:
1. `on_stop` → `maybe_extract_decisions(source="stop")` (capped at 3 attempts)
2. `on_session_end` → `maybe_extract_decisions(source="session_end")` (uncapped)

Expected timeline: 2-5 days of normal development produces 3+ qualifying sessions.

- [ ] **Step 3: Verify gate**

Run:

```sql
SELECT dc.session_id, COUNT(*) as candidates, MIN(dc.created_at) as first_extracted
FROM decision_candidates dc
JOIN sessions s ON s.id = dc.session_id
WHERE dc.created_at > '2026-06-29T00:00:00'
  AND s.ended_at IS NOT NULL
GROUP BY dc.session_id
ORDER BY first_extracted;
```

Gate passes when result has >= 3 rows.

If gate does not pass after 5+ ended sessions:
1. Check `sessions.metadata` for `extraction_attempts` values — confirms Stop hook fires
2. Check hook warnings: `sqlite3 .entirecontext/db/local.db "SELECT * FROM events WHERE event_type LIKE '%warn%' ORDER BY created_at DESC LIMIT 10"`
3. Escalate — may indicate LLM availability or session quality issue

---

### Task 3: v1.0.0 status-only release + Alpha → Beta

Execute ONLY after Task 2 gate passes. Zero code delta — only version, badge, classifier, and CHANGELOG changes.

**Files:**
- Modify: `pyproject.toml:3` — version to 1.0.0
- Modify: `pyproject.toml:12` — classifier to `4 - Beta`
- Modify: `src/entirecontext/__init__.py:3` — version to 1.0.0
- Modify: `README.md:5` — version badge + status badge
- Modify: `README.md:7` — remove experimental warning
- Modify: `CHANGELOG.md:8` — add v1.0.0 section
- Modify: `ROADMAP.md:277` — mark Alpha → Beta complete

**Interfaces:**
- Consumes: Task 2 gate evidence (3+ sessions with auto-extracted candidates)
- Produces: v1.0.0 release commit + tag

- [ ] **Step 1: Update pyproject.toml version**

```toml
version = "1.0.0"
```

- [ ] **Step 2: Update pyproject.toml classifier**

Replace:

```toml
    "Development Status :: 3 - Alpha",
```

With:

```toml
    "Development Status :: 4 - Beta",
```

- [ ] **Step 3: Update __init__.py version**

```python
__version__ = "1.0.0"
```

- [ ] **Step 4: Update README badges**

Replace:

```markdown
![Version 0.10.0](https://img.shields.io/badge/version-0.10.0-green) ![Status Experimental](https://img.shields.io/badge/status-experimental-orange)
```

With:

```markdown
![Version 1.0.0](https://img.shields.io/badge/version-1.0.0-green) ![Status Beta](https://img.shields.io/badge/status-beta-blue)
```

- [ ] **Step 5: Remove experimental warning from README**

Delete this line:

```markdown
> ⚠️ **Experimental** — API and data format may change without notice.
```

- [ ] **Step 6: Add CHANGELOG v1.0.0 section**

Insert after `## [Unreleased]`:

```markdown
## [1.0.0] - YYYY-MM-DD

Status-only release: promotes EntireContext from Alpha to Beta after confirming the autonomous decision-memory loop completes across real sessions without human intervention.

### Changed

- **Status: Alpha → Beta** — `Development Status :: 3 - Alpha` → `4 - Beta`. README badge updated from `experimental` to `beta`. Experimental warning removed.
```

Replace `YYYY-MM-DD` with the actual date when committing.

- [ ] **Step 7: Update ROADMAP**

Replace:

```markdown
- [ ] **Alpha → stable status** — flip README badge and pyproject classifier once production observability confirms loop completion across multiple real sessions
```

With:

```markdown
- [x] **Alpha → Beta status** — README badge, pyproject classifier, experimental warning removed. Production observability confirmed: auto_extract producing candidates across real sessions, 6+ full-loop sessions (retrieval + application + outcome).
```

- [ ] **Step 8: Run lint + test**

Run: `uv run ruff check . && uv run pytest -x -q`
Expected: All pass

- [ ] **Step 9: Codex pre-release review**

Run Codex review on the release commit. Fix all findings before tagging.

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml src/entirecontext/__init__.py README.md CHANGELOG.md ROADMAP.md
git commit -m "chore(release): v1.0.0 — Alpha → Beta

Production observability confirms the autonomous decision-memory loop
completes across real sessions. Promotes status from Alpha to Beta."
```

- [ ] **Step 11: Tag and push**

```bash
git tag v1.0.0
git push origin main --tags
```

Wait for CI pipeline: lint → test → build → publish → release → close-release-issues.

- [ ] **Step 12: Verify PyPI publication**

Check: `pip index versions entirecontext 2>/dev/null | head -3`

Expected: v1.0.0 listed.

---

## Dependency Graph

```
Task 1 (v0.10.0 tag) ─┐
                       ├→ Task 3 (v1.0.0 status-only release)
Task 2 (observation)  ─┘
```

Task 1 and Task 2 are parallel. Task 3 depends on both: v0.10.0 must be tagged (so the v1.0.0 CHANGELOG references it) AND the observation gate must pass.

## Self-Review Checklist

1. **Spec coverage:**
   - v0.10.0 CHANGELOG includes ALL code on main since v0.9.3 (loop gate + features) → Task 1 Step 4
   - Observation gate criteria (3+ sessions) → Task 2 Step 3
   - Version sync (pyproject + __init__ + README badge) → Task 1 Steps 1-3, Task 3 Steps 1-4
   - Classifier flip (Alpha → Beta) → Task 3 Step 2
   - ROADMAP update → Task 3 Step 7
   - Codex pre-release review → Task 1 Step 6, Task 3 Step 9
   - Tag + PyPI release → Task 1 Step 8, Task 3 Step 11

2. **Placeholder scan:** No TBDs. `YYYY-MM-DD` in Task 3 Step 6 is replaced at commit time.

3. **Type consistency:** Version string `"0.10.0"` in Task 1, `"1.0.0"` in Task 3 — used consistently across pyproject.toml, __init__.py, README badge.

4. **Code/CHANGELOG alignment:** v0.10.0 CHANGELOG covers all code on HEAD (including loop gate). v1.0.0 CHANGELOG is status-only (zero code delta). No mismatch between what the artifact contains and what the changelog claims.
