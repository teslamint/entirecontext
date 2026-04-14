# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Proactive decision retrieval** (#42) — new `ec_decision_context` MCP tool assembles signals from the current session (recent turns' files + uncommitted git diff + latest checkpoint SHA) and returns ranked decisions in a single call. Each result includes a `selection_id` agents can pass directly to `ec_decision_outcome`/`ec_context_apply`. The tool degrades gracefully when there is no active session, falling back to git-diff-only signals with `signal_summary.active_session=false`.
- **Mid-session surfacing hook** (#42) — new PostToolUse hook `on_post_tool_use_decisions` surfaces decisions linked to just-edited files. Writes Markdown to `.entirecontext/decisions-context.md` (primary delivery) and prints to stdout. Gated by `decisions.surface_on_tool_use` (default off), with per-turn and session-wide deduplication and rate limiting via `decisions.surface_on_tool_use_turn_interval`. Session-start surfacing now also populates the shared dedup set so decisions shown at session start are not re-surfaced mid-session.
- **Staleness hardening in retrieval** (#39) — `rank_related_decisions` hard-filters superseded and contradicted decisions by default, collapses supersession chains to their terminal successor, and fixes fallback padding to respect the same policy. FTS and hybrid decision search now accept `include_stale`, `include_superseded`, and `include_contradicted` flags. `get_decision` surfaces an immediate `successor` pointer when the decision is superseded. New CLI command `ec decision chain <id>` walks the supersession chain for debugging. Session-start hook uses a single batched query and applies the same central filter policy.
- **Auto-promotion from outcome feedback** (#39) — `record_decision_outcome` now runs inside a `BEGIN IMMEDIATE` transaction and auto-promotes `staleness_status` to `contradicted` when a decision accumulates ≥2 contradicted outcomes that outnumber accepted outcomes. One-way ratchet — recovery requires manual `ec decision stale --status fresh`. Threshold configurable via `[decisions] auto_promotion_contradicted_threshold`.
- **Supersession cycle detection** (#39) — `supersede_decision` walks the target's chain before writing and rejects inputs that would create a multi-hop cycle. `resolve_successor_chain` is also defended by a depth cap.

### Deprecated

- **`fts_search_decisions` / `hybrid_search_decisions` / `ec decision search` include_contradicted default** — currently defaults to `True` for backward compatibility during v0.2.x. The default will flip to `False` in **v0.3.0**. Pass `include_contradicted=False` (or `--no-include-contradicted` from the CLI) now to opt into the future default.

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
