---
title: Bounded Abbreviated-SHA Blame Lookup
status: approved
date: 2026-07-21
schema: spec/v1
---

# Bounded Abbreviated-SHA Blame Lookup Design

_Created 2026-07-21._

## Overview

Make `ec blame <file> --decisions` reliable for files spanning more distinct commits than SQLite permits in one expression tree. Preserve the existing annotations, unlinked ranges, uncommitted ranges, CLI interface, and decision-link semantics while bounding each database lookup.

## User Scenarios

### S1: Annotate a file with high commit diversity

A developer runs `ec blame path/to/generated-history.py --decisions` on a file whose blamed lines span at least 1,200 distinct commits. The command completes without a SQLite expression-depth error and renders all recorded decision annotations.

### S2: Resolve abbreviated commit links at scale

A repository contains `decision_commits` rows with abbreviated commit SHAs. When those links resolve to commits blamed in a high-diversity file, `ec blame --decisions` emits the same canonical full-SHA annotations and deduplication as it does for a small file.

### S3: Preserve partial-history states

A file contains linked commits, commits without recorded decisions, and uncommitted lines. The command continues to render the three states separately after lookup bounding is introduced.

### S4: Keep normal blame behavior unchanged

A developer runs `ec blame --decisions` on an ordinary file. Its output and exit behavior remain unchanged; no new flag, configuration, or operational step is required.

## Scope

### In

- Bound the exact and abbreviated-SHA candidate lookup performed by `annotate_file()`.
- Preserve parameterized SQL and the existing canonical SHA resolution and annotation deduplication pipeline.
- Add an adversarial regression using at least 1,200 distinct blamed SHAs with SQLite expression depth lowered to 1,000.
- Retain existing CLI rendering and error behavior.

### Out

- Changes to the `ec blame` CLI interface or output format.
- Changes to `decision_commits`, decision schema, or migrations.
- New dependencies, configuration knobs, or user-tunable batch sizes.
- Performance redesign of `git blame` itself.
- General retrieval batching outside decision-annotated blame.

## Assumptions and Preconditions

| Claim | Command | Observed at | Observed result | Evidence source |
|---|---|---|---|---|
| The current lookup adds one prefix `OR` predicate per distinct blamed SHA. | `sed -n '128,143p' src/entirecontext/core/blame_decisions.py` | `2026-07-21T04:17:00Z` | One unbounded `prefix_conditions` expression is executed with all blamed SHAs. | Working tree source at `412288f` |
| SQLite expression depth can be constrained to the common 1,000 boundary in a deterministic regression. | `PYTHONPATH=src .venv/bin/python -c "import sqlite3; from entirecontext.db import get_memory_db; c=get_memory_db(); print(c.getlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH)); c.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH,1000); print(c.getlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH))"` | `2026-07-21T04:17:00Z` | The local limit is 10,000 and can be lowered to 1,000 for the test connection. | Python `sqlite3.Connection` runtime |
| Existing tests already lock abbreviated-link normalization, canonical deduplication, line ranges, and uncommitted ranges. | `rg -n 'test_(abbreviated|uppercase|equivalent|happy_two|line_range|uncommitted)' tests/test_blame_decisions.py` | `2026-07-21T04:17:00Z` | Six focused behavior tests exist in `tests/test_blame_decisions.py`. | Working tree tests at `412288f` |
| Separating exact and abbreviated candidates gives the two paths different query plans. | `PYTHONPATH=src .venv/bin/python -c "from entirecontext.db import get_memory_db,init_schema;c=get_memory_db();init_schema(c);print([tuple(r) for r in c.execute('EXPLAIN QUERY PLAN SELECT dc.commit_sha FROM decision_commits dc JOIN decisions d ON d.id=dc.decision_id WHERE dc.commit_sha IN (?,?,?)',('a'*40,'b'*40,'c'*40))]);print([tuple(r) for r in c.execute('EXPLAIN QUERY PLAN SELECT dc.commit_sha FROM decision_commits dc JOIN decisions d ON d.id=dc.decision_id WHERE length(dc.commit_sha)>=4 AND length(dc.commit_sha)<?',(40,))])"` | `2026-07-21T04:24:40Z` | Exact `IN` uses `idx_decision_commits_commit_sha`; the abbreviated-length filter scans stored commit links once. | In-memory migrated schema and SQLite query planner |
| The pre-change suite is green when the worktree uses the repository virtual environment. | `PATH="$PWD/.venv/bin:$PATH" UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src .venv/bin/pytest -q` | `2026-07-21T04:18:29Z` | 2,093 passed, 1 skipped, 1 warning. | Fresh worktree baseline |

## Approaches Considered

**Approach A: Split exact batches from abbreviated candidates**
- How: query exact commit links in conservative indexed batches, then load potentially abbreviated links once based on the blamed repository's full SHA width; combine both result sets before the existing resolution and deduplication pass.
- Pro: removes the unbounded prefix expression, preserves indexed exact lookup, scans abbreviated candidates once rather than once per batch, and avoids a per-SHA query loop.
- Con: the abbreviated-candidate query still scales with stored commit-link count because prefix matching is not indexable by the existing schema.

**Approach B: Batch the current combined OR query**
- How: split blamed SHAs into batches and execute the current exact-plus-prefix `OR` query for each batch.
- Pro: smallest source diff and bounded expression depth.
- Con: the prefix `OR` makes SQLite scan `decision_commits`; batching repeats that corpus scan for every batch.

