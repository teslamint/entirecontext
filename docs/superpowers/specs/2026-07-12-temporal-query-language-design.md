# Temporal Query Language (TQL) Design

_Created 2026-07-12._

## Overview

Add `--until` and broadened `--since` temporal filters to EntireContext's core retrieval commands so queries evaluate against memory state at a specific git commit or time range. Both flags accept git refs and ISO dates. EC's unique moat is git-anchored time travel; TQL exposes it as a first-class CLI and MCP interface.

No inline query tokens (`since:`, `between:`) — CLI flags and MCP structured parameters only. This eliminates the FTS5 column-filter collision risk entirely.

## User Scenarios

### 1. Point-in-time decision lookup — "Why is this code like this?"

Find auth-related decisions **recorded** before the v0.8.0 release:

```bash
ec decision search "auth" --until v0.8.0
```

Returns only decisions whose `created_at` is before the v0.8.0 commit timestamp. Decisions recorded later are excluded, even if they describe older code.

### 2. Sprint decision roundup — time-range listing

List all decisions made during the first two weeks of June for a retro:

```bash
ec decision list --since 2026-06-01 --until 2026-06-14
```

### 3. Cross-release decision comparison — tag-to-tag range search

Find search-related decisions **recorded** between the v0.10.0 and v0.13.0 release timestamps:

```bash
ec decision search "search" --since v0.10.0 --until v0.13.0
```

