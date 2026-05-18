# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.0] - 2026-05-10

v0.6.0 advances the outcome lifecycle core for decision memory. Database schema v14 widens decision outcome vocabulary, supersession now records replacement feedback, and candidate confirmation records the commit that introduced the promoted decision.

### Added

- **Schema v14 outcome lifecycle** — `decision_outcomes.outcome_type` now accepts `refined` and `replaced` in addition to `accepted`, `ignored`, and `contradicted`. CLI and MCP outcome recording accept all five values, and `decision show`/hook output display the full breakdown so audit output matches stored data.
- **Supersede → replaced auto-linkage** — `supersede_decision` records an atomic `replaced` outcome on the old decision when it is superseded. Re-superseding updates only the auto-generated replacement row, preserving user-authored `replaced` notes and preventing duplicate auto rows.
- **Candidate confirmation commit linkage** — confirmed decision candidates now link the promoted decision to the current commit SHA, preserving the git anchor for decisions created from the candidate pipeline.

### Changed

- **Outcome feedback reporting** — `get_file_outcome_stats` reports non-zero `refined` and `replaced` counts so file-level outcome summaries reflect the expanded schema. Extraction confidence penalties still compute their trigger from scored outcomes only (`accepted`, `ignored`, `contradicted`), so neutral `refined`/`replaced` feedback remains visible without diluting contradicted-history demotion.
- **Dependency lock refresh** — refreshed the lockfile for the current development toolchain, including the Typer dependency update and Hypothesis-based confirmation tests.

## [0.5.0] - 2026-04-27

v0.5.0 closes 3x-deferred correctness debt before adding new feature surface — zero new product features, zero schema changes. Still schema v13.

### Changed

