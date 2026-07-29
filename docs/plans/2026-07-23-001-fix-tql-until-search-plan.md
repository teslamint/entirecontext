---
schema: plan/v1
title: Complete TQL until propagation for semantic and cross-repo search
type: fix
status: approved
date: 2026-07-23
execution: code
---

# Complete TQL `--until` Propagation

## Goal

Make the existing TQL upper bound effective for local semantic search and every cross-repo `ec search` path without changing TQL syntax, timestamp semantics, search-mode selection, or repository boundaries.

## Success metrics

| Metric | Target | Measurement |
|---|---|---|
| Local semantic upper-bound correctness | 100% of seeded results satisfy the inclusive or exclusive bound | `tests/test_e2e_search.py` temporal semantic-search assertions |
| Cross-repo upper-bound correctness | Regex, FTS, hybrid, and semantic modes exclude out-of-range rows in every selected repository | `tests/test_cross_repo.py` multi-repo assertions |
| Boundary propagation completeness | CLI and MCP pass `since`, `until`, and `until_exclusive` to the selected core path | `tests/test_search_cmds.py` and `tests/test_mcp.py` call-contract assertions |
| Regression safety | Existing TQL, search, cross-repo, semantic, and MCP search suites remain green | Targeted module suites, then Ruff, mypy, and the full test suite |

The measurement infrastructure exists and is green before implementation: 79 tests passed across TQL, TQL integration, CLI search, cross-repo search, and end-to-end search; the focused MCP `ec_search` selection passed 4 tests with 111 deselected.

## Architecture notes

- Preserve the existing boundary contract: CLI and MCP accept raw refs or dates, use `resolve_temporal_ref()` and `resolve_until()`, validate with `TQLContext.validated()`, and pass normalized timestamps into core functions.
- Extend `semantic_search()` with `until` and `until_exclusive` immediately after its existing `since` parameter. Existing positional callers that pass `since` remain compatible.
- Keep semantic filtering in the current post-ranking pipeline. When turn and session rows are loaded, select a SQLite-normalized timestamp with `datetime(timestamp)` or `datetime(started_at)`, then apply lower and upper bounds before appending a result. This reuses SQLite's mixed-format normalization without adding a second timestamp parser.
- Treat a null or unparseable normalized timestamp as ineligible whenever a temporal bound is active, matching SQL `datetime()` filter behavior.
- Include `until` in semantic search's filtered-fetch multiplier condition so a temporal request gets the same candidate allowance as the existing file, commit, agent, and `since` filters.
- Extend `cross_repo_search()` with normalized `until` and `until_exclusive` parameters and forward all three temporal values to regex, FTS, hybrid, and semantic per-repository calls. `RepoExecutor` continues to own repository enumeration, fault isolation, result annotation, sorting, and limiting.
- CLI cross-repo resolution remains once per invocation against the current repository, matching the shipped TQL behavior. It must pass the already resolved upper bound rather than re-resolving inside each repository.
- MCP cross-repo search resolves and validates temporal inputs before calling `cross_repo_search()`. ISO dates remain usable without a repository path. Git refs require a resolvable current project, matching cross-repo decision search behavior.
- Preserve the existing decision that CLI `--hybrid --global` warns and falls back to FTS5. This plan only propagates temporal bounds into the selected path.
- Preserve the separation between MCP boundary formatting, cross-repo orchestration, and per-repository search implementations. No new shared state, schema, dependency, or public command is introduced.

## Assumption Recheck

No origin spec; no approved live assumptions to recheck.

## File structure

### Semantic filtering

- Modify `src/entirecontext/core/embedding.py` to accept and enforce normalized upper bounds for turn and session embeddings.
- Modify `tests/test_e2e_search.py` to lock semantic inclusive, exclusive, mixed-format, and invalid-timestamp behavior.

### Cross-repo propagation

- Modify `src/entirecontext/core/cross_repo.py` to carry normalized upper bounds into every search mode.
- Modify `tests/test_cross_repo.py` to prove filtering across both real repository fixtures.

### CLI and MCP boundaries

- Modify `src/entirecontext/cli/search_cmds.py` to forward resolved bounds to local semantic and cross-repo calls.
- Modify `src/entirecontext/mcp/tools/search.py` to resolve, validate, and forward bounds for local semantic and cross-repo calls.
- Modify `tests/test_search_cmds.py` to verify CLI call contracts and validation short-circuits.
- Modify `tests/test_mcp.py` to verify MCP local semantic and cross-repo call contracts.

## Scenario coverage map

No origin spec exists for this corrective plan. The direct user request and `docs/retros/2026-07-13-tql-temporal-query-language-retro.md` define these regression scenarios.

