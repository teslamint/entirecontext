# EntireContext Specification

> Git-anchored decision memory for coding agents.

**Package version**: 0.9.3
**Reference status**: Current implementation reference, refreshed 2026-06-20
**Primary source of truth**: `src/entirecontext/`, `pyproject.toml`, and contract tests

---

## 1. Scope and Source of Truth

This document describes behavior in the current codebase at a reference level.
For user onboarding and product framing, start with `README.md`.
For exact runtime behavior, use the source modules named below and the corresponding tests.

- Runtime behavior: `src/entirecontext/`
- Command-line interface (CLI) surface: `src/entirecontext/cli/__init__.py` and `src/entirecontext/cli/*_cmds.py`
- Model Context Protocol (MCP) surface: `src/entirecontext/mcp/server.py` and `src/entirecontext/mcp/tools/*.py`
- Data schema: `src/entirecontext/db/schema.py`
- Hook behavior: `src/entirecontext/hooks/handler.py`, `session_lifecycle.py`, `turn_capture.py`, `decision_hooks.py`
- Public user guide: `README.md`
- Contract drift guard: `tests/test_contract_sync.py`

### Status tags used in this spec

- `[Implemented]`: behavior is present in code now.
- `[Partial]`: partially implemented or implemented with known caveats.
- `[Historical]`: retained as provenance, not a current behavior claim.
- `[Planned]`: intentionally not implemented yet.

---

## 2. Architecture

### 2.1 System Layers `[Implemented]`

```
User / Agent
  ├─ CLI (ec, Typer)
  ├─ Claude Code Hooks
  └─ MCP Server (stdio, MCPServer)

Core Engine
  ├─ Capture (sessions/turns)
  ├─ Checkpoint
  ├─ Search (regex/FTS/semantic/hybrid)
  ├─ Decision memory + context telemetry
  ├─ Attribution
  ├─ Futures assessment + lessons
  ├─ Dashboard/graph/AST/compaction
  └─ Cross-repo orchestration

Storage
  ├─ Per-repo SQLite (.entirecontext/db/local.db)
  ├─ Global SQLite (~/.entirecontext/db/ec.db)
  ├─ External turn content files (.entirecontext/content/...)
  └─ Git shadow branch (entirecontext/checkpoints/v1)
```

### 2.2 Data flow `[Implemented]`

- Capture: hooks write sessions and turns to a per-repo SQLite database.
- Search: the system queries a per-repo database (DB) or uses a cross-repo index plus per-repo DB fanout.
- Sync export (`ec sync`): exports DB data to shadow branch artifacts.
- Sync import (`ec pull`): imports shadow branch artifacts into the DB.

---

## 3. Data Model

Schema version: **20**.
Minimum SQLite version: **3.38.0+**.

Reference:
- `src/entirecontext/db/schema.py`
- `src/entirecontext/db/migration.py`

### 3.1 Core tables `[Implemented]`

- `projects`, `agents`, `sessions`, `turns`, `turn_content`
- `checkpoints`, `events`, `event_sessions`, `event_checkpoints`
- `attributions`, `embeddings`, `ast_symbols`
- `assessments`, `assessment_relationships`
- `decisions`, `decision_commits`, `decision_checkpoints`, `decision_files`, `decision_file_lineage`, `decision_file_lineage_suppressions`, `decision_file_lineage_state`, `decision_assessments`, `decision_outcomes`
- `retrieval_events`, `retrieval_selections`, `context_applications`
- `operation_events`, `decision_candidates`
- `sync_metadata`

### 3.2 Search indexes `[Implemented]`

- Full-text search (FTS5) virtual tables: `fts_turns`, `fts_events`, `fts_sessions`, `fts_ast_symbols`, `fts_decisions`, `fts_decision_candidates`
- Triggers synchronize inserts, updates, and deletes where `schema.py` defines them.

### 3.3 Global DB `[Implemented]`

- `repo_index` in `~/.entirecontext/db/ec.db` for cross-repo lookup

---

## 4. Public Interfaces

