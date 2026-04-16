# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Retrieval telemetry completeness** (#70) — PostToolUse and SessionStart hooks now record per-decision `retrieval_selections` rows alongside the existing `retrieval_events` row, threading `selection_id` into Markdown fallback files. `record_retrieval_event` and `record_retrieval_selection` in `core/telemetry.py` accept a `commit` parameter (default `True`) so hook callers can defer commits for atomicity.
- **Contract-sync drift guards** — `tests/test_contract_sync.py` asserts `mcp/server.__all__` matches what `register_tools()` actually registers (driven by AST extraction of `server.py`'s module tuple, not a hardcoded copy), that every `ec_*` tool is present in the README `### Available Tools` section bidirectionally (catches stale rows as well as missing rows), that `decision_hooks` fallback filename constants are documented in README, and that the current `SCHEMA_VERSION` is cross-referenced in a CHANGELOG paragraph that also mentions "schema". Replaces `tests/test_mcp_registration.py`, whose hardcoded expected set had silently drifted (its registration loop omitted `tools.decision_candidates` and its expected set omitted the four candidate tools, so it passed via symmetric drift — the exact failure mode the v0.2.0 retrospective finding #2 named).

## [0.2.0] - 2026-04-15

v0.2.0 narrows EntireContext around proactive decision memory for coding agents: past decisions surface automatically from current-change signals, staleness and contradictions no longer dominate retrieval, and new captures can enter via a reviewable candidate pipeline.

Database schema v11 → v13. v0.1.x databases auto-migrate on first `RepoContext` connection via `check_and_migrate`: v12 adds `decisions.auto_promotion_reset_at`, v13 adds the `decision_candidates` table (plus FTS5 mirror and triggers). Both migrations are additive — no data rewrite.

### Added

- **Proactive decision retrieval** (#42) — new `ec_decision_context` MCP tool assembles signals from the current session (recent turns' files, uncommitted git diff, latest checkpoint SHA) and returns ranked decisions in a single call. Each result includes a `selection_id` agents can pass directly to `ec_decision_outcome`/`ec_context_apply`. The tool degrades gracefully when there is no active session, falling back to git-diff-only signals with `signal_summary.active_session=false`.
- **Mid-session surfacing hook** (#42) — new PostToolUse hook `on_post_tool_use_decisions` surfaces decisions linked to just-edited files. Writes Markdown to `.entirecontext/decisions-context-tooluse-<session>.md` (session-qualified so concurrent sessions in the same repo cannot clobber each other) and also prints to stdout. SessionStart writes its own separate file `.entirecontext/decisions-context.md`. Gated by `decisions.surface_on_tool_use` (default off), with per-turn and session-wide deduplication and rate limiting via `decisions.surface_on_tool_use_turn_interval`. Session-start surfacing now populates the shared dedup set so decisions shown at session start are not re-surfaced mid-session.
- **Signal-based decision ranking** (#40) — `rank_related_decisions` replaces the 200-row recency scan with a candidate-first architecture that unions signals from files, assessments, diff FTS, and commit SHAs, scoring with five weighted signals plus a staleness penalty. Results include a `score_breakdown` for observability, and `ec_decision_related` accepts a new `commit_shas` parameter.
- **Candidate decision extraction pipeline** (#41) — new `decision_candidates` table (schema v13) collects drafts from sessions, checkpoints, and assessments, scores them with a reproducible confidence heuristic, dedupes via FTS5 similarity, and exposes a confirmation flow through `ec decision candidates list/show/confirm/reject` and the `ec_decision_candidate_*` MCP tools. Confirmation is atomic via claim-then-promote so concurrent CLI/MCP confirms cannot create duplicate decision rows, and turn-window derivation uses SQLite-normalized timestamps so same-day checkpoint bundles are never silently dropped. Gated by `[decisions] auto_extract` (default off).
- **Decision keyword search** (#45) — new `ec_decision_search` MCP tool, `ec decision search` CLI command, and `fts_search_decisions`/`hybrid_search_decisions` core APIs wire the existing `fts_decisions` FTS5 table into keyword and hybrid-RRF search with cross-repo ranking and search telemetry.
- **New flags on decision search and retrieval** (#39) — FTS and hybrid decision search accept `include_stale`, `include_superseded`, and `include_contradicted`. `get_decision` surfaces an immediate `successor` pointer when the decision is superseded. New CLI command `ec decision chain <id>` walks the supersession chain for debugging.
- **Auto-promotion from outcome feedback** (#39) — `record_decision_outcome` runs inside a `BEGIN IMMEDIATE` transaction and auto-promotes `staleness_status` to `contradicted` when a decision accumulates ≥2 contradicted outcomes that outnumber accepted outcomes. One-way ratchet — recovery requires manual `ec decision stale --status fresh`, which also resets the auto-promotion baseline. Threshold configurable via `[decisions] auto_promotion_contradicted_threshold`.
- **Supersession cycle detection** (#39) — `supersede_decision` walks the target's chain before writing and rejects inputs that would create a multi-hop cycle. `resolve_successor_chain` is also defended by a depth cap.

### Changed

- **Staleness filtering default behavior** (#39) — `rank_related_decisions` now hard-filters superseded and contradicted decisions by default and collapses supersession chains to their terminal successor. Fallback padding respects the same policy, and the session-start hook uses a single batched query applying the same central filter. Pre-v0.2.0 callers that relied on the prior lenient default should opt in to `include_stale`/`include_superseded`/`include_contradicted` as needed.
- **Product positioning and docs** (#38) — README now leads with decision memory as the wedge, reorganizes "How Decision Memory Works" above the capability list, splits Key Capabilities into core (decision memory) and supporting, and promotes decision tools to the top of the MCP tool table. AGENTS.md template extracted into a standalone doc. Lesson retrieval added as a sibling to decision reuse in agent instruction templates.

### Deprecated

- **`fts_search_decisions` / `hybrid_search_decisions` / `ec decision search` `include_contradicted` default** — currently defaults to `True` for backward compatibility during v0.2.x. The default will flip to `False` in **v0.3.0**. Pass `include_contradicted=False` (or `--no-include-contradicted` from the CLI) now to opt into the future default.

### Fixed

- **MCP input normalization and query errors** (#44) — MCP tool `repos` parameters accept `str | list[str] | None` (scalar strings coerced to single-item lists); `ec_decision_create` coerces scalar `rejected_alternatives`/`supporting_evidence` to lists; FTS5 syntax errors return actionable JSON error payloads instead of opaque failures. The `repos=["*"]` wildcard contract is preserved.

## [0.1.1] - 2026-04-09

### Fixed

- **SQLite ResourceWarnings** — added context manager protocol to `RepoContext`/`GlobalContext`, converted all CLI and hook callers to guaranteed cleanup via `with` statements or `try/finally`

### Changed

- **Release workflow** — publish now gated on lint + test jobs; added install smoke test (`ec --help`) before artifact upload
- **Package metadata** — added PyPI classifiers (Alpha, MIT, Python 3.12/3.13, Typed) and project URLs (Homepage, Repository, Issues, Changelog)
- **Release artifacts** — LICENSE and CHANGELOG.md now explicitly included in sdist via `source-include`

## [0.1.0] - 2026-04-09

Initial release of EntireContext: git-anchored decision memory for coding agents.

### Added

- **Core capture loop** — sessions, turns, tool calls, and checkpoints recorded through Claude Code hooks and anchored to git history
- **Decision model** — first-class decision records with outcome tracking, quality scoring, staleness detection, supersede/unlink, and FTS search
- **Decision hooks** — automatic extraction (`maybe_extract_decisions`), stale check (`maybe_check_stale_decisions`), and session-start context surfacing (`on_session_start_decisions`)
- **Assessments & feedback** — futures assessments, typed relationships, feedback loops, lessons, and trend analysis
- **Search** — regex, FTS5, semantic (sentence-transformers), and hybrid search across sessions and repos
- **AST index** — symbol-level search via tree-sitter integration
- **Knowledge graph** — entity and relationship graph with traversal and visualization
- **Git time-travel** — checkpoints, rewind, blame, and historical inspection
- **MCP server** — 20+ tools for in-session retrieval (search, checkpoints, assessments, graph, trends, decisions, dashboard)
- **Sync** — shadow branch export/import for cross-machine and cross-repo memory sharing
- **CLI** — comprehensive Typer-based CLI (`ec`) with subcommands for all features
- **Dashboard** — project health and activity overview
- **Cross-repo support** — per-repo local DB + global DB for broader learning patterns
- **Hook system** — 5 hook types (SessionStart, UserPromptSubmit, Stop, PostToolUse, SessionEnd) with stdin JSON protocol
- **Config** — TOML deep merge (defaults, global, per-repo) with security filtering and query redaction
- **Async workers** — background task execution for non-blocking hook operations

### Infrastructure

- Python 3.12+, uv build system
- SQLite with WAL mode, schema version 6
- FTS5 virtual tables with auto-sync triggers
- Hybrid storage: SQLite metadata + JSONL content files
- MIT license