| Regression scenario | Unit chain | Walking evidence |
|---|---|---|
| A local CLI or MCP semantic query supplies an inclusive datetime or date-only exclusive upper bound and receives no newer turn or session | U1 → U3 | End-to-end semantic fixture plus CLI and MCP boundary assertions |
| A CLI `--global` or MCP `repos` query supplies an upper bound and every selected repository applies it in regex, FTS, hybrid, and semantic modes | U2 → U3 | Real two-repository fixture plus CLI and MCP boundary assertions |
| An invalid or reversed temporal range fails before semantic or cross-repo execution | U3 | CLI exit/error assertion and MCP error-payload assertion |

## Implementation Units

## U1: Enforce normalized upper bounds in semantic search

Execution note: test-first
Files:
  Modify: `src/entirecontext/core/embedding.py`
  Test: `tests/test_e2e_search.py`
Interfaces:
  Consumes: `semantic_search(conn, query, limit=20, model_name="all-MiniLM-L6-v2", file_filter=None, commit_filter=None, agent_filter=None, since=None, until=None, until_exclusive=False)`
  Produces: Semantic result lists whose turn `timestamp` or session `started_at` satisfies every supplied normalized temporal bound
Test scenarios:
  happy: `TestSemanticSearch::test_semantic_search_with_until_filter` keeps a result exactly on an inclusive datetime boundary and excludes a newer result.
  edge: `TestSemanticSearch::test_semantic_search_with_exclusive_until_and_mixed_formats` treats date-only expansion as exclusive and compares both ISO-offset and SQLite space-separated stored timestamps correctly.
  error: `TestSemanticSearch::test_semantic_search_excludes_unparseable_timestamp_when_bounded` returns no malformed-timestamp row instead of raising or leaking it through the bound.
  integration: The real database and embedding fixture walk the local semantic regression scenario before CLI or MCP formatting.
Steps:
  1. Add the three failing semantic temporal tests with deterministic fake vectors and explicit turn or session timestamps.
  2. Run the three tests and confirm failure because `semantic_search()` has no `until` contract and does not normalize source timestamps.
  3. Add `until` and `until_exclusive`, select SQLite-normalized source timestamps, include `until` in the filtered-fetch condition, and apply inclusive or exclusive comparison before result append.
  4. Run `tests/test_e2e_search.py`, then `tests/test_tql.py` and `tests/test_tql_integration.py`; confirm the new scenarios and existing temporal semantics pass.
  5. Commit: `fix(search): enforce TQL upper bounds in semantic retrieval`
Acceptance: `UV_CACHE_DIR=/tmp/uv-cache .venv/bin/pytest -q tests/test_e2e_search.py tests/test_tql.py tests/test_tql_integration.py` passes, and the new tests prove inclusive, exclusive, mixed-format, and invalid-timestamp behavior.

## U2: Propagate upper bounds through cross-repo orchestration

Execution note: test-first
Files:
  Modify: `src/entirecontext/core/cross_repo.py`
  Test: `tests/test_cross_repo.py`
Interfaces:
  Consumes: `cross_repo_search(query, search_type="regex", target="turn", repos=None, file_filter=None, commit_filter=None, agent_filter=None, since=None, until=None, until_exclusive=False, limit=20, include_warnings=False)`
  Produces: Merged cross-repo results where each per-repository regex, FTS, hybrid, or semantic query receives the same normalized temporal bounds
Test scenarios:
  happy: `TestCrossRepoSearch::test_until_filters_each_repo` seeds one in-range and one out-of-range turn per repository and proves regex, FTS, and hybrid modes return only in-range rows.
  edge: `TestCrossRepoSearch::test_exclusive_until_reaches_semantic_search` seeds embeddings in both repositories and proves the exclusive flag reaches semantic filtering before global sorting and limiting.
  error: `TestCrossRepoSearch::test_temporal_filter_preserves_repo_fault_isolation` keeps valid-repository results when one registered repository fails during a bounded query.
  integration: The real `multi_ec_repos` fixture walks the global regression scenario across two independent databases and preserves `repo_name` and `repo_path` annotations.
Steps:
  1. Add failing multi-repository tests for bounded regex, FTS, hybrid, semantic, and one-repository failure behavior.
  2. Run the new tests and confirm out-of-range rows remain because `cross_repo_search()` accepts only `since`.
  3. Add `until` and `until_exclusive` to `cross_repo_search()` and forward them to every per-repository search call without changing `RepoExecutor`.
  4. Run `tests/test_cross_repo.py`, then `tests/test_e2e_cross_repo.py`; confirm temporal correctness, annotations, fault isolation, sorting, and limits remain intact.
  5. Commit: `fix(search): preserve TQL bounds across repositories`
