# Redesign Direction: Loop-First Architecture

Date: 2026-06-21
Method: EC decision/lesson/assessment ledger analysis → code-review → Architect expert (GPT via Codex)

## Bottom Line

The loudest signal across 6 retrospectives (v0.6.0–v0.9.3) is not "split the big file" — it's that **the core loop (capture→distill→retrieve→intervene→outcome) doesn't close by default**. Every stage exists as code but requires manual config toggling or CLI invocation. Nothing measures whether the loop fired. The system designed to track decisions doesn't use its own lifecycle fields (all 50 decisions `staleness_status=fresh`, every `superseded_by_id=null`).

Primary recommendation: add a loop health contract, then decompose `decisions.py` along loop-stage boundaries. This is a Medium effort, not a rewrite.

## Evidence: Recurring Pain Points (6 retros)

| # | Pattern | Occurrences | Root Cause |
|---|---------|-------------|------------|
| 1 | distill=0 (auto-assess not firing) | 4 cycles (v0.6.0–v0.7.0) | `auto_extract=false` for 2 months; code existed, wasn't enabled |
| 2 | Codex shift-left missed | 3 consecutive | Will-based process change; no structural enforcement |
| 3 | Decision lifecycle fields unused | All 50 decisions | Staleness/supersession machinery never exercised |
| 4 | Measurement infrastructure broke | 3 times | ended_at NULL (175/290), rate formula unreachable, unstable metrics |
| 5 | Doc/code contract drift | Persistent | `__version__` 5 releases behind, MCP stale after uv sync |
| 6 | decisions.py God module | Continuous | 1878 lines, 58 functions, 5 responsibility areas mixed |

Source: EC decision ledger (50 decisions), MEMORY retrospectives, direct code analysis.

## Evidence: Source Code Hotspots

| File | Lines | Functions | Classes | Issue |
|------|-------|-----------|---------|-------|
| `core/decisions.py` | 1878 | 58 | 3 | God module: staleness + quality + CRUD + ranking(660L) + search + normalization |
| `core/decision_extraction.py` | 1142 | 37 | 7 | Complex extraction pipeline |
| `cli/decisions_cmds.py` | 965 | — | — | Thick CLI layer |
| `hooks/decision_hooks.py` | 929 | — | — | Policy logic in hook package |
| `hooks/session_lifecycle.py` | 731 | 23 | — | 13 `_maybe_*` wrappers mix dispatch + business logic |
| `mcp/tools/decisions.py` | 668 | — | — | MCP surface |

Decision-related code = ~6,432 lines = **27% of total source** (23,969 lines).

MCP boilerplate: 29+ instances of `resolve_repo()` + `try/finally/conn.close()`. `repos is not None and repos != ""` in 6+ locations.

## Meta-Problem: Why the Loop Doesn't Close

Each stage is implemented as **optional side effects** behind independent config flags and manual CLI invocations. The architecture has "features that can run," not "a session lifecycle that must progress through observable stages."

```
Current: SessionEnd → 13 _maybe_*() → each checks own config flag → silently skips
Missing: no record of "distill skipped because config disabled" vs "distill failed" vs "distill ran"
```

The structural fix: a **loop-stage contract** where every lifecycle event records whether each expected stage fired, skipped, or failed, with a reason. Once "disabled by config" becomes visible in the same surface as "worker failed" or "no candidates produced," issues like `auto_extract=false` for two months become impossible to miss.

## Target Architecture: Loop-Stage Modules

```
core/
  loop_health.py        ← NEW: stage contract (fired/skipped/failed + reason)
  decisions/
    __init__.py          ← re-exports for backward compat
    store.py             ← CRUD, links, successor-chain (from decisions.py 316-970)
    distill.py           ← extraction, candidates, quality gates (from decision_extraction.py + normalization)
    retrieve.py          ← ranking, FTS/hybrid search, staleness filtering (from decisions.py 998-1810)
    outcome.py           ← outcome recording, supersession, contradiction promotion (from decisions.py)
    intervene.py         ← surfacing, prompt formatting, context application (from decision_prompt_surfacing.py)
hooks/
  session_lifecycle.py   ← thin dispatch only: SESSION_END_STAGES list → stage modules
  decision_hooks.py      ← surfacing policy moves to core/decisions/intervene.py
mcp/
  runtime.py             ← add with_repo() context manager
  tools/*.py             ← use with_repo(), shared normalization
```

