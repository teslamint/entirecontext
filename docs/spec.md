# EntireContext Specification

> Git-anchored decision memory for coding agents.

**Package version**: 0.9.3
**Reference status**: Current implementation reference, refreshed 2026-06-20
**Primary source of truth**: `src/entirecontext/`, `pyproject.toml`, and contract tests

---

## 1. Scope and Source of Truth

This document describes the behavior implemented in the current codebase at a reference level. For user onboarding and product framing, start with `README.md`; for exact runtime behavior, use the source modules named below and the corresponding tests.

- Runtime behavior: `src/entirecontext/`
- CLI surface: `src/entirecontext/cli/__init__.py` and `src/entirecontext/cli/*_cmds.py`
- MCP surface: `src/entirecontext/mcp/server.py` and `src/entirecontext/mcp/tools/*.py`
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
  └─ MCP Server (stdio, FastMCP)

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

- Capture: hooks write sessions/turns into per-repo SQLite.
- Search: runs against per-repo DB or cross-repo index + per-repo DB fanout.
- Sync export (`ec sync`): DB data exported to shadow branch artifacts.
- Sync import (`ec pull`): shadow branch artifacts imported back into DB.

---

## 3. Data Model

Schema version: **14**.
Minimum SQLite version: **3.38.0+**.

Reference:
- `src/entirecontext/db/schema.py`
- `src/entirecontext/db/migration.py`

### 3.1 Core tables `[Implemented]`

- `projects`, `agents`, `sessions`, `turns`, `turn_content`
- `checkpoints`, `events`, `event_sessions`, `event_checkpoints`
- `attributions`, `embeddings`, `ast_symbols`
- `assessments`, `assessment_relationships`
- `decisions`, `decision_commits`, `decision_checkpoints`, `decision_files`, `decision_assessments`, `decision_outcomes`
- `retrieval_events`, `retrieval_selections`, `context_applications`
- `operation_events`, `decision_candidates`
- `sync_metadata`

### 3.2 Search indexes `[Implemented]`

- FTS5 virtual tables: `fts_turns`, `fts_events`, `fts_sessions`, `fts_ast_symbols`, `fts_decisions`, `fts_decision_candidates`
- Trigger-based synchronization for insert/update/delete where defined in `schema.py`

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

Transport: stdio. Source of truth is `src/entirecontext/mcp/server.py` plus the `register_tools()` functions under `src/entirecontext/mcp/tools/`. `tests/test_contract_sync.py` asserts that this registered set matches the README `### Available Tools` table.

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

- Tools accept a `repos` parameter (`null` current repo, `["*"]` all repos, `["name"]` selected repos) where applicable; MCP runtime normalizes scalar/list/wildcard shapes at the boundary.

## 4.3 Hook contract `[Implemented]`

Hook dispatcher handles:

- `SessionStart`
- `UserPromptSubmit`
- `Stop`
- `PostToolUse`
- `SessionEnd`
- `PostCommit`

Runtime entrypoint:

- `ec hook handle [--type HOOK_TYPE]` reads JSON stdin

Install location and format:

- Claude Code hooks are installed by `ec enable` into `.claude/settings.local.json` using Claude hook object format with `matcher` + nested `hooks`.
- User-level MCP config is installed by `ec enable` into `~/.claude/settings.json` under `mcpServers.entirecontext`.

Exit codes:

- `0` success
- `2` reserved for block semantics (framework-level), not actively used by current handlers

## 4.4 Git hooks `[Implemented]`

Installed by `ec enable` unless `--no-git-hooks` is passed:

- `.git/hooks/post-commit` -> invokes `ec hook handle --type PostCommit`
- `.git/hooks/pre-push` -> invokes `ec sync --if-enabled`

---

## 5. Search

### 5.1 Modes `[Implemented]`

- Regex (default)
- FTS5 (`--fts`)
- Semantic (`--semantic`, `sentence-transformers` extra required)
- Hybrid (`--hybrid`, FTS5 + recency RRF reranking)

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

1. Ensure shadow branch exists (create orphan branch if absent)
2. Create temporary git worktree on local shadow branch
3. Export sessions/checkpoints since `sync_metadata.last_export_at`
4. Update `manifest.json`
5. Commit changes when present
6. Push when enabled by runtime config path
7. If push is rejected as non-fast-forward:
   - fetch `origin/<shadow-branch>`
   - create detached worktrees for local `HEAD` snapshot and remote tracking snapshot
   - merge artifacts at app level only
   - create one merge retry commit and retry push once
8. Update `sync_metadata.last_export_at` and duration fields only after successful sync completion

### 6.2 `ec pull` current workflow `[Implemented]`

1. Fetch shadow branch from `origin`
2. Resolve the latest remote tracking snapshot from `origin/<shadow-branch>`
3. Create a detached temporary git worktree on that remote tracking ref
4. Import missing sessions/checkpoints (idempotent-by-ID)
5. Update `sync_metadata.last_import_at`

### 6.3 Merge strategy status `[Implemented]`

