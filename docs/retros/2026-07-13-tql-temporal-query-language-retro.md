# TQL (Temporal Query Language) Retrospective

_Merged 2026-07-13 (PR #193). Branch: feature/temporal-query-language._

## Scope & Delivery

| Item | Result |
|------|--------|
| `core/tql.py` module (resolve_temporal_ref, resolve_until, apply_temporal_filters) | Shipped |
| `--since`/`--until` on 3 CLI commands (search, decision search, decision list) | Shipped |
| `until` on 4 MCP tools (ec_search, ec_decision_search, ec_decision_list, ec_decision_related) | Shipped |
| `updated_at` → `created_at` semantic change for decision temporal filters | Shipped |
| datetime() normalization replacing raw lexicographic comparison | Shipped |
| Code delta | +1213/-115 lines (product 34%, test 35%, docs 31%) |
| Tests | 35 new TQL tests, 2048 total passed |
| PR #193 | 1 branch review round (3 findings fixed), 2 CI autofix commits |
| CI failures | 2 (lint + type-check, both auto-fixed by cloud session) |
| Duration | ~15h spec-to-merge (2 sessions across 2 days) |
| Tasks | 5/5 completed |

## Previous Carry-Forward Status

| Item | Status |
|------|--------|
| Maturity 75 dogfooding with `ec context apply` | ⏳ Ongoing — not specifically exercised in this release |
| Consolidate PR fetch-result and processing-state branches in archaeology | ⏳ Not started — archaeology not touched |
| Support general Git C-style escaped quotes in paths | ⏳ Not started — no path parsing work in this release |

## Key Findings

### 1. Branch review caught 3 real issues that implementation missed

The single-round branch review (opus-model reviewer agent) caught C1 (date-only expansion dead code), I1 (validated() never called), and I2 (cross-repo raw ref passthrough). All three were spec-documented behaviors that the implementation simply forgot to wire up.

**Why:** The plan described `resolve_until` and `TQLContext.validated()` conceptually but the implementation created the primitives without connecting them at call sites. The `is_date_only` return value from `resolve_temporal_ref` was discarded at every call site (`_, is_date = ...`).

**How to apply:** When a plan specifies a multi-step data flow (resolve → transform → validate → inject), the implementation checklist should verify each handoff, not just each component. A post-implementation grep for unused return values (`_, ` patterns) could catch this mechanically.

### 2. Private function signature changes caused cascading test updates

Adding `until` and `until_exclusive` positional parameters to 6 inner search functions broke 3 existing tests that called `_fts_search_turns()`, `_fts_search_events()`, etc. directly with positional args.

**Why:** Inner functions used positional parameters, and existing tests bypassed the outer API to call them directly.

**How to apply:** Accept this as a low-severity cost of extending internal interfaces. The tests are validating internal behavior (FTS error handling) that doesn't have a clean outer API path. Not worth refactoring the inner signatures to kwargs just for test stability.

### 3. Autofix cloud session handled CI failures without manual intervention

The `/autofix-pr 193` cloud session produced 2 commits: one for lint/type-check issues (`params: list` → `params: list[Any]`) and one for git option injection defense (`ref.startswith("-")` guard). Both were correct and merged cleanly.

**Why:** The `apply_temporal_filters` type annotation used bare `list` instead of `list[Any]`, and the git ref resolution accepted arbitrary strings including `-`-prefixed values that could be interpreted as git flags.

**How to apply:** The git option injection fix (rejecting refs starting with `-`) is a security-relevant pattern. Apply the same guard in any future `subprocess.run(["git", ..., user_input])` call sites.

### 4. Plan was not saved to file until post-implementation

The release-loop progress.md recorded `Plan: (inline)` through implementation and review, only saving the plan file after the user pointed it out. This violates the release-loop protocol (plan should survive context compaction).

**Why:** The plan was provided by the user in the conversation prompt, not generated through the plan phase. The orchestrator treated it as already-available rather than saving it as a durable artifact.

**How to apply:** When a plan is provided inline (user message or previous session), always save to `docs/superpowers/plans/` before starting implementation. The plan file is a release-loop invariant regardless of source.

## Carry-Forward to Next Release

| Item | Type | Priority |
|------|------|----------|
| `--until` silently ignored for `--semantic` search (M1) | feature gap | P3 |
| `--until` silently dropped in `--global` cross-repo search path (M2) | feature gap | P3 |
| Maturity 75 dogfooding with `ec context apply` | measurement | ongoing |
| Consolidate PR fetch-result and processing-state branches in archaeology | architecture | P3 |

## Lessons

**"Unused return values are spec violations waiting to happen"** — `resolve_temporal_ref` returned `(ts, is_date_only)` and every call site discarded the second value. A grep for `_, ` patterns after implementation would have caught the C1 critical before review.

**"Autofix-PR is a reliable CI repair path"** — the cloud session correctly identified and fixed both a type annotation gap and a security-relevant git option injection vector, producing clean commits that passed all checks.

**"Plan-as-file is a release-loop invariant"** — inline plans from conversation don't survive context compaction. Save first, implement second, regardless of plan origin.
