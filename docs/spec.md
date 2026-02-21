# EntireContext Specification

> Time-travel searchable agent memory anchored to your codebase.

**Version**: 0.1.0
**Status**: Implementation-aligned specification (as of 2026-02-20)

---

## 1. Scope and Source of Truth

This document describes the behavior implemented in the current codebase.

- Primary source of truth (runtime behavior):
  - `src/entirecontext/`
- Supporting docs (user-facing):
  - `README.md`

### Status tags used in this spec

- `[Implemented]`: behavior is present in code now.
- `[Partial]`: partially implemented or implemented with known caveats.
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
  ├─ Search (regex/FTS/semantic)
  ├─ Attribution
  ├─ Futures assessment
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

Schema version: **3**.
Minimum SQLite version: **3.38.0+**.

Reference:
- `src/entirecontext/db/schema.py`
- `src/entirecontext/db/migration.py`

### 3.1 Core tables `[Implemented]`

- `projects`, `agents`, `sessions`, `turns`, `turn_content`
- `checkpoints`, `events`, `event_sessions`, `event_checkpoints`
- `attributions`, `embeddings`
- `assessments` (futures)
- `sync_metadata` (`last_sync_error`, `last_sync_duration_ms`, `sync_pid` included)

### 3.2 Search indexes `[Implemented]`

- FTS5 virtual tables: `fts_turns`, `fts_events`, `fts_sessions`
- Trigger-based synchronization for insert/update/delete

### 3.3 Global DB `[Implemented]`

- `repo_index` in `~/.entirecontext/db/ec.db` for cross-repo lookup

---

## 4. Public Interfaces

## 4.1 CLI interface `[Implemented]`

Validated command set (from `ec --help`):

- Top-level: `init`, `enable`, `disable`, `status`, `config`, `doctor`, `search`, `sync`, `pull`, `rewind`, `blame`, `index`, `import`
- Groups: `session`, `hook`, `checkpoint`, `repo`, `event`, `mcp`, `futures`

### Key command groups

- `ec checkpoint`: `create`, `list`, `show`, `diff`
- `ec futures`: `assess`, `list`, `feedback`, `lessons`
- `ec sync`: supports `--no-filter` (see Known Gaps for runtime caveat)

## 4.2 MCP interface `[Implemented]`

Transport: stdio.

Implemented tools (9):

1. `ec_search`
2. `ec_checkpoint_list`
3. `ec_session_context`
4. `ec_attribution`
5. `ec_rewind`
6. `ec_related`
7. `ec_turn_content`
8. `ec_assess`
9. `ec_lessons`

Cross-repo support:

- tools support `repos` parameter (`null` current repo, `["*"]` all repos, `["name"]` selected repos)

## 4.3 Hook contract `[Implemented]`

Hook dispatcher handles:

- `SessionStart`
- `UserPromptSubmit`
- `Stop`
- `PostToolUse`
- `SessionEnd`

Runtime entrypoint:

- `ec hook handle [--type HOOK_TYPE]` reads JSON stdin

Install location and format:

- Installed by `ec enable` into `.claude/settings.local.json`
- Uses Claude hook object format with `matcher` + nested `hooks`

Exit codes:

- `0` success
- `2` reserved for block semantics (framework-level), not actively used by current handlers

## 4.4 Git hooks `[Partial]`

Installed by `ec enable`:

- `.git/hooks/post-commit` -> invokes `ec hook handle --type PostCommit`
- `.git/hooks/pre-push` -> invokes `ec sync`

Current caveat:

- `PostCommit` is not dispatched in hook handler today (see Known Gaps).

---

## 5. Search

### 5.1 Modes `[Implemented]`

- Regex (default)
- FTS5 (`--fts`)
- Semantic (`--semantic`, `sentence-transformers` extra required)

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
2. Create temporary git worktree on shadow branch
3. Export sessions/checkpoints since `sync_metadata.last_export_at`
4. Update `manifest.json`
5. Commit changes when present
6. Push when enabled by runtime config path (see caveat below)
7. Update `sync_metadata.last_export_at` and duration fields

### 6.2 `ec pull` current workflow `[Implemented]`

1. Fetch shadow branch
2. Create temporary git worktree
3. Import missing sessions/checkpoints (idempotent-by-ID)
4. Update `sync_metadata.last_import_at`

### 6.3 Merge strategy status `[Partial]`

- App-level merge helpers exist (`sync/merge.py`) for manifest/transcript/checkpoint artifacts
- Current `perform_sync`/`perform_pull` path does not execute an explicit multi-remote merge/retry orchestration loop

---

## 7. Futures Assessment

## 7.1 Data and CLI `[Implemented]`