## 4.1 CLI interface `[Implemented]`

Validated command set (from `ec --help`, 2026-06-20):

- Top-level commands: `init`, `enable`, `disable`, `status`, `config`, `doctor`, `search`, `sync`, `pull`, `rewind`, `blame`, `index`, `import`, `graph`, `ast-search`, `dashboard`, `compact`
- Groups: `session`, `hook`, `checkpoint`, `repo`, `event`, `mcp`, `futures`, `purge`, `context`, `decision`

### Key command groups

- `ec session`: `list`, `show`, `current`, `export`, `consolidate`, `graph`, `activate`, `backfill-ended-at`, `backfill-applied`
- `ec checkpoint`: `create`, `list`, `show`, `diff`, `assess-accuracy`
- `ec decision`: `create`, `list`, `show`, `rejected-alternatives`, `link`, `stale`, `outcome`, `update`, `supersede`, `unlink`, `search`, `chain`, `stale-all`, `extract-candidates`, `extract-from-session`, `surface-prompt`, `candidates`, `alternatives`
- `ec context`: `select`, `apply`
- `ec futures`: `assess`, `list`, `feedback`, `lessons`, `enrich-backlog`, `relate`, `relationships`, `unrelate`, `trend`, `report`, `tidy-pr`, `worker-status`, `worker-stop`, `worker-launch`
- `ec purge`: `session`, `turn`, `match`
- `ec mcp`: `serve`
- `ec sync`: supports `--no-filter` and `--if-enabled`

## 4.2 MCP interface `[Implemented]`

Transport: stdio. The source of truth is `src/entirecontext/mcp/server.py` together with the `register_tools()` functions under `src/entirecontext/mcp/tools/`.
Those functions define the registered tools.
The `tests/test_contract_sync.py` test checks that the registered set matches the README `### Available Tools` table.

Implemented tools (29):

1. `ec_activate`
2. `ec_assess`
3. `ec_assess_create`
4. `ec_assess_trends`
5. `ec_ast_search`
6. `ec_attribution`
7. `ec_checkpoint_list`
8. `ec_context_apply`
9. `ec_dashboard`
10. `ec_decision_candidate_confirm`
11. `ec_decision_candidate_get`
12. `ec_decision_candidate_list`
13. `ec_decision_candidate_reject`
14. `ec_decision_context`
15. `ec_decision_create`
16. `ec_decision_get`
17. `ec_decision_list`
18. `ec_decision_outcome`
19. `ec_decision_related`
20. `ec_decision_search`
21. `ec_decision_stale`
22. `ec_feedback`
23. `ec_graph`
24. `ec_lessons`
25. `ec_related`
26. `ec_rewind`
27. `ec_search`
28. `ec_session_context`
29. `ec_turn_content`

Cross-repo support:

- Where applicable, tools accept a `repos` parameter: `null` means the current repo, `["*"]` means all repos, and `["name"]` means selected repos. The MCP runtime normalizes scalar, list, and wildcard shapes at the boundary.

## 4.3 Hook contract `[Implemented]`

Hook dispatcher handles:

- `SessionStart`
- `UserPromptSubmit`
- `Stop`
- `PostToolUse`
- `SessionEnd`
- `PostCommit`

Runtime entrypoint:

- `ec hook handle [--type HOOK_TYPE]` reads JavaScript Object Notation (JSON) from stdin.

Install location and format:

- Claude Code hooks use the Claude hook object format with `matcher` and nested `hooks`. The `ec init` command installs them in `.claude/settings.local.json`. The `ec enable` command performs the same installation. Use it to reinstall the hooks.
- The `ec init` command installs the user-level MCP config in `~/.claude/settings.json` under `mcpServers.entirecontext`. The `ec enable` command installs it on the same terms.

`ec disable` removes the selected agent integration and the agent-neutral repository Git hooks. By default, it preserves the shared user-level MCP entry. `--remove-mcp` explicitly removes only a standard `entirecontext` stdio entry. It preserves sibling servers, unrelated settings, and nonstandard entries. The flag also authorizes removal of an identical standard entry that a user configured manually.