- **Autocommit migration (S2b — closes D.5)** — `db/connection.py:_configure_connection` now sets `conn.autocommit = True` so each DML statement self-commits unless an explicit `with transaction(conn):` boundary is open. The `core/context.py:transaction()` helper is rewritten with a per-connection depth counter (`conn._ec_tx_depth`) replacing the LEGACY-mode `conn.in_transaction` nesting detector, which is unreliable under autocommit. Two plan deviations driven by Python sqlite3 reality: (1) `sqlite3.Connection` is a C type with no `__dict__`, so a new `_ECConnection` subclass is threaded as `factory=` through all three connection factories plus the four direct `sqlite3.connect()` callsites in `core/cross_repo.py`; (2) under `conn.autocommit=True`, `conn.commit()`/`rollback()` are no-ops on transactions opened by explicit `BEGIN IMMEDIATE`, so the helper now issues `conn.execute("COMMIT")`/`("ROLLBACK")`. `tests/test_transaction_helper.py` rewritten to behavioral assertions on the depth counter; `tests/test_decisions_core.py`'s 6 `in_transaction` sites updated (4 assertion conversions, 2 manual-`BEGIN IMMEDIATE` sites coordinated with `_ec_tx_depth`-bracketing and `execute("ROLLBACK")`). `core/ast_index.py:index_file_ast` (DELETE + INSERT-loop multi-DML, missed by S2a's audit) is now wrapped in `with transaction(conn):` to preserve atomicity under autocommit, with a regression test in `tests/test_ast_index.py::TestIndexFileAstAtomicity`. The `core/telemetry.py` `record_retrieval_event(commit=...)`/`record_retrieval_selection(commit=...)` parameters introduced in v0.3.0 are removed — under autocommit the deferral they expressed is a semantic lie, and the three production callers (`core/decision_prompt_surfacing.py`, `hooks/decision_hooks.py` ×2) now wrap their telemetry blocks in `with transaction(conn):`. ~58 redundant single-DML `conn.commit()` callsites across `core/` (33), `hooks/` (17), `db/` (3), and `sync/` (5) are removed; three multi-DML hook regions (`hooks/turn_capture.py:on_user_prompt_submit` + `on_stop`, `hooks/session_lifecycle.py:_populate_session_summary`) plus `sync/auto_sync.py:acquire_sync_lock` get explicit `with transaction(conn):` wraps to preserve their atomicity under autocommit. `tests/test_no_internal_commit.py:ALLOWLIST` collapses from 14 entries to empty; future `conn.commit()` calls in `core/` are now ratcheted out by default. The v0.3.0 `commit=False` deferred-commit test is deleted (its contract no longer exists). Tracks ec decision `dcc64267` (D.5 — now closed).
- **Multi-DML atomicity foundation (S2a)** — `link_decision_to_commit` (`core/decisions.py`, completing the link-helper family alongside the 4 siblings landed in S1), `consolidate_turn_content` file-present branch (`core/consolidation.py`), all six `_import_*` phase commits (`core/import_aline.py`), `generate_embeddings` (`core/embedding.py`), and `rebuild_fts_indexes` (`core/search.py`) now wrap their multi-DML regions in `with transaction(conn):` from `core/context.py`. Under current Python 3.12 LEGACY transaction control this is behavior-preserving on the success path. The point is to make the upcoming S2b autocommit flip semantically safe — without these wraps, those regions would lose atomicity under `autocommit=True` (each DML committing independently, partial-write on crash). Side benefit: the Aline import path now rolls back per-phase batches when an exception escapes the per-row swallow (previously the connection was left in an open implicit tx with no commit/rollback). The ratchet at `tests/test_no_internal_commit.py:ALLOWLIST` tightens by three files (`embedding.py`, `search.py`, `import_aline.py`). Single-DML `conn.commit()` sites stay statement-atomic and defer to S2b. Python 3.13 added to the CI test-job matrix at `.github/workflows/ci.yml`; lint job stays 3.12-only. Tracks ec decision `dcc64267`.
- **`confirm_candidate` atomic promotion (S1)** — `core/decision_candidates.confirm_candidate`'s Step 2 promotion (decision creation + provenance links + `promoted_decision_id` back-pointer) is now wrapped in a single `BEGIN IMMEDIATE` transaction via `core/context.py::transaction()`, closing the v0.2.0 gap where a process crash between `create_decision`'s commit and the Step 3 UPDATE left an orphan `decisions` row with no candidate back-pointer. The 4 helpers `create_decision`, `link_decision_to_file`, `link_decision_to_checkpoint`, `link_decision_to_assessment` (`core/decisions.py`) become commit-free internally — they wrap their own DML in `with transaction(conn):` so external callers continue to see auto-commit when invoked outside an outer transaction (the helper's `transaction()` is a no-op when `conn.in_transaction=True`, deferring to the outer owner's commit). Matches the `record_decision_outcome` precedent. `link_decision_to_commit` is unchanged — not called by `confirm_candidate`; deferred to a follow-up if needed. Step 1 atomic claim and Step 2-failure conditional rollback UPDATE retain their own commit boundaries (the claim must persist before promotion to gate concurrency; the rollback runs after the wrapped tx is already torn down). Tracks ec decisions `e59c78eb`, `4c7893b0`.
- **F4 security-model E2E coverage (S3)** — `tests/test_e2e_f4_security_model.py` adds four invariant assertions covering the hook→tmp→subprocess→worker chain, closing the v0.4.0 gap where `tests/test_e2e_feed_the_loop.py` exercised F4's worker in-process via `monkeypatch.setattr("...launch_worker", ...)`. The new test verifies (1) hook-side tmp creation uses `O_EXCL` + `0o600`, (2) the worker re-redacts even when the tmp file is tampered with raw secrets, (3) the worker's `try/finally` removes the tmp on per-repo DB corruption (proving cleanup is from `finally`, not coincidental success-path cleanup), (4) hook-side `O_EXCL` rejects a pre-planted symlink at the tmp path so the target file is never written. Invariants 1 and 4 mock `launch_worker` and exercise the hook in-process; invariants 2 and 3 spawn a real `ec decision surface-prompt` subprocess. New `subprocess_isolated_home` fixture (HOME env redirect) is layered atop existing `isolated_global_db` so subprocesses see an isolated global DB. Tracks ec decision `03ab3e25`.
- **Review-bot post-push noise reduction (S4)** — `.github/workflows/claude-code-review.yml` and `tidy-pilot.yml` now set `concurrency: cancel-in-progress` keyed by PR number, so consecutive `synchronize` events cancel any in-flight review run instead of stacking (addresses the stale-commit race seen on PR #59). The explicit "Skip the already reviewed check entirely" prompt directive in claude-code-review.yml has also been removed, allowing claude-code-action's built-in dedup to suppress trivial re-reviews (e.g., the test-comment garbage on PR #55). `tidy-pilot.yml`'s prompt/script body is unchanged in this PR; same-pattern deeper hardening for the second bot is deferred to a follow-up. Tracks ec decisions `eaa24b32` (D.6 origin) and `e98f85a4` (v0.5.0 implement-not-wontfix commitment).

## [0.4.0] - 2026-04-17

v0.4.0 deepens the decision-memory loop so outcome data flows into both ranking and extraction, and adds UserPromptSubmit as a new retrieval signal channel. No schema change — still v13.

### Added

- **`[decisions.ranking]` config section** (#85) — staleness factors, assessment relation weights, exact-file and git-commit weights, and directory proximity cap are now tunable per repo through the new `[decisions.ranking]` TOML section (defaults unchanged). `rank_related_decisions` accepts a `ranking: RankingWeights` kwarg, and the SessionStart hook and `ec_decision_related` MCP tool load repo config automatically. The `score_breakdown` key set (`file_exact`, `file_proximity`, `assessment`, `diff_relevance`, `git_commit`, `quality`, `staleness_factor`) is now pinned as an additive-only public contract — renames are a breaking change.
- **Outcome recency decay in decision quality score** (#83) — `calculate_decision_quality_score` now accepts an optional `decayed_counts` keyword argument; `rank_related_decisions` feeds it an exponential time-decayed sum per outcome type (`weight = 0.5 ** (age_days / half_life_days)`) so recent feedback dominates historical. Decay lives under `[decisions.quality]` (new namespace, deliberately separate from `[decisions.ranking]`): `recency_half_life_days` (default 30) and `min_volume` (default 2, smooths single-outcome swings toward zero). `half_life<=0` disables decay and falls back to legacy uniform counts. `get_decision_quality_summary` intentionally keeps the legacy 1-arg path so CLI/MCP quality-summary output stays stable.
- **Outcome → extraction confidence penalty** (#84) — candidate extraction now penalizes drafts whose referenced files have a majority-contradicted outcome history in the last N days. New helpers `get_file_outcome_stats` (aggregates across files with SQL-side path normalization matching `_gather_candidates_by_files`) and `apply_outcome_feedback_to_confidence` (applies penalty when `contradicted / total > 0.5`) run inside `run_extraction` between `score_confidence` and the `min_confidence` gate, so bad-history files can push a borderline candidate below the threshold. Config lives in `[decisions.extraction]`: `outcome_feedback_enabled` (default `true`), `outcome_feedback_lookback_days` (default 60), `contradicted_penalty` (default 0.15). The 0.5 ratio gate is intentionally hardcoded — it's the midpoint, not a tunable knob. Breakdown always surfaces `outcome_feedback.{applied, contradicted, accepted, ignored, total, ratio, penalty}` for telemetry/review.
- **UserPromptSubmit async decision surfacing** (#86) — `on_user_prompt` now optionally launches a background worker (`ec decision surface-prompt`) that ranks decisions against the current prompt text plus uncommitted diff and recent commits, writing Markdown to `.entirecontext/decisions-context-prompt-<session>-<turn>.md` (turn-scoped so concurrent prompts don't race). The prompt text is redacted **in-memory** (capture-time `redact_content` + hook-time `filter_secrets` + `redact_for_query`) before any disk write; the tmp file uses `O_EXCL` + mode `0600` to guard against symlink races. The worker re-applies both secret filters as defense-in-depth so a tampered tmp file cannot leak raw secrets into the fallback Markdown. Tmp file is always removed in a `try/finally` regardless of outcome. Config: `[decisions] surface_on_user_prompt` (default `false`), `[decisions] surface_on_user_prompt_limit` (default 3). Telemetry uses `search_type="user_prompt"` so aggregation can distinguish this channel from `session_start` and PostToolUse. Hook passes `--repo-path` explicitly to the worker so detached subprocesses don't rely on ambient cwd.
- **v0.4.0 E2E coverage** (`tests/test_e2e_feed_the_loop.py`) — single-scenario integration test wires F1 decay + F2 extraction penalty + F3 ranking weights + F4 async surfacing against one repo and one decision, including a negative assertion that contradicted decisions are filtered by default and an end-to-end verification that `sk-[A-Za-z0-9]{48}` patterns never reach disk through the hook → tmp → worker → Markdown chain.

## [0.3.0] - 2026-04-17

v0.3.0 closes the decision-memory feedback arc: retrieval records its footprint, extraction quality gets validated before candidates enter the pipeline, and outcome data flows back into ranking. No schema change — still v13.

### Changed

- **BREAKING: `include_contradicted` default flipped to `False`** (#69) — `list_decisions`, `fts_search_decisions`, `hybrid_search_decisions`, `ec_decision_search` MCP tool, and `ec decision search` CLI now exclude contradicted decisions by default. Pass `include_contradicted=True` (or `--include-contradicted` from the CLI) to restore the previous behavior. The `ec_decision_list` MCP tool also gains a new `include_contradicted` parameter (default `False`).

### Added

- **Minimal quality loop** (#73) — `ec_context_apply` with `application_type` of `decision_change` or `code_reuse` now auto-records an "accepted" outcome for the referenced decision. SessionEnd hook can infer "ignored" outcomes for decisions surfaced but never acted upon, with a configurable grace period (`decisions.ignored_inference_min_turn_gap`, default 2) to avoid penalizing decisions surfaced in the final turn. Outcome counts (`accepted`, `ignored`, `contradicted`) are displayed in Markdown output. Config-gated via `decisions.infer_ignored_on_session_end` (default off).
- **Relevance-based SessionStart reactivation** (#72) — SessionStart hook now uses `rank_related_decisions()` with full multi-signal ranking (file paths, uncommitted diff, recent commit SHAs, assessment IDs) instead of the per-file `list_decisions()` loop. Score breakdown is included in Markdown output. Assessment signal lookback is configurable via `decisions.assessment_lookback_hours` (default 48).
- **Retrieval telemetry completeness** (#70) — PostToolUse and SessionStart hooks now record per-decision `retrieval_selections` rows alongside the existing `retrieval_events` row, threading `selection_id` into Markdown fallback files. `record_retrieval_event` and `record_retrieval_selection` in `core/telemetry.py` accept a `commit` parameter (default `True`) so hook callers can defer commits for atomicity.
- **Extraction noise gate and confidence threshold** (#71) — `maybe_extract_decisions` now checks session quality before launching the extraction worker: sessions must have at least 1 checkpoint OR a configurable minimum number of turns with `files_touched` (`decisions.noise_gate_min_turns_with_files`, default 3). Additionally, `run_extraction` filters candidates below `decisions.candidate_min_confidence` (raised from 0.0 to 0.35) before persistence, preventing low-quality session-source candidates with no rationale or alternatives from entering the candidate pipeline.
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

- ~~**`include_contradicted` default**~~ — completed in [Unreleased]: default flipped to `False`.

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