- `assessments` table stores verdict/feedback metadata
- CLI:
  - `ec futures assess`
  - `ec futures list`
  - `ec futures feedback`
  - `ec futures lessons`

## 7.2 MCP exposure `[Implemented]`

- `ec_assess` (read assessment)
- `ec_lessons` (read distilled lessons inputs)

## 7.3 Auto-distill behavior `[Implemented]`

- `futures feedback` triggers auto-distill check
- session end lifecycle also triggers auto-distill check
- gated by config: `futures.auto_distill`

---

## 8. Configuration (defaults)

Source:

- `src/entirecontext/core/config.py`

```toml
[capture]
auto_capture = true
checkpoint_on_commit = true
checkpoint_on_session_end = false

[search]
default_mode = "regex"
semantic_model = "all-MiniLM-L6-v2"

[sync]
auto_sync = false
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
  "(?i)(api[_-]?key|secret|password|token)\\s*[=:]\\s*[\\'\"]?[\\w-]+",
  "(?i)bearer\\s+[\\w.-]+",
  "ghp_[a-zA-Z0-9]{36}",
  "sk-[a-zA-Z0-9]{48}",
]

[futures]
auto_distill = false
lessons_output = "LESSONS.md"
```

---

## 9. Implementation Status by Phase

## Phase 1: Foundation

- `[Implemented]` Core CLI + DB + hooks + regex/FTS search

## Phase 2: Git integration

- `[Partial]` Checkpoint + sync/pull + rewind are present
- `[Partial]` post-commit automation path has handler gap (Known Gap #1)

## Phase 3: Semantic + MCP

- `[Implemented]` semantic indexing/search and MCP tools
- `[Implemented]` MCP toolset expanded beyond initial draft (9 tools)

## Phase 4: Attribution + Multi-agent

- `[Implemented]` line attribution CLI/API and agent hierarchy fields

## Phase 5: Sharing + Cross-repo

- `[Implemented]` global repo index and cross-repo query paths
- `[Partial]` advanced sync conflict policy described in old draft is not fully wired in runtime path

## Phase 6: Futures (added)

- `[Implemented]` futures CLI, table, feedback loop, lessons generation
- `[Implemented]` LLM backend abstraction and MCP read tools (`ec_assess`, `ec_lessons`)

---

## 10. Known Gaps and Follow-up Backlog

The items below are implementation gaps, not documentation errors.

## P0

1. PostCommit hook dispatch gap
- Current: git hook emits `PostCommit`, handler has no dispatcher entry
- Target: `PostCommit` creates checkpoint when policy allows
- Acceptance criteria:
  - `post-commit` hook invocation creates checkpoint for active session
  - no-op behavior remains safe without active session
- Verification:
  - integration test for hook dispatch + checkpoint row creation

## P1

2. pre-push optional policy mismatch
- Current: `pre-push` script always calls `ec sync`
- Target: behavior gated by explicit config policy (e.g., `sync.auto_sync_on_push` or replacement key)
- Acceptance criteria:
  - disabled config -> pre-push does not perform sync
  - enabled config -> pre-push performs sync
- Verification:
  - hook unit/integration tests with both config states

3. `ec sync --no-filter` runtime wiring
- Current: CLI exposes option, but sync path does not apply filter toggle to exporter flow
- Target: `--no-filter` must bypass secret filtering, default path must apply configured filtering
- Acceptance criteria:
  - same input transcript yields redacted output by default
  - same input transcript yields unredacted output with `--no-filter`
- Verification:
  - exporter/security integration tests

## P2

4. Sync merge/retry policy alignment
- Current: merge helpers exist but not orchestrated in sync engine retry loop
- Target: either implement app-level merge/retry loop or officially narrow policy in docs/README
- Acceptance criteria:
  - chosen policy is implemented and tested
  - docs and runtime are consistent
- Verification:
  - conflict scenario tests (simulated divergent shadow branch states)

---

## 11. Validation Checklist (2026-02-20)

## CLI shape checks

- `ec --help` confirms command groups including `futures`, `mcp`, `import`, `checkpoint`
- `ec checkpoint --help` confirms `create/list/show/diff`
- `ec futures --help` confirms `assess/list/feedback/lessons`
- `ec sync --help` confirms `--no-filter` option exposure

## MCP checks

- Source-level confirmation of 9 tools in `mcp/server.py`

## Config checks

- Source-level confirmation against `DEFAULT_CONFIG` in `core/config.py`

## Hook checks

- Source-level confirmation of handled hook types and identified `PostCommit` gap

---

## 12. Migration Notes from Previous Draft

- The previous draft emphasized design intent; this document now prioritizes implemented behavior.
- Where intent and implementation differ, this spec records both explicitly via status tags and backlog items.
