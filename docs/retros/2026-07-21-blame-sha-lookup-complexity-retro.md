# Retro: Bound Abbreviated-SHA Blame Lookup Complexity

- Date: 2026-07-21
- Source: PR #199
- Spec: `docs/specs/2026-07-21-blame-sha-lookup-complexity-design.md`
- Plan: `docs/plans/2026-07-21-001-fix-blame-sha-lookup-complexity-plan.md`

## Release data

| Metric | Value |
|---|---|
| **Changed non-test lines** | 388 (355 added + 33 removed) |
| Commits | 18 branch commits, squash-merged as `5a24ebf` |
| Review rounds | 5 (3 unit rounds + 1 branch review + 1 PR feedback round) |
| Comments (fixed / deferred) | 1 / 0 |
| CI failures | 0 across 3 green runs |
| Duration (first spec commit → merge) | 0.13 days (3h 12m 54s) |
| Units planned / completed | 1 / 1 |

## Success criteria: measured vs declared

| # | Declared criterion | Measurement (command / rubric) | Measured result | Verdict |
|---|---|---|---|---|
| 1 | A 1,200-distinct-SHA blame lookup completes with `SQLITE_LIMIT_EXPR_DEPTH` set to 1,000 and returns the expected exact and abbreviated-link annotations. | `PYTHONPATH=src .venv/bin/pytest -q tests/test_blame_decisions.py -k high_distinct_sha_count` | Fresh retro run: 1 passed, 19 deselected. | **Met** |
| 2 | The 1,200-SHA fixture performs exactly three exact candidate queries and one abbreviated-candidate query, with no exact batch exceeding 400 SHAs. | `PYTHONPATH=src .venv/bin/pytest -q tests/test_blame_decisions.py -k query_count_is_bounded` | Fresh retro run: 1 passed, 19 deselected. | **Met** |
| 3 | All existing decision-annotated blame behaviors remain green. | `PYTHONPATH=src .venv/bin/pytest -q tests/test_blame_decisions.py tests/test_blame_cmds.py` | Fresh retro run: 34 passed. | **Met** |
| 4 | The changed production module passes configured lint and type checking. | `PATH="$PWD/.venv/bin:$PATH" uv run ruff check src/entirecontext/core/blame_decisions.py tests/test_blame_decisions.py && PATH="$PWD/.venv/bin:$PATH" uv run mypy src/entirecontext/core/blame_decisions.py` | Fresh retro run: Ruff reported `All checks passed!`; mypy reported `Success: no issues found in 1 source file`. | **Met** |
| 5 | The repository regression suite remains green. | `PATH="$PWD/.venv/bin:$PATH" UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src .venv/bin/pytest -q` | Fresh retro run: 2,099 passed, 1 skipped, 1 pre-existing fixture warning in 138.74s. | **Met** |

## Carry-forward from previous retro

| Item | Status | Evidence |
|---|---|---|
| Bound abbreviated-SHA blame lookup complexity | Done | PR #199, merge `5a24ebf`, and all five fresh success measurements above; `ROADMAP.md` marks the item complete. (T3) |
| Post-squash archaeology convergence | Not started | `ROADMAP.md` retains the item as unchecked; no explicit repository-content export authorization was supplied. (T3) |
| TQL `--until` for local semantic search | Not started | `src/entirecontext/cli/search_cmds.py:90-103` passes `since` but not `until` to `semantic_search`. (T3) |
| TQL `--until` for global cross-repo search | Not started | `src/entirecontext/core/cross_repo.py:180-241` accepts and forwards `since` but has no `until` parameter. (T3) |
| Maturity 75 dogfooding with `ec context apply` | In progress | `ROADMAP.md` retains this as an ongoing measurement item. (T3) |
| Consolidate PR fetch-result and processing-state branches in archaeology | Not started | `src/entirecontext/core/archaeology.py:447-496` still carries separate skip, token, batch, and final-batch transitions. (T3) |
| General Git C-style escaped paths | Not started | `src/entirecontext/core/archaeology.py:35-45` still decodes octal escapes only. (T3) |

- Previous doc shape: pre-schema, exempt

## Interview Transcript

- Independence level: same-model fresh-context
- Rounds used: 2 (max 5)

