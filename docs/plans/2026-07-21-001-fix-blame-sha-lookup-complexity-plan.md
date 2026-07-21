---
schema: plan/v1
title: Bound abbreviated-SHA blame lookup complexity
type: fix
status: approved
date: 2026-07-21
execution: code
origin: docs/specs/2026-07-21-blame-sha-lookup-complexity-design.md
---

# Bound Abbreviated-SHA Blame Lookup Complexity Plan

## Goal

Prevent `ec blame --decisions` from exceeding SQLite expression limits when a file spans many distinct commits. Preserve every existing annotation and CLI behavior while replacing the combined exact-plus-prefix expression with bounded indexed exact lookups and one abbreviated-candidate scan per Git object-ID width.

The plan intentionally contains one implementation unit. Source, regression tests, and verification form one atomic behavior change, while the plan remains warranted for traceability to the approved spec and its query-shape decision.

## Architecture Notes

- Keep `annotate_file()` as the public core entry point and preserve its return shape.
- Add `_SHA_QUERY_BATCH_SIZE = 400` in `src/entirecontext/core/blame_decisions.py`; the value is fixed, internal, and not configurable.
- Add an internal `_query_decision_links(conn, blamed_shas)` helper that returns the same selected decision metadata rows consumed by the existing resolution loop.
- Query exact stored SHAs with `commit_sha IN (...)` in slices of at most 400 so `idx_decision_commits_commit_sha` remains usable.
- Query stored SHAs with lengths from 4 up to, but not including, each blamed full-SHA width. Run this abbreviated-candidate query once for normal SHA-1 or SHA-256 blame output and at most twice for synthetic mixed-width input.
- Pass all candidate rows through the existing `_resolve_blamed_sha()` check and canonical `(resolved_sha, decision_id)` deduplication. Candidate selection alone never annotates a line.
- Rejected: batching the current combined `OR` query. `EXPLAIN QUERY PLAN` shows that its prefix arm scans `decision_commits`, so chunking would repeat the scan for every batch.
- Known Pattern: `src/entirecontext/core/archaeology.py::archaeologize()` accumulates bounded batches and flushes the final partial batch. Use the same explicit slice/flush clarity; do not introduce a repository-wide batching abstraction for one caller.
- No applicable `docs/solutions/` entry or `CONCEPTS.md` vocabulary exists for this change.

## Assumption Recheck

All live assumptions retained by the approved origin spec were rerun from the isolated worktree. No contradiction or unavailable evidence was found.

| Approved claim | Fresh command evidence | Outcome |
|---|---|---|
| The current lookup adds one prefix `OR` predicate per distinct blamed SHA. | `sed -n '128,143p' src/entirecontext/core/blame_decisions.py` at `2026-07-21T04:32:19Z` still shows one unbounded `prefix_conditions` expression. | match |
| SQLite expression depth can be constrained to 1,000 in a deterministic regression. | `PYTHONPATH=src .venv/bin/python -c "import sqlite3; from entirecontext.db import get_memory_db; c=get_memory_db(); print(c.getlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH)); c.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH,1000); print(c.getlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH))"` at `2026-07-21T04:32:19Z` printed `10000` then `1000`. | match |
| Existing tests lock abbreviated-link normalization, canonical deduplication, line ranges, and uncommitted ranges. | `rg -n 'test_(abbreviated|uppercase|equivalent|happy_two|line_range|uncommitted)' tests/test_blame_decisions.py` at `2026-07-21T04:32:19Z` found the same six focused tests. | match |
| Split exact and abbreviated paths receive different query plans. | `PYTHONPATH=src .venv/bin/python -c "from entirecontext.db import get_memory_db,init_schema;c=get_memory_db();init_schema(c);print([tuple(r) for r in c.execute('EXPLAIN QUERY PLAN SELECT dc.commit_sha FROM decision_commits dc JOIN decisions d ON d.id=dc.decision_id WHERE dc.commit_sha IN (?,?,?)',('a'*40,'b'*40,'c'*40))]);print([tuple(r) for r in c.execute('EXPLAIN QUERY PLAN SELECT dc.commit_sha FROM decision_commits dc JOIN decisions d ON d.id=dc.decision_id WHERE length(dc.commit_sha)>=4 AND length(dc.commit_sha)<?',(40,))])"` at `2026-07-21T04:32:19Z` reported `SEARCH dc USING INDEX idx_decision_commits_commit_sha` for exact `IN` and `SCAN dc` for the abbreviated-length filter. | match |
| The pre-change repository suite is green in the isolated worktree. | `PATH="$PWD/.venv/bin:$PATH" UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src .venv/bin/pytest -q` completed at `2026-07-21T04:35:09Z` with 2,093 passed, 1 skipped, and 1 warning. | match |

## File Structure

- Modify `src/entirecontext/core/blame_decisions.py` — bounded candidate-query helper, fixed batch constant, and unchanged annotation-resolution integration.
- Modify `tests/test_blame_decisions.py` — high-diversity regression data, lowered SQLite limit proof, exact/abbreviated annotation assertions, and bounded query-count evidence.