Package health and MCP activation are separate checks. A successful `ec --help` or package reinstall does not enable a Codex MCP registration with `enabled = false` in `~/.codex/config.toml`. Enable that registration in Codex configuration.

Exit codes:

- `0` success
- `2` reserved for block semantics (framework-level), not actively used by current handlers

## 4.4 Git hooks `[Implemented]`

`ec init` or `ec enable` installs these hooks for every target agent (`claude`, `codex`, or `both`), unless you pass `--no-git-hooks`. These Git hooks are agent-neutral. `--agent codex` installs them without Claude Code hooks. `ec init --no-hooks` skips these hooks and every other integration:

- `.git/hooks/post-commit` -> invokes `ec hook handle --type PostCommit`
- `.git/hooks/pre-push` -> invokes `ec sync --if-enabled`

`ec disable` removes these EntireContext-owned repository hooks for every target agent. Ownership guards preserve foreign hooks and configured shared hook paths.

## 4.5 Installed-tool build provenance `[Implemented]`

Wheel and source-distribution builds contain a generated `entirecontext._build_provenance` module.
This module stores the source checkout's full Git SHA and tracked-file dirty state.
A wheel rebuilt from an unpacked source distribution preserves the source distribution's stamp when `.git` is unavailable.

When `ec doctor` runs from an installed distribution inside the EntireContext source checkout, it compares the stamped SHA with the checkout's current `HEAD`.
It warns if provenance is unavailable, if the build came from a dirty tracked tree, or if the SHA differs.
Missing or mismatched installed stamps direct the operator to run `uv tool install --force .`.
Dirty stamps first require the operator to commit or restore tracked changes.
If checkout `HEAD` is unresolved, the operator must create or check out a commit before rebuilding.
Direct checkout/editable execution and unrelated consumer repositories do not receive this warning.

---

## 5. Search

### 5.1 Modes `[Implemented]`

- Regex (default)
- FTS5 (`--fts`)
- Semantic (`--semantic`, `sentence-transformers` extra required)
- Hybrid (`--hybrid`, FTS5 + recency-based reciprocal rank fusion (RRF) reranking)

### 5.2 Filters `[Implemented]`

- `--file`, `--commit`, `--agent`, `--since`, `-t/--target`, `-n/--limit`
- cross-repo: `-g/--global`, `-r/--repo`

### 5.3 Targets `[Implemented]`

- `turn`, `session`, `event`, `content`

---

## 6. Sync and Shadow Branch

Shadow branch:

- `entirecontext/checkpoints/v1`

Artifacts:

- `manifest.json`
- `sessions/<session-id>/meta.json`
- `sessions/<session-id>/transcript.jsonl`
- `checkpoints/<checkpoint-id>.json`

### 6.1 `ec sync` current workflow `[Implemented]`

1. Ensure that the shadow branch exists. Create an orphan branch if it does not.
2. Create a temporary Git worktree on the local shadow branch
3. Export all sessions, their turns, and checkpoints, regardless of timestamps
4. Update `manifest.json`.
5. Commit the changes when present.
6. Push if the runtime config enables sync
7. If the push is rejected as non-fast-forward:
   - fetch `origin/<shadow-branch>`
   - create detached worktrees for the local `HEAD` snapshot and the remote tracking snapshot
   - merge artifacts at the application level only
   - create one merge retry commit. Retry the push once.
8. Update `sync_metadata.last_export_at` and the duration fields only after the sync completes successfully.

The export timestamp controls telemetry and automatic-sync cooldown only. It does not filter records.
Writes after export selection appear on the next sync. See [ADR 0020](adr/0020-full-sync-export.md).

### 6.2 `ec pull` current workflow `[Implemented]`

1. Fetch the shadow branch from `origin`
2. Resolve the latest remote tracking snapshot from `origin/<shadow-branch>`
3. Create a detached temporary Git worktree on that remote tracking ref
4. Import the missing sessions and checkpoints (idempotent-by-ID)
5. Update `sync_metadata.last_import_at`