Mapping to loop stages:
- **capture**: `core/session.py` + `hooks/turn_capture.py` (already separate)
- **distill**: `core/decisions/distill.py` (extract + confirm + quality)
- **retrieve**: `core/decisions/retrieve.py` (rank + search + filter)
- **intervene**: `core/decisions/intervene.py` (surface + format + apply)
- **outcome**: `core/decisions/outcome.py` (record + supersede + promote)
- **health**: `core/loop_health.py` (stage contract + observability)

## Surgical Refactors (ordered by impact/risk)

### 1. Add Loop Health Contract

| Dimension | Detail |
|-----------|--------|
| **Scope** | Create `core/loop_health.py` (~100 lines). Record stage status for SessionStart, UserPromptSubmit, SessionEnd, PostCommit. Include "skipped:config_disabled" as first-class status. |
| **Blast radius** | Low-medium. Mostly additive; hook callsites only. |
| **Benefit** | Directly addresses the #1 failure mode: code existed but didn't fire and nobody noticed. Makes v1.0 gate ("loop completes without human intervention") measurable. |
| **Effort** | Medium (1-2d) |
| **Priority** | **Highest** — this is the meta-fix. |

### 2. Replace `_maybe_*` Sprawl With Declarative Stage Dispatch

| Dimension | Detail |
|-----------|--------|
| **Scope** | Keep 3 entry points in `session_lifecycle.py`. Move each `_maybe_*` body to stage modules. Dispatch via `SESSION_END_STAGES` list. |
| **Blast radius** | Medium. Tests already cover ordering and failures. Preserve order exactly. |
| **Benefit** | Makes default loop closure visible. Removes hidden business logic from hook dispatch. Enables per-stage health reporting (pairs with #1). |
| **Effort** | Medium (1-2d) |

### 3. Extract Retrieval Stage From decisions.py

| Dimension | Detail |
|-----------|--------|
| **Scope** | Move `RankingWeights`, ranking helpers, `rank_related_decisions`, `fts_search_decisions`, `hybrid_search_decisions` → `core/decisions/retrieve.py` (~660 lines). Keep re-export shims. |
| **Blast radius** | Medium. Many tests import from `core.decisions`; compatibility exports keep it manageable. |
| **Benefit** | Highest complexity reduction. Retrieval is already relatively cohesive and heavily tested. |
| **Effort** | Short-Medium (4h-1d) |

### 4. Extract Outcome Lifecycle + Dogfood Staleness

| Dimension | Detail |
|-----------|--------|
| **Scope** | Move `record_decision_outcome`, contradiction promotion, `supersede_decision`, successor-chain, staleness policy → `core/decisions/outcome.py`. Add SessionEnd health check reporting fresh/stale/superseded/contradicted counts. |
| **Blast radius** | Medium-high. Outcome semantics are central; do this AFTER retrieval extraction. |
| **Benefit** | Converts `staleness_status` and `superseded_by_id` from dormant schema into the product's own feedback loop. |
| **Effort** | Medium (1-2d) |

### 5. Add MCP Repo Context Helper + Adopt Existing RepoContext

| Dimension | Detail |
|-----------|--------|
| **Scope** | Add `runtime.with_repo()` context manager for MCP tools. Replace `resolve_repo()` + `try/finally conn.close()` incrementally. **Note:** `RepoContext` already exists in `core/context.py` (lines 88-156) with `__enter__`/`__exit__` — the connection lifecycle problem is an adoption gap, not missing infrastructure (same pattern as distill=0, Codex shift-left). |
| **Blast radius** | Low. Start with one MCP module, then repeat. |
| **Benefit** | Removes 29+ instances of boilerplate. Reduces repo normalization drift. |
| **Effort** | Quick-Short (<1h-4h) |
| **Risk note** | Will-based adoption ("use this pattern consistently") has a 3-peat failure history in this project. Consider removing the old `get_db()` + `try/finally` path entirely in migrated modules, not just adding an alternative. |

### Quick Win: Deduplicate `_find_git_root`

| Dimension | Detail |
|-----------|--------|
| **Scope** | Remove duplicate definition in `hooks/session_lifecycle.py:15-29`, import from `core/context.py:72`. |
| **Blast radius** | Very low. Tests monkeypatching `_find_git_root` on session_lifecycle need redirect. |
| **Benefit** | Single source of truth for git root discovery. |
| **Effort** | Quick (<1h) |

### Quick Win: Extract `decisions_normalization.py`

| Dimension | Detail |
|-----------|--------|
| **Scope** | Move lines 1805-1878 (3 functions: `normalize_alternative`, `normalize_rejected_alternatives`, `audit_rejected_alternatives`) to `core/decisions_normalization.py`. |
| **Blast radius** | Very low. 3 import sites in source, 1 test file. Zero coupling to ranking or CRUD. |
| **Benefit** | First step in decisions.py decomposition with near-zero risk. Establishes the pattern. |
| **Effort** | Quick (<1h) |

## Counterarguments Against Refactoring Now

1. **v1.0 might only need one config flip.** If `auto_extract` verification passes and the loop closes with current code, shipping v1.0 first and refactoring v1.1 avoids regression risk during the final push.

2. **1800+ test import surface.** Splitting `decisions.py` touches many test files. Even with re-export shims, subtle import-order or mock-target changes can cause flaky failures. Stage the split across multiple PRs.

3. **Opportunity cost.** Every day spent refactoring is a day not spent on `lesson_reuse_rate` activation or production `auto_extract` verification — the two items that directly unlock the remaining maturity points.

4. **"It works."** The current architecture, while messy, has shipped 10+ releases. The God module is well-tested. Refactoring for aesthetics without a concrete v1.0 blocker is vanity.

5. **Don't introduce a workflow engine.** The product needs five observable stages, not a framework. `loop_health.py` should be ~100 lines recording events, not an orchestrator.

## Recommended Execution Order

```
Phase 0 (immediate): Loop health contract (#1) — additive, low risk, unblocks measurement
Phase 1 (next release): Extract retrieval (#3) + MCP helper (#5) — highest cleanup/risk ratio
Phase 2 (post-v1.0): Stage dispatch (#2) + outcome lifecycle (#4) — higher blast radius, better after v1.0 stability
```

## Methodology Note

This analysis used three parallel review lanes:
- **Decision-analyzer**: EC decision ledger (50 decisions), all returned findings
- **Direct code analysis**: AST function counts, grep for patterns, file metrics
- **Architect expert (GPT via Codex)**: independent advisory review

Two additional subagents (code-reviewer, architect-review as Plan agent) were spawned but went idle without returning results; their analysis was fully substituted by direct file reads and the Codex Architect consultation.

### Simplify skill scope mismatch

The original goal included the `simplify` skill, which reviews changed code and applies fixes. This task produced a redesign *direction* with no source code changes — the skill has no legitimate diff target. The simplification lens is captured in:
- Refactor #3 (extract retrieval for cohesion — removes 660 lines from God module)
- Refactor #5 (MCP `with_repo()` — removes 29+ boilerplate sites)

These are where `simplify`-type thinking landed. Actual `simplify` execution belongs in the PRs that implement each refactor.

## Next Steps

When implementing the surgical refactors, invoke `/simplify` after each PR's code changes to verify the decomposition actually simplified rather than just moved code. The redesign direction itself is a research deliverable, not a code change.
