# TQL Implementation Plan

**Goal:** Add `--since`/`--until` temporal filters (accepting git refs and ISO dates) to 3 CLI commands and 4 MCP tools.

**Architecture:** New `core/tql.py` module handles ref resolution and filter injection. Existing search/decision functions gain an `until` parameter and migrate existing `since` raw injection to `apply_temporal_filters` for uniform `datetime()` normalization. CLI/MCP boundary layers resolve all temporal refs unconditionally before calling core.

**Tech Stack:** Python 3.12+, SQLite `datetime()`, git subprocess

**Deliverable Type:** code

## Global Constraints

- No schema changes — uses existing indexed columns
- `datetime(col)` normalization for **all** temporal WHERE clauses — both `since` and `until` (mixed format: `T+00:00` vs space-naive). Existing raw `since` injections (`AND t.timestamp >= ?`) must be replaced with `apply_temporal_filters` to prevent lexicographic comparison bugs across formats
- decisions filter on `created_at` (changed from `updated_at`) — point-in-time existence semantics
- CLI `decision related` command does not exist — TQL applies to MCP `ec_decision_related` only

---

## File Structure

**Create:**
- `src/entirecontext/core/tql.py` — TQLContext, resolve_temporal_ref, resolve_until, apply_temporal_filters
- `tests/test_tql.py` — unit tests for TQL module
- `tests/test_tql_integration.py` — integration tests (DB + git repo)

**Modify:**
- `src/entirecontext/core/search.py` — replace raw `since` with `apply_temporal_filters`, add `until`/`until_exclusive` to 3 outer + 6 inner functions
- `src/entirecontext/core/decisions.py` — `updated_at` → `created_at`, replace `(? IS NULL OR ...)` pattern with `apply_temporal_filters`, add `until`/`until_exclusive` to 4 functions, add `since`/`until` to 2 functions
- `src/entirecontext/cli/search_cmds.py` — add `--until` flag
- `src/entirecontext/cli/decisions_cmds.py` — add `--until` to search, add `--since`/`--until` to list
- `src/entirecontext/mcp/tools/search.py` — add `until` param to `ec_search`
- `src/entirecontext/mcp/tools/decisions.py` — add `until` param to `ec_decision_search`, `ec_decision_list`, `ec_decision_related`

---

## Tasks

### Task 1: TQL Core Module
- Create `src/entirecontext/core/tql.py` with TQLContext, resolve_temporal_ref, resolve_until, apply_temporal_filters, TQLError
- Create `tests/test_tql.py` with unit tests

### Task 2: Core Search Until Integration
- Modify `src/entirecontext/core/search.py`: add `until`/`until_exclusive` param to all search functions, replace raw `since` injection with `apply_temporal_filters`

### Task 3: Core Decisions Temporal Integration
- Modify `src/entirecontext/core/decisions.py`: `updated_at` → `created_at`, add `until`/`until_exclusive` to search/list/rank functions

### Task 4: CLI and MCP Integration
- Add `--until` to CLI commands, `until` to MCP tools
- Resolve temporal refs at boundary layer via `resolve_temporal_ref`/`resolve_until`

### Task 5: Documentation and ROADMAP
- Update `ROADMAP.md` and `docs/brainstorms/temporal-query-language.md`

## Verification

1. `pytest tests/test_tql.py tests/test_tql_integration.py -v` — all new TQL tests pass
2. `pytest` — full suite green (no regressions except deliberate `updated_at` → `created_at` semantic change)
3. Boundary test: seed both `T+00:00` and space-format rows, exercise `since` AND `until` against both
4. Manual: `ec decision search "auth" --until v0.8.0` against real DB
5. Manual: `ec decision list --since 2026-06-01 --until 2026-07-01` against real DB
