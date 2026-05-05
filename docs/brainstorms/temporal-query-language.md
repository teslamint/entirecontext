# Temporal Query Language (TQL)

_Draft brainstorm. Created 2026-04-27. Milestone: v0.8.0. Confidence: 88%._

## Intent

Add `--at <ref>`, `since:`, and `between:` syntax to all retrieval commands so queries evaluate against memory state at a specific git commit or time range. EntireContext's unique moat is git-anchored time-travel; no competitor offers point-in-time memory queries. TQL exposes that moat as a first-class CLI and MCP interface.

User-visible outcomes:

- `ec search "auth refactor" --at HEAD~20` returns only decisions and turns that existed at commit `HEAD~20`.
- `ec decision list since:2026-03-01` returns decisions created after a given date.
- `ec decision search "caching" between:2026-02-01..2026-04-01` narrows retrieval to a two-month window.
- All retrieval commands share the same TQL token syntax; agents learn one pattern.

## Scope

### In

- TQL parser module (`core/tql.py`): strips `since:`, `between:`, `--at` tokens from query strings before FTS5 evaluation; resolves git refs to UTC timestamps via `git log --format=%ci`.
- `WHERE created_at <= resolved_ts` filter added to all retrieval queries that support TQL.
- Initial surface: `ec search`, `ec decision search`, `ec decision list`, `ec decision related`.
- `--at <sha|branch|tag>` flag: resolves to commit timestamp; filters all results to `created_at <= that timestamp`.
- `since: <date|ref>` inline token: resolves to lower-bound timestamp filter.
- `between: <date|ref>..<date|ref>` inline token: resolves to lower-bound + upper-bound timestamp filter.
- Timezone normalization: all stored `created_at` values treated as UTC; user-supplied dates interpreted with local offset then converted to UTC.
- Unit tests for token parsing, git ref resolution, date parsing (ISO 8601, relative refs), and timezone conversion.

### Out

- Schema replay or migration rewind at a given ref (separate `ec rewind` concern; TQL is query-only).
- Graph or dashboard temporal filtering (deferred to v0.8.x after core TQL is validated).
- MCP TQL exposure (v0.8.0 candidate; deprioritized relative to CLI surface).
- `--at` semantics for write operations (TQL is read-only).

## TQL Token Specification

| Token | Format | Example | Resolves to |
|---|---|---|---|
| `--at <ref>` | CLI flag; git ref or ISO date | `--at HEAD~20`, `--at 2026-03-01` | Upper-bound timestamp (inclusive) |
| `since:<date\|ref>` | Inline query prefix; stripped before FTS | `since:2026-03-01 auth` | Lower-bound timestamp |
| `between:<a>..<b>` | Inline query prefix; stripped before FTS | `between:2026-02-01..2026-04-01` | Lower + upper bounds |

Tokens are stripped from query text before FTS5 evaluation. Remaining text is the search query. Stripping must handle leading/trailing whitespace to avoid empty FTS5 queries.

## Parser Design Contract

```
# Preprocessor pipeline (before FTS5)
raw_query  →  extract_tql_tokens(raw_query)
          →  (tql_context: {since, until, at_ref}, clean_query: str)

# git ref resolution
resolve_ref(ref) → UTC timestamp  (subprocess: git log -1 --format=%ci <ref>)

# DB filter injection
WHERE created_at >= <since_ts>  (if since set)
  AND created_at <= <until_ts>  (if at or between upper set)
```

The preprocessor must handle the case where `clean_query` is empty after stripping (valid: time-range filter with no text query, returns all records in range).

**FTS5 conflict risk:** `since:`, `between:` with a colon are valid FTS5 column filter syntax. The TQL preprocessor must strip these tokens before they reach FTS5, or FTS5 will attempt to match against a column named `since` or `between` (which does not exist) and return an error. This is the highest implementation risk.

## Proposed Action Items

### v0.8.0 Core

[ ] Define the complete TQL token grammar in a spec comment at the top of `core/tql.py`. Include edge cases: empty clean query, overlapping since/between/at, invalid ref format.

[ ] Implement `core/tql.py`: `parse_tql(query_str) -> TQLContext`. Strip tokens, resolve refs via `git log`, normalize timestamps to UTC. Raise `TQLParseError` for invalid syntax.

[ ] Verify that FTS5 does not receive `since:` or `between:` tokens. Add explicit test for FTS5 error when stripping is skipped.

[ ] Add `apply_tql_filter(query, tql_context) -> query_with_where_clauses` helper that injects `created_at` bounds into SQLite query strings.

[ ] Wire TQL into `core/hybrid_search.py`: `fts_search_decisions`, `hybrid_search_decisions`, `list_decisions`.

[ ] Wire TQL into `cli/search_cmds.py` and `cli/decision_cmds.py`: accept `--at` flag; parse inline tokens from query argument.

[ ] Add timezone handling: parse user-supplied ISO dates with local offset; normalize to UTC before DB comparison. Test with UTC+9 and UTC-5 offsets.

[ ] Unit tests: token parsing (all three forms), git ref resolution (mock subprocess), empty clean query, overlapping tokens, FTS5 non-collision, timezone normalization.

[ ] Integration test: query against a repo with decisions at known timestamps; verify `--at <old-sha>` excludes newer decisions.

[ ] Update README, MCP tool documentation (note: MCP TQL deferred), CHANGELOG, and ROADMAP.

## Risks

- FTS5 token collision: `since:` is valid FTS5 column-filter syntax. If the preprocessor fails to strip the token before FTS5 receives it, queries will return FTS5 errors or wrong results. This is the highest-severity implementation risk and must be covered by a dedicated test.
- Git subprocess latency: `git log -1 --format=%ci <ref>` is a subprocess call. For `--at HEAD`, this is fast; for a remote ref or a large repo, it may add 100–500ms. Consider caching within a single query evaluation.
- Timezone correctness: SQLite stores timestamps without timezone info. If `created_at` values were stored in local time rather than UTC in older schema versions, TQL filters will be wrong for historical records.
- Empty FTS5 query: `ec search "since:2026-01-01"` strips to empty string. FTS5 MATCH '' returns an error. The preprocessor must convert empty clean query to a non-FTS path (list all records in range).
- Ambiguous `between:` upper bound: `between:2026-02-01..2026-04-01` — is April 1st inclusive or exclusive? Must be documented in the spec.

## Review Questions

- Preprocessor approach (strip inline tokens before FTS) vs separate CLI flags only (`--since`, `--until`, `--at`)? Inline tokens are more ergonomic for agents in MCP contexts; separate flags are safer for FTS5 collision avoidance.
- Is the `since:<date>` colon syntax genuinely novel enough to justify FTS5 collision risk, or should the token format use a different separator (e.g., `since=2026-03-01`, `@2026-03-01`)?
- How should `--at <ref>` interact with `since:` in the same query — should they be additive (at sets upper bound, since sets lower) or should they conflict with an error?
- Should `between:` bounds be inclusive on both ends, or exclusive on the upper end (standard range convention)?
- Should MCP tools expose `--at` and `since:` as structured parameters rather than inline query tokens?