| ID | Round | Phase | Probe | Answer | Evidence | Verdict (verbatim) |
|---|---|---|---|---|---|---|
| T1 | 1 | 5 | What specifically prevented the original SQLite failure from recurring without merely moving unbounded work into Git subprocesses? | Exact SQL lookup is capped at 400 SHAs per batch and abbreviated candidates are scanned once per SHA width. Blamed-prefix filtering prevents unrelated candidates from reaching Git, while lowercase cache keys collapse case variants. | `src/entirecontext/core/blame_decisions.py:90-120,165-183`; `tests/test_blame_decisions.py:55-157`; `.release-loop/progress.md` feedback round 1; merge `5a24ebf`. | accepted |
| T2 | 1 | 5 | What took meaningfully longer than the original minimum implementation, and what should a future plan test earlier? | Review exposed uppercase and mixed-case full-SHA behavior, unrelated abbreviated candidates, and case-variant cache misses after the initial batching implementation. Future Git/SQLite boundary plans should jointly test SQL expression/query counts, candidate cardinality, subprocess calls, and cache-key normalization. | `.release-loop/progress.md` unit review rounds 1–3 and feedback round 1; merged tests in `5a24ebf`; `review_rounds=3`, `feedback_rounds=1`, `comments_fixed=1`. | accepted |
| T3 | 2 | 4 | Did this cycle close the previous P2 carry-forward and silently drop any of the other six prior items? | It closed only `Bound abbreviated-SHA blame lookup complexity`. The other six items remain explicitly tracked with supported statuses, and PR #199 introduced no deferred item because its sole actionable comment was fixed before merge. | `ROADMAP.md:350-357`; prior retro carry-forward table; PR #199 / `5a24ebf`; fresh success measurements; `src/entirecontext/cli/search_cmds.py:90-103`; `src/entirecontext/core/cross_repo.py:180-241`; `src/entirecontext/core/archaeology.py:35-45,381-507`; `.release-loop/progress.md`. | accepted |
| T4 | 1 | 5 | Which claim is reusable beyond this feature, and what is the concrete rule? | A bound in one cost domain does not bound downstream work. Lookup pipelines should assert bounds at database expressions and queries, candidate rows, subprocess calls, and cache identities, with key normalization matching lookup equivalence. | The initial SQL-focused implementation passed before PR feedback exposed 1,000 Git calls; `tests/test_blame_decisions.py:69-157`; `.release-loop/progress.md` records the causal sequence. | accepted |

## Findings

### What worked well

- **What happened**: PR #199 replaced the expression-depth failure with three exact indexed queries plus one candidate scan for 1,200 SHAs, then bounded Git resolution for 1,000 unrelated links and 64 case variants.
  **Why**: review followed the candidate set across SQL, Python filtering, Git subprocesses, and cache identity instead of stopping after the database test passed.
  **How to apply**: keep a regression assertion at every multiplicative boundary in lookup pipelines.
  **Cites**: T1; Phase 2–3 data

- **What happened**: all five declared success criteria passed in fresh post-merge runs, including 2,099 repository tests.
  **Why**: each criterion named an executable measurement before implementation, and the retro reran those exact commands rather than citing PR claims.
  **How to apply**: retain command-shaped criteria for storage-engine limits and query-shape guarantees.
  **Cites**: Phase 2–3 data

### What to improve

- **What happened**: the first green implementation bounded SQLite expressions but still allowed 1,000 unrelated candidates to trigger 1,000 `git rev-parse` calls; a later review also found case variants bypassed the cache.
  **Why**: the original success criteria measured SQL query shape but not downstream candidate cardinality, subprocess count, or cache-key equivalence.
  **How to apply**: define one complexity budget spanning database expressions, candidate rows, external calls, and normalized cache identities before implementation.
  **Cites**: T1; T2; T4

### Process observations

- **What happened**: the minimum batching change was followed by three unit review rounds and one PR feedback round covering uppercase full SHAs, mixed-case full SHAs, unrelated abbreviated candidates, and case-variant cache misses.
  **Why**: representation and cost-boundary cases were broader than the initial SQL failure mode.
  **How to apply**: add a boundary-matrix test pass before the first implementation review for code that joins Git identifiers with SQLite records.
  **Cites**: T2; Phase 2 release data

## Carry-forward items registered

| Item | Type | Priority | Tracked at |
|---|---|---|---|
| None this cycle | — | — | The six unresolved prior items remain in `ROADMAP.md`; PR #199 deferred zero comments. |

## Lessons

- **“A bound in one cost domain does not bound the pipeline.”** Assert limits at database expressions and queries, candidate rows, subprocess calls, and cache identities, and normalize keys at the same equivalence boundary used for matching.

## Compounding

- compound invocation: `Documentation complete — docs/solutions/performance-issues/bound-cost-across-lookup-pipeline-domains.md`