## Scenario Coverage Map

| Scenario | Ordered unit chain | Scenario evidence |
|---|---|---|
| S1: Annotate a file with high commit diversity | U1 | `test_high_distinct_sha_count_survives_expression_depth_limit` exercises 1,200 blamed SHAs with depth 1,000. Covers S1. |
| S2: Resolve abbreviated commit links at scale | U1 | The same integration fixture includes full and abbreviated links and asserts canonical annotations. Covers S2. |
| S3: Preserve partial-history states | U1 | Existing linked, unlinked, and uncommitted-range tests plus the focused module run remain green. Covers S3. |
| S4: Keep normal blame behavior unchanged | U1 | Existing `tests/test_blame_decisions.py` and `tests/test_blame_cmds.py` pass without CLI or output changes. Covers S4. |

## Implementation Units

## U1: Split and bound decision-link candidate lookup
Execution note: test-first
Files:
  Modify: `src/entirecontext/core/blame_decisions.py`
  Test: `tests/test_blame_decisions.py`
Interfaces:
  Consumes: `annotate_file(conn: sqlite3.Connection, repo_path: str, file: str, start_line: int | None = None, end_line: int | None = None) -> dict[str, Any]`; `decision_commits.commit_sha`; `decisions` annotation metadata; Git blame porcelain full SHAs.
  Produces: unchanged `annotate_file()` return contract; internal `_query_decision_links(conn: sqlite3.Connection, blamed_shas: list[str]) -> list[sqlite3.Row]`; internal `_SHA_QUERY_BATCH_SIZE = 400`.
Test scenarios:
  happy: 1,200 distinct SHA-1 blamed commits include exact and abbreviated stored links; both resolve to canonical full-SHA annotations. Covers S1 and S2.
  edge: candidate SQL executes exactly three exact batches and one abbreviated-candidate query; each exact batch has at most 400 SHAs; existing equivalent-link deduplication and mixed linked/unlinked/uncommitted ranges remain unchanged. Covers S3.
  error: set `SQLITE_LIMIT_EXPR_DEPTH` to 1,000 before the 1,200-SHA call and prove no `sqlite3.OperationalError` escapes.
  integration: call `annotate_file()` with mocked porcelain output and the real `ec_db` SQLite fixture, then run the existing CLI/core suites. Covers S1, S2, S3, and S4.
Steps:
  1. Add `tests/test_blame_decisions.py::TestAnnotateFile::test_high_distinct_sha_count_survives_expression_depth_limit` and `test_high_distinct_sha_query_count_is_bounded`; use deterministic synthetic 40-character SHAs, a real migrated `ec_db`, `Connection.setlimit()`, and query tracing or a counting connection proxy.
  2. Run `PYTHONPATH=src .venv/bin/pytest -q tests/test_blame_decisions.py -k 'high_distinct_sha_count or query_count_is_bounded'`; confirm the current code fails with expression depth 1,000 and does not satisfy the required three-exact-plus-one-abbreviated query shape.
  3. Add `_SHA_QUERY_BATCH_SIZE`, `_query_decision_links()`, indexed exact batches, and one abbreviated-candidate query per blamed SHA width; replace only the current combined-query block in `annotate_file()`.
  4. Run the two new tests, the complete blame core/CLI suites, Ruff, mypy, and the full repository suite; confirm no regressions and retain the observed counts in `.release-loop/progress.md`.
  5. Commit: `fix(blame): Bound decision-link lookup complexity` using the repository Lore trailers and the fresh verification evidence.
Acceptance: `PYTHONPATH=src .venv/bin/pytest -q tests/test_blame_decisions.py -k 'high_distinct_sha_count or query_count_is_bounded'`; `PYTHONPATH=src .venv/bin/pytest -q tests/test_blame_decisions.py tests/test_blame_cmds.py`; `PATH="$PWD/.venv/bin:$PATH" uv run ruff check src/entirecontext/core/blame_decisions.py tests/test_blame_decisions.py`; `PATH="$PWD/.venv/bin:$PATH" uv run mypy src/entirecontext/core/blame_decisions.py`; `PATH="$PWD/.venv/bin:$PATH" UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src .venv/bin/pytest -q`.

## Mutation/Failure-State Matrix

No stateful ceremony in the deliverable; no mutation/failure-state matrix required.

## Deferred to Follow-Up Work

- General batching for other unbounded `IN (...)` queries remains outside this fix because no failure evidence was established for those callers.
- Index or schema changes for abbreviated-link prefix search remain outside this fix because one verified candidate scan is sufficient for the accepted P2 scope.

## Open Unknowns

### Planning-Time

None.

### Implementation-Time

- Choose query tracing or a small counting connection proxy for the bounded-query assertion. The test must observe three exact queries and one abbreviated-candidate query without changing production interfaces.