### 6.3 Merge strategy status `[Implemented]`

- The workflow retries automatically once. It does so only after a non-fast-forward push rejection.
- The workflow does not use a Git 3-way merge. It has no interactive conflict UI.
- The merge policy applies only at the artifact level:
  - `manifest.json`: key union, session entry with higher `total_turns` wins, ties preserve non-null fields
  - `sessions/<id>/meta.json`: higher `total_turns` wins, ties preserve non-null fields, `started_at` uses earlier value, `ended_at` uses later value
  - `sessions/<id>/transcript.jsonl`: union by turn `id`
  - `checkpoints/*.json`: filename union
- Malformed merge artifacts, a missing remote snapshot, or a failed retry push each produce an explicit sync error.

---

## 7. Futures Assessment

## 7.1 Data and CLI `[Implemented]`

- The `assessments` table stores verdict/feedback metadata.
- The `assessment_relationships` table stores typed relationships between assessments.
- CLI commands: `assess`, `list`, `feedback`, `lessons`, `enrich-backlog`, `trend`, `relate`, `relationships`, `unrelate`, `tidy-pr`, `report`, `worker-status`, `worker-stop`, `worker-launch`.

`src/entirecontext/core/llm.py` defines the large language model (LLM) backends for `ec futures assess -b BACKEND`. `src/entirecontext/cli/futures_cmds.py` calls them.
The `--model` option defaults to `gpt-4o-mini`.
The command passes this value to every backend.
A constructor fallback applies only when a caller passes no model.

| Backend | Auth | Model when `--model` is omitted | Constructor fallback |
|---|---|---|---|
| `openai` | `OPENAI_API_KEY` | `gpt-4o-mini` | `gpt-4o-mini` |
| `github` | `GITHUB_TOKEN` | `gpt-4o-mini` | `openai/gpt-4o-mini` |
| `ollama` | None (local) | `gpt-4o-mini` | `llama3` |
| `codex` | CLI subprocess | Ignored; the CLI uses its own model | — |
| `claude` | CLI subprocess | Ignored; the CLI uses its own model | — |

## 7.2 MCP exposure `[Implemented]`

- `ec_assess`
- `ec_assess_create`
- `ec_feedback`
- `ec_lessons`
- `ec_assess_trends`

## 7.3 Auto-distill and feedback behavior `[Implemented]`

- `futures feedback` triggers auto-distill checks.
- The session end lifecycle can trigger auto-distill checks.
- Config keys in the `[futures]` section, such as `auto_distill`, `assess_enrich`, `assess_backfill_window_days`, and `lessons_min_per_verdict`, control assessment enrichment and backlog processing.

---

## 7b. Content Filtering and Purge `[Implemented]`

## 7b. Content Filtering and Purge `[Implemented]`

### 7b.1 3-Layer filtering architecture

Source:
- `src/entirecontext/core/content_filter.py`
- `src/entirecontext/core/purge.py`
- `src/entirecontext/cli/purge_cmds.py`

**Layer 1: Capture-time exclusion** (`capture.exclusions`)
- `content_patterns`: regex list — skip an entire turn if the user message matches
- `file_patterns`: glob list — exclude file paths from `files_touched` tracking
- `tool_names`: exact match list — skip tool usage recording
- `redact_patterns`: regex list — replace matches with `[FILTERED]` before DB storage
- The `enabled` flag gates all exclusion behavior

**Layer 2: Query-time redaction** (`filtering.query_redaction`)
- Query-time redaction applies to `regex_search` and `fts_search` results and to MCP tool responses (`ec_search`, `ec_session_context`, `ec_turn_content`)
- `patterns`: regex list — redact matches in returned text fields
- `replacement`: configurable replacement string (default `[FILTERED]`)
- The `enabled` flag gates redaction