Filters by `created_at` (recording time), not by the code era a decision describes. See [Semantics & Limitations](#semantics--limitations).

### 4. Agent MCP context lookup — decisions recorded before a specific point

An agent queries only decisions whose `created_at` is before v0.10.0 when preparing to modify `src/core/search.py`:

```python
ec_decision_related(file_paths=["src/core/search.py"], until="v0.10.0")
```

Decisions recorded after v0.10.0 are excluded from the candidate set before ranking.

### 5. Early architecture decisions — upper-bound filter only

Review architecture decisions **recorded** before mid-April (project early phase):

```bash
ec decision search "architecture" --until 2026-04-15
```

### 6. General search with time range — adding upper bound to existing `--since`

Search migration-related turns/sessions within a one-week window:

```bash
ec search "migration" --since 2026-07-05 --until 2026-07-10
```

## Scope

### In

- `core/tql.py` module: `TQLContext` dataclass, git ref resolution, ISO date parsing, temporal filter injection
- `--until <ref|date>` flag: upper-bound timestamp filter (accepts git refs and ISO dates)
- `--since` broadening: add to `ec decision list` and `ec decision related` (currently missing); both `--since` and `--until` accept git refs and ISO dates
- CLI commands: `ec search`, `ec decision search`, `ec decision list`, `ec decision related`
- MCP tools: `ec_search`, `ec_decision_search`, `ec_decision_list`, `ec_decision_related` — add `until` structured parameter
- Timestamp normalization via SQLite `datetime()` for mixed-format comparison
- Date-only `--until` inclusive expansion (end-of-day)
- `rank_related_decisions()` pre-filter by temporal bounds

### Out

- Inline query tokens (`since:`, `between:`) — eliminated by design (FTS5 collision avoidance)
- Schema changes — all filtering uses existing indexed `created_at`/`timestamp`/`started_at` columns
- Session, event, checkpoint, graph, dashboard temporal broadening (v2)
- MCP-only TQL features beyond the 4 target tools
- `--until` for write operations (TQL is read-only)
- PDI ranking temporal override (PDI uses live signal, not point-in-time)

## Architecture

### TQL Context Model

```python
@dataclass
class TQLContext:
    since: str | None = None   # lower-bound UTC timestamp (inclusive)
    until: str | None = None   # upper-bound UTC timestamp (exclusive for date-only, inclusive for datetime)
```

Both fields store normalized UTC timestamps (output of `datetime()`).

### Temporal Ref Resolution

```python
def resolve_temporal_ref(ref: str, *, repo_path: str | None = None) -> str:
    """Resolve git ref or ISO date string to normalized UTC timestamp.

    Resolution order:
    1. Try ISO 8601 date/datetime parse
    2. Try git ref resolution via `git log -1 --format=%cI <ref>`
    3. Raise TQLError on failure
    """
```

- Git ref resolution uses `%cI` (strict ISO 8601: `2026-07-12T12:34:56+09:00`) for reliable timezone handling
- The resolved timestamp is normalized via `datetime()` to `YYYY-MM-DD HH:MM:SS` UTC
- Subprocess timeout: 5 seconds (prevents hangs on invalid refs in large repos)

### Date-Only Upper Bound Expansion

When `--until` receives a date-only value (no time component):

- `--until 2026-04-01` → `until = "2026-04-02 00:00:00"` with `<` operator (half-open: includes all of April 1st)
- `--until 2026-04-01T15:00:00` → `until = "2026-04-01 15:00:00"` with `<=` operator (exact)

Detection: if the resolved timestamp has `00:00:00` time and the original input had no `T` or time separator, treat as date-only.

### Timestamp Normalization

The database has mixed timestamp formats:
- Python writes: `2026-07-12T12:34:56.123456+00:00` (ISO 8601 with fractional seconds and UTC offset)
- SQLite DEFAULT: `2026-07-12 12:34:56` (space-separated, naive)

All WHERE clauses use `datetime(col)` to normalize: `datetime('2026-07-12T12:34:56.123456+00:00')` → `2026-07-12 12:34:56`.

### Filter Injection

```python
def apply_temporal_filters(
    conditions: list[str],
    params: list,
    tql: TQLContext | None,
    column: str,
) -> None:
    """Append WHERE clause fragments and params for temporal bounds."""
```

Injects:
- `datetime({column}) >= datetime(?)` when `tql.since` is set
- `datetime({column}) < datetime(?)` or `datetime({column}) <= datetime(?)` when `tql.until` is set (operator depends on date-only expansion)

## Interface

### CLI Flags

| Flag | Accepts | Semantics |
|------|---------|-----------|
| `--since <ref\|date>` | git ref, ISO date, date-only | Lower bound (inclusive) |
| `--until <ref\|date>` | git ref, ISO date, date-only | Upper bound (inclusive for datetime, half-open for date-only) |

Both flags accept the same input types. Git refs are resolved to their commit timestamp via `resolve_temporal_ref()`.

**Validation rules:**
- `--since` > `--until` → error: "Empty time range: --since is after --until"
- Invalid git ref → error: "Cannot resolve temporal reference '<ref>': not a valid git ref or date"

**Examples:**
```bash
ec search "auth refactor" --until HEAD~20
ec search "auth" --since 2026-01-01 --until 2026-04-01
ec decision search "caching" --until v0.8.0
ec decision list --since 2026-03-01
ec decision related --file src/core/search.py --until v0.10.0
```

### MCP Structured Parameters

Each of the 4 target MCP tools gains:

| Parameter | Type | Description |
|-----------|------|-------------|
| `until` | `str \| None` | Upper-bound filter — accepts git refs or ISO dates |

Existing `since` parameter remains unchanged and is broadened to also accept git refs (currently ISO dates only). Both `since` and `until` resolve git refs via `resolve_temporal_ref()` using the project's `repo_path`.

## Data Model

### Column Mapping Per Target Type

| Target | Column for temporal filter | Rationale |
|--------|---------------------------|-----------|
| turn | `t.timestamp` | Primary temporal column (existing `since` behavior) |
| session | `s.started_at` | Session start time (existing behavior) |
| event | `e.created_at` | Event occurrence time (existing behavior) |
| decision (search/list) | `d.created_at` | **Changed from `d.updated_at`**: point-in-time existence semantics |
| decision (rank_related) | `d.created_at` | Pre-filter candidates before scoring |

**Breaking change:** Existing `--since` on `ec decision search` and `ec_decision_search` changes from `d.updated_at` to `d.created_at`. This aligns with TQL's point-in-time semantics: "decisions that existed since date X" means decisions *created* since X, not decisions *updated* since X. The existing `updated_at` filter was a recency convenience, not a temporal query feature. Impact: low — decision list default ordering remains `updated_at DESC`.

**Caller audit (verified):** Only CLI (`decisions_cmds.py`) and MCP (`mcp/tools/decisions.py`) call `fts_search_decisions`/`hybrid_search_decisions`. `cross_repo.py` does not call these functions. No internal caller depends on `updated_at` recency semantics.

### Existing Indexes

All target columns already have descending indexes:
- `idx_turns_timestamp` on `turns(timestamp DESC)`
- `idx_sessions_activity` on `sessions(last_activity_at DESC)` — `started_at` needs no index for TQL v1 (small table)
- `idx_decisions_updated_at` on `decisions(updated_at DESC)`

**No new index needed.** The decisions table is small (current: 127 rows) and `datetime()` wrapping in WHERE clauses defeats raw-column indexes. A full scan on 127 rows is sub-millisecond. If the table grows significantly, add an expression index `CREATE INDEX ... ON decisions(datetime(created_at) DESC)` or normalize stored timestamps — defer to v2.

## Integration

### Core Search Functions

**`core/search.py`:** Add `until: str | None = None` parameter to:
- `regex_search()`, `fts_search()`, `hybrid_search()` — outer dispatch functions
- `_regex_search_turns()`, `_fts_search_turns()` — inject `AND datetime(t.timestamp) <= datetime(?)`
- `_regex_search_sessions()`, `_fts_search_sessions()` — inject `AND datetime(s.started_at) <= datetime(?)`
- `_regex_search_events()`, `_fts_search_events()` — inject `AND datetime(e.created_at) <= datetime(?)`

**`core/decisions.py`:** Changes:
- `fts_search_decisions()` — change `updated_at` to `created_at`; add `until` parameter
- `hybrid_search_decisions()` — pass `until` through
- `list_decisions()` — add `since` and `until` parameters
- `rank_related_decisions()` — add `since` and `until` parameters; pre-filter candidate set before scoring

### CLI Commands

**`cli/search_cmds.py`:**
- Add `--until` option to `search` command
- Resolve both `--since` and `--until` via `resolve_temporal_ref()` when they contain git refs
- Pass resolved values to core search functions

**`cli/decisions_cmds.py`:**
- `decision search` — add `--until`
- `decision list` — add `--since`, `--until` (both new)
- `decision related` — add `--since`, `--until` (both new, requires `rank_related_decisions` extension)

### MCP Tools

**`mcp/tools/search.py`:** `ec_search` — add `until` parameter
**`mcp/tools/decisions.py`:** `ec_decision_search`, `ec_decision_list`, `ec_decision_related` — add `until` parameter

Git ref resolution happens in the MCP tool function before calling core. MCP tools must pass `repo_path` from the project context for `resolve_temporal_ref()`.

## Testing

### Unit Tests (`tests/test_tql.py`)

1. **Ref resolution:** git ref → UTC timestamp (mock subprocess), ISO date parsing, date-only detection
2. **Date-only expansion:** `2026-04-01` → `< 2026-04-02 00:00:00`; `2026-04-01T15:00:00` → `<= 2026-04-01 15:00:00`
3. **Filter injection:** `apply_temporal_filters()` generates correct WHERE fragments and params
4. **Validation:** `--since` > `--until` empty range, invalid ref, non-existent git ref
5. **Timezone normalization:** `+09:00` offset → UTC conversion via `datetime()`
6. **Mixed timestamp format comparison:** seed both `T+00:00` and space-format rows, verify filters match correctly

### Integration Tests (`tests/test_tql_integration.py`)

1. **Decision search with `--until`:** create decisions at known timestamps, verify `--until <old-sha>` excludes newer decisions
2. **Decision list with time range:** `--since A --until B` returns correct subset
3. **Decision related with pre-filter:** verify temporal bounds exclude decisions from candidate set before ranking
4. **`ec search` with `--until`:** verify turns/sessions/events filtered by upper bound
5. **`created_at` semantic assertion:** a decision created before `--since` but updated after must **not** appear (previously it would under `updated_at`); a decision created after `--since` but not updated since must appear (positive semantic test)
6. **FTS5 non-collision:** verify no inline token stripping needed — FTS5 receives clean query strings

### Boundary Tests

7. **Both stored formats:** seed rows with `2026-04-01T12:00:00+00:00` and `2026-04-01 12:00:00` for the same logical time; verify temporal filter treats them identically
8. **Date-only boundary:** `--until 2026-04-01` includes row at `2026-04-01 23:59:59`, excludes row at `2026-04-02 00:00:01`
9. **Empty result set:** temporal filter narrows to zero results — no error, empty list

## Semantics & Limitations

TQL filters by **recording time** (`created_at`), not by the historical era a decision describes. For naturally recorded decisions (created during the session that made the choice), these coincide. For archaeology-bootstrapped decisions (`source:archaeology`), `created_at` is the batch extraction timestamp — all archaeologized decisions cluster within seconds of each other regardless of the code era they describe.

Consequence: `--until <old-ref>` on an archaeology-bootstrapped corpus may exclude every archaeologized decision (all recorded after the archaeology run). This is coherent with the "records that existed at commit X" semantics but does not provide "decisions about the repo state at commit X." True historical-era querying would require a separate `decision_era` column anchored to the decision's source commit, which is out of scope for TQL v1.

**Resolution order note:** `resolve_temporal_ref()` tries ISO date parsing before git ref resolution. A git tag that looks like a date (e.g., tag named `2026-04-01`) will be interpreted as a date, not resolved as a ref. This is acceptable — date-shaped tags are extremely rare in practice.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| `datetime()` wrapping defeats index usage on large tables | Low (127 decisions) | Measure query time; defer timestamp normalization to v2 if needed |
| Git subprocess latency for ref resolution | Low | 5s timeout; cache within single CLI invocation |
| `updated_at` → `created_at` breaking change on existing `--since` | Low | Document in CHANGELOG; no users rely on `updated_at` recency filtering in automation |
| Mixed timestamp format causing off-by-one | Medium | `datetime()` normalization + boundary tests with both formats seeded |
| Date-only vs datetime ambiguity in `--until` | Low | Detection heuristic: no `T`/time separator → date-only expansion |

## Open Decisions

None — all design questions resolved during the Design phase.