Acceptance: `UV_CACHE_DIR=/tmp/uv-cache .venv/bin/pytest -q tests/test_cross_repo.py tests/test_e2e_cross_repo.py` passes and every search mode excludes out-of-range rows from both repositories.

## U3: Complete CLI and MCP temporal boundary wiring

Execution note: test-first
Files:
  Modify: `src/entirecontext/cli/search_cmds.py`
  Modify: `src/entirecontext/mcp/tools/search.py`
  Test: `tests/test_search_cmds.py`
  Test: `tests/test_mcp.py`
Interfaces:
  Consumes: CLI `ec search QUERY [--semantic|--fts|--hybrid] [--global|-r REPO] [--since REF_OR_DATE] [--until REF_OR_DATE]`; MCP `ec_search(query, search_type="regex", since=None, until=None, repos=None, ...)`
  Produces: One resolved and validated `(since, until, until_exclusive)` tuple passed to local semantic or cross-repo core search; CLI errors use exit code 1 and MCP errors use the existing JSON error payload
Test scenarios:
  happy: `TestSearch::test_semantic_until_is_forwarded` and `TestMCPToolIntegration::test_ec_search_semantic_until_is_forwarded` prove normalized inclusive bounds reach local semantic search.
  edge: `TestSearch::test_global_date_until_is_forwarded_as_exclusive` and `TestMCPToolIntegration::test_ec_search_cross_repo_until_is_forwarded` prove date-only expansion and normalized repository filters reach `cross_repo_search()`.
  error: CLI and MCP reversed-range tests prove validation returns before either core function is called; a cross-repo MCP git ref without a resolvable current project returns the existing TQL error shape.
  integration: CLI and MCP tests walk both direct-request scenarios through their public boundaries while preserving mutual-exclusion and cross-repo hybrid-fallback behavior.
Steps:
  1. Add failing CLI and MCP call-contract tests for local semantic, cross-repo, date-only exclusive, reversed-range, and unresolved-ref behavior.
  2. Run the new tests and confirm `resolved_until` and `until_exclusive` are dropped on the current local semantic and cross-repo branches.
  3. Forward the CLI's existing resolved values to `semantic_search()` and `cross_repo_search()`; resolve and validate MCP cross-repo values before forwarding them, closing any connection opened only to obtain the current repository path.
  4. Run `tests/test_search_cmds.py` and the complete `tests/test_mcp.py`, then run all changed-module suites together.
  5. Commit: `fix(search): complete TQL until boundary propagation`
Acceptance: `UV_CACHE_DIR=/tmp/uv-cache .venv/bin/pytest -q tests/test_search_cmds.py tests/test_mcp.py tests/test_tql.py tests/test_tql_integration.py tests/test_e2e_search.py tests/test_cross_repo.py tests/test_e2e_cross_repo.py` passes; `UV_CACHE_DIR=/tmp/uv-cache .venv/bin/ruff check src/entirecontext/core/embedding.py src/entirecontext/core/cross_repo.py src/entirecontext/cli/search_cmds.py src/entirecontext/mcp/tools/search.py tests/test_e2e_search.py tests/test_cross_repo.py tests/test_search_cmds.py tests/test_mcp.py` and `.venv/bin/mypy src/entirecontext` pass before the full test suite.

## Mutation/failure-state matrix

No stateful ceremony in the deliverable; no mutation/failure-state matrix required.

## Deferred to Follow-Up Work

- A published v0.15.0 release, version bump, tag, and CHANGELOG entry remain shipping work. `ROADMAP.md` now describes the already merged feature scope without claiming those artifacts exist.
- Semantic candidate pre-filtering before similarity ranking, a two-pass background architecture, and changes to the existing `limit * 5` post-filter heuristic are outside this correctness fix.
- Adding `until_filter` to retrieval telemetry is a separate observability change because current telemetry records only `since_filter`.
- Per-repository git-ref resolution is not introduced. Cross-repo search keeps the shipped convention of resolving a ref once against the current project before fan-out.
- The decision-specific embedding function `semantic_search_decisions()` is not exposed by the affected `ec search` CLI or MCP paths and remains unchanged.

## Open unknowns

### Planning-time

None. The public behavior, inclusive and exclusive semantics, boundary ownership, file scope, and verification commands are fixed by the existing TQL implementation and retrospective.

### Implementation-time

None. Unit steps name the required signatures, comparison behavior, fixtures, error ownership, and completion evidence.