**Approach C: Temporary-table join**
- How: insert blamed SHAs into a temporary table and join it to decision links for exact and prefix matching.
- Pro: keeps one set-based database operation and scales to very large SHA sets.
- Con: adds temporary schema lifecycle and transaction behavior to a currently read-only lookup path.

**Recommendation:** Approach A. It removes the accepted P2 failure without repeating a non-indexable prefix scan per batch. Exact batches must contain no more than 400 blamed SHAs, remaining below the legacy 999-variable boundary. Potentially abbreviated links are selected once per blamed full-SHA width and resolved through the existing Git-backed canonicalization path.

## Architecture

`src/entirecontext/core/blame_decisions.py` remains the only production module changed. `annotate_file()` continues to parse porcelain blame output into a deduplicated SHA-to-lines map. The candidate-query stage has two bounded parts:

1. Exact links use `decision_commits.commit_sha IN (...)` in fixed batches of at most 400 so the existing commit-SHA index remains usable.
2. Potentially abbreviated links are selected once for each full-SHA width present in blame output by requiring stored SHAs to be shorter than that width. Those candidates pass through `_resolve_blamed_sha()` before they can annotate a line.

The combined candidate rows then enter the existing annotation construction path. A real repository uses one Git object format, so the normal path performs one abbreviated-candidate query; mixed-width synthetic input remains bounded to the two parser-supported widths.

Candidate aggregation may return the same stored decision link through both exact and potentially abbreviated paths for mixed-width synthetic input. The existing canonical `(resolved_sha, decision_id)` deduplication remains authoritative, so result semantics do not depend on candidate path.

The design introduces no public module, schema, migration, background work, or cross-repository integration.

## Interface

No public interface changes. These commands retain their current arguments, rendering, and exit behavior:

```console
ec blame <file> --decisions
ec blame <file> -L <start>,<end> --decisions
```

`--summary` remains mutually exclusive with `--decisions`.

## Data Model

No data-model change. The existing `decision_commits(commit_sha)` index supports exact batches. Abbreviated-link selection remains a scan of candidate stored links, but it runs once per blamed full-SHA width rather than once per exact batch.

## Integration

The bounded lookup stays inside the existing `ec blame --decisions` call path. It does not affect archaeology, decision creation, commit-link normalization, MCP tools, or attribution-only blame output.

## Testing

Measurement infrastructure already exists: the real SQLite fixture, `sqlite3.Connection.setlimit()`, and `subprocess` monkeypatching used by `tests/test_blame_decisions.py`. No separate measurement implementation is required.

TDD begins with a failing regression that lowers `SQLITE_LIMIT_EXPR_DEPTH` to 1,000, supplies porcelain output with at least 1,200 distinct full SHAs, includes exact and abbreviated decision links, and asserts successful complete annotation. The same fixture records candidate-query execution and proves three exact batches plus one abbreviated-candidate query, with no exact batch exceeding 400 SHAs. Existing tests then prove normalization, deduplication, line ranges, unlinked ranges, uncommitted ranges, and CLI rendering remain unchanged.

## Risks

- **Candidate duplication:** a stored full link can appear in the exact result while a malformed or mixed-width record also enters abbreviated candidates. Mitigation: retain canonical result deduplication after all rows are aggregated.
- **Hidden variable-limit failure:** an exact batch can exceed older SQLite parameter limits. Mitigation: cap exact batches at 400 bound parameters.
- **N+1 regression:** querying once per SHA would avoid the expression limit but scale poorly. Mitigation: require bounded set-based batches, not per-SHA queries.
- **Abbreviated-link corpus scan:** the existing schema cannot index prefix resolution from stored shorter SHAs to blamed full SHAs. Mitigation: perform the candidate scan once per full-SHA width, then retain Git verification so unrelated rows cannot annotate output.
- **Test passes only on the local SQLite build:** the local build allows expression depth 10,000. Mitigation: lower the test connection limit to 1,000 explicitly before exercising 1,200 SHAs.

## Success Criteria

1. A 1,200-distinct-SHA blame lookup completes with `SQLITE_LIMIT_EXPR_DEPTH` set to 1,000 and returns the expected exact and abbreviated-link annotations.
   - **Measured by**: `PYTHONPATH=src .venv/bin/pytest -q tests/test_blame_decisions.py -k high_distinct_sha_count`
2. The 1,200-SHA fixture performs exactly three exact candidate queries and one abbreviated-candidate query, with no exact batch exceeding 400 SHAs.
   - **Measured by**: `PYTHONPATH=src .venv/bin/pytest -q tests/test_blame_decisions.py -k query_count_is_bounded`
3. All existing decision-annotated blame behaviors remain green.
   - **Measured by**: `PYTHONPATH=src .venv/bin/pytest -q tests/test_blame_decisions.py tests/test_blame_cmds.py`
4. The changed production module passes configured lint and type checking.
   - **Measured by**: `PATH="$PWD/.venv/bin:$PATH" uv run ruff check src/entirecontext/core/blame_decisions.py tests/test_blame_decisions.py && PATH="$PWD/.venv/bin:$PATH" uv run mypy src/entirecontext/core/blame_decisions.py`
5. The repository regression suite remains green.
   - **Measured by**: `PATH="$PWD/.venv/bin:$PATH" UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src .venv/bin/pytest -q`

## Open Decisions

None. Planning owns test/implementation sequencing but may not change the public behavior, the split exact/abbreviated lookup shape, the 400-SHA maximum exact batch size, or the adversarial 1,200-SHA/1,000-depth proof without returning to design.