- Automatic retry is fixed at one attempt and only triggers for non-fast-forward push rejection
- There is no git 3-way merge and no interactive conflict UI
- Merge policy is artifact-level only:
  - `manifest.json`: key union, session entry with higher `total_turns` wins, ties preserve non-null fields
  - `sessions/<id>/meta.json`: higher `total_turns` wins, ties preserve non-null fields, `started_at` uses earlier value, `ended_at` uses later value
  - `sessions/<id>/transcript.jsonl`: union by turn `id`
  - `checkpoints/*.json`: filename union
- Malformed merge artifacts, missing remote snapshot, or failed retry push are explicit sync errors

---

## 7. Futures Assessment

## 7.1 Data and CLI `[Implemented]`

- `assessments` table stores verdict/feedback metadata.
- `assessment_relationships` stores typed relationships between assessments.
- CLI commands: `assess`, `list`, `feedback`, `lessons`, `enrich-backlog`, `trend`, `relate`, `relationships`, `unrelate`, `tidy-pr`, `report`, `worker-status`, `worker-stop`, `worker-launch`.

## 7.2 MCP exposure `[Implemented]`

- `ec_assess`
- `ec_assess_create`
- `ec_feedback`
- `ec_lessons`
- `ec_assess_trends`

## 7.3 Auto-distill and feedback behavior `[Implemented]`

- `futures feedback` triggers auto-distill checks.
- Session end lifecycle can trigger auto-distill checks.
- Assessment enrichment/backlog processing is controlled by `[futures]` config keys such as `auto_distill`, `assess_enrich`, and `assess_backfill_window_days`.

---

## 7b. Content Filtering and Purge `[Implemented]`

## 7b. Content Filtering and Purge `[Implemented]`

### 7b.1 3-Layer filtering architecture

Source:
- `src/entirecontext/core/content_filter.py`
- `src/entirecontext/core/purge.py`
- `src/entirecontext/cli/purge_cmds.py`

**Layer 1: Capture-time exclusion** (`capture.exclusions`)
- `content_patterns`: regex list — skip entire turn if user message matches
- `file_patterns`: glob list — exclude file paths from `files_touched` tracking
- `tool_names`: exact match list — skip tool usage recording
- `redact_patterns`: regex list — replace matches with `[FILTERED]` before DB storage
- `enabled` flag gates all exclusion behavior

**Layer 2: Query-time redaction** (`filtering.query_redaction`)
- Applied to `regex_search`, `fts_search` results and MCP tool responses (`ec_search`, `ec_session_context`, `ec_turn_content`)
- `patterns`: regex list — redact matches in returned text fields
- `replacement`: configurable replacement string (default `[FILTERED]`)
- `enabled` flag gates redaction

**Layer 3: Post-hoc purge** (`ec purge`)
- `ec purge session SESSION_ID` — delete session + cascading turns/turn_content/checkpoints
- `ec purge turn TURN_ID...` — delete specific turns + content files
- `ec purge match PATTERN` — regex match against `user_message`/`assistant_summary`, delete matched turns
- All commands default to dry-run; `--execute` performs actual deletion
- Active sessions (ended_at IS NULL) cannot be purged (raises `ActiveSessionError`)
- JSONL content files deleted on disk; empty directories cleaned up
- FTS5 cleanup handled automatically via existing delete triggers

### 7b.2 Selective capture toggle

- Global: `capture.auto_capture = false` skips all turn creation
- Per-session: session `metadata.capture_disabled = true` skips turns for that session only

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

- `[Implemented]` line attribution CLI/API and agent hierarchy fields
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
- `[Implemented]` Code AST search (`ec ast-search`)
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

Previously tracked sync-policy gaps in this section have been closed. The notes below record the current implementation-alignment state.

Sync policy notes:

- `pre-push` is currently installed as `ec sync --if-enabled`, so push-triggered sync is gated by `sync.auto_sync_on_push`.
- `ec sync --no-filter` currently propagates to runtime sync config and is covered by CLI tests.
- Sync merge/retry and remote-tracking pull behavior are implemented; keep docs/tests aligned with the artifact-level policy above.

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

- `tests/test_contract_sync.py` source-extracts `mcp/server.py` registration modules and confirms 29 `ec_*` tools match `server.__all__` and README.
- Query-time redaction applies to search/session/turn MCP responses where implemented by tool modules.

## Config checks

- Source-level confirmation against `DEFAULT_CONFIG` in `core/config.py`.
- `capture.exclusions`, `[decisions]`, `[decisions.injection]`, `[futures]`, `[index]`, and `filtering.query_redaction` sections are present.

## Hook checks

- Source-level confirmation of handled hook types, including `PostCommit` dispatch.
- Decision fallback filenames are guarded by `tests/test_contract_sync.py`: `decisions-context.md` and `decisions-context-tooluse`.
- Content filtering integrated in `on_user_prompt`, `on_stop`, and `on_tool_use` paths.

## Sync policy checks

- `ec sync --no-filter` propagates runtime filtering config and is covered by CLI tests.
- Shadow-branch export/import and artifact-level merge behavior remain covered by sync tests.

---

## 12. Migration Notes from Previous Draft

- The previous draft emphasized design intent; this document now prioritizes implemented behavior.
- Where intent and implementation differ, this spec records both explicitly via status tags and backlog items.