**Layer 3: Post-hoc purge** (`ec purge`)
- `ec purge session SESSION_ID` — delete the session and its cascading turns, `turn_content`, and checkpoints
- `ec purge turn TURN_ID...` — delete the specified turns and their content files
- `ec purge match PATTERN` matches `PATTERN` against `user_message`/`assistant_summary` with a regex. The command deletes the matched turns.
- All commands default to dry-run; `--execute` performs actual deletion.
- The purge command cannot purge active sessions (`ended_at IS NULL`). It raises `ActiveSessionError` for those sessions.
- The command deletes JSON Lines (JSONL) content files on disk. It also removes empty directories.
- Existing delete triggers handle FTS5 cleanup automatically.

### 7b.2 Selective capture toggle

- Global: `capture.auto_capture = false` skips all turn creation
- Per-session: A session with `metadata.capture_disabled = true` skips turns for that session only

---

## 8. Configuration (defaults)

Source:

- `src/entirecontext/core/config.py`

This is an operator-facing excerpt, not a replacement for `DEFAULT_CONFIG`.

```toml
[capture]
auto_capture = true
checkpoint_on_commit = true
checkpoint_on_session_end = false
auto_cleanup_no_changes = false
content_retention_days = 30
intent_summary = false
emit_aar = true
codex_session_idle_minutes = 60
surface_lessons_on_start = true

[capture.exclusions]
enabled = false
content_patterns = []
file_patterns = []
tool_names = []
redact_patterns = []

[search]
default_mode = "regex"
semantic_model = "all-MiniLM-L6-v2"

[sync]
auto_sync = false
auto_sync_on_push = false
auto_pull = false
cooldown_seconds = 300
pull_staleness_seconds = 600
push_on_sync = true
quiet = true

[display]
max_results = 20
color = true

[security]
filter_secrets = true
patterns = [
  "(?i)(api[_-]?key|secret|password|token)\\s*[=:]\\s*['\"]?[\\w-]+",
  "(?i)bearer\\s+[\\w.-]+",
  "ghp_[a-zA-Z0-9]{36}",
  "sk-[a-zA-Z0-9]{48}",
]

[index]
auto_embed = false
embed_model = "all-MiniLM-L6-v2"

[futures]
auto_distill = false
lessons_output = "LESSONS.md"
lessons_min_per_verdict = 5
default_backend = "claude"
default_model = ""
assess_enrich = true
assess_backfill_window_days = 7

[decisions]
auto_stale_check = false
auto_extract = false
show_related_on_start = false
surface_on_tool_use = false
infer_applied_on_session_end = true
infer_outcome_type = true
auto_promotion_contradicted_threshold = 2
auto_embed = true

[decisions.injection]
inject_on_user_prompt = true
top_k = 5
max_tokens = 800
min_confidence = 0.4
inject_timeout_ms = 250

[filtering.query_redaction]
enabled = false
patterns = []
replacement = "[FILTERED]"
```
Lesson selection reserves slots for each verdict within the total lesson cap.
A run of one verdict cannot evict every lesson from another verdict.
The reservation never exceeds half the cap.
The value `0` restores pure recency ordering.

---

## 9. Implementation Status by Phase

## Phase 1: Foundation

- `[Implemented]` Core CLI + DB + hooks + regex/FTS search

## Phase 2: Git integration

- `[Implemented]` Checkpoint, rewind, sync/pull, post-commit checkpoint path, and pre-push sync gate

## Phase 3: Semantic + MCP

- `[Implemented]` Semantic indexing/search when optional dependencies are installed
- `[Implemented]` MCP server with 29 registered `ec_*` tools guarded by `tests/test_contract_sync.py`

## Phase 4: Attribution + Multi-agent

- `[Implemented]` Line attribution CLI and application programming interface (API), plus agent hierarchy fields
- `[Implemented]` session graph and spreading activation retrieval

## Phase 5: Sharing + Cross-repo

- `[Implemented]` global repo index and cross-repo query paths
- `[Implemented]` artifact-level shadow-branch sync/pull with one non-fast-forward retry

## Phase 6: Futures and lessons

- `[Implemented]` futures CLI, assessment table, typed assessment relationships, feedback loop, lessons generation, enrichment worker, and LLM backend abstraction

## Phase 7: Content Filtering & Purge

- `[Implemented]` 3-layer content filtering: capture exclusion, query redaction, post-hoc purge
- `[Implemented]` `ec purge session/turn/match` CLI with dry-run safety
- `[Implemented]` per-session and global capture toggles

## Phase 8: Dashboard, Graph, AST & Advanced Features

- `[Implemented]` Team dashboard (`ec dashboard`)
- `[Implemented]` Knowledge graph (`ec graph`)
- `[Implemented]` Code search over abstract syntax trees (AST) (`ec ast-search`)
- `[Implemented]` Memory consolidation (`ec session consolidate`) and storage compaction (`ec compact`)
- `[Implemented]` Hybrid search (`--hybrid`)
- `[Implemented]` Session export (`ec session export`)

## Phase 9: Decision memory and proactive retrieval

- `[Implemented]` first-class decisions, rejected alternatives, staleness/supersession, outcome tracking, and auto-promotion to `contradicted`
- `[Implemented]` candidate decision extraction/review pipeline
- `[Implemented]` Proactive Decision Injection on `UserPromptSubmit`
- `[Implemented]` decision surfacing on `SessionStart` and optional `PostToolUse`
- `[Implemented]` context telemetry (`retrieval_events`, `retrieval_selections`, `context_applications`)

---

## 10. Follow-up Notes

The previously tracked sync-policy gaps in this section are now closed.
The notes below record the current alignment with the implementation.

Sync policy notes:

- The `ec init` and `ec enable` commands currently install the `pre-push` hook as `ec sync --if-enabled`. The `sync.auto_sync_on_push` setting gates push-triggered sync.
- CLI tests cover the runtime sync config propagation from `ec sync --no-filter`.
- The code implements sync merge/retry and remote-tracking pull behavior. Keep docs and tests aligned with the artifact-level policy above.

---

## 11. Validation Checklist (2026-06-20)

## CLI shape checks

- `ec --help` confirms top-level commands including `compact`, `dashboard`, `graph`, `ast-search`, and groups including `context` and `decision`.
- `ec checkpoint --help` confirms `create/list/show/diff/assess-accuracy`.
- `ec decision --help` confirms decision CRUD, staleness, outcome, supersession, candidate extraction/review, and alternatives commands.
- `ec context --help` confirms `select/apply`.
- `ec futures --help` confirms assessment, feedback, lessons, enrichment, relationship, reporting, tidy-pr, and worker commands.
- `ec session --help` confirms `list/show/current/export/consolidate/graph/activate/backfill-ended-at/backfill-applied`.
- `ec sync --help` confirms `--no-filter` and `--if-enabled` option exposure.

## MCP checks

- The `tests/test_contract_sync.py` test extracts registrations from the `mcp/server.py` modules. It checks that 29 `ec_*` tools match `server.__all__` and the README.
- Tool modules apply query-time redaction to search, session, and turn MCP responses where they implement that behavior.

## Config checks

- Source-level confirmation against `DEFAULT_CONFIG` in `core/config.py`.
- `capture.exclusions`, `[decisions]`, `[decisions.injection]`, `[futures]`, `[index]`, and `filtering.query_redaction` sections are present.

## Hook checks

- Source-level confirmation of handled hook types, including `PostCommit` dispatch.
- The `tests/test_contract_sync.py` test checks the decision fallback filenames `decisions-context.md` and `decisions-context-tooluse`.
- The `on_user_prompt`, `on_stop`, and `on_tool_use` paths apply content filtering.

## Sync policy checks

- The `ec sync --no-filter` option propagates runtime filtering config. CLI tests cover this behavior.
- Sync tests still cover shadow-branch export/import and artifact-level merge behavior.

---

## 12. Migration Notes from Previous Draft

- The previous draft emphasized design intent; this document now prioritizes implemented behavior.
- When intent and implementation differ, this spec records both with status tags and backlog items.
