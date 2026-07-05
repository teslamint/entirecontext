# EntireContext

Time-travel searchable agent memory anchored to git state. Python 3.12+, uv, SQLite (WAL mode), Typer CLI (`ec`).

After `uv sync` that touches `mcp/` or `core/decisions.py`, restart Claude Code — the stdio MCP server does not auto-reload.

## Test

Tests use real git repos via fixtures (`git_repo`, `ec_repo`, `ec_db`, `isolated_global_db`). External deps are isolated with `monkeypatch`. See `tests/conftest.py`.

When modifying a source module, always run the existing tests for that module before committing — not just newly written tests. Test verification scope must match the change scope.

## Architecture

```
CLI (Typer)  →  core/  →  db/  →  hooks/  →  sync/
cli/             business    SQLite     Claude Code   shadow branch
  project_cmds   logic       schema     integration   export/import
  session_cmds   config      migration  turn capture  merge
  search_cmds    security    connection session lifecycle
  hook_cmds      cross_repo
  checkpoint_cmds content_filter
  sync_cmds      purge
  rewind_cmds    export
  repo_cmds      report
  purge_cmds     tidy_pr
  graph_cmds     dashboard
  ast_cmds       ast_index
  dashboard_cmds knowledge_graph
  futures_cmds   agent_graph
  blame_cmds     activation
  index_cmds     consolidation
  event_cmds     hybrid_search
  import_cmds    async_worker
  compact_cmds   compact
  mcp_cmds
```

`mcp/server.py` — MCP server interface (optional dependency).

## Data Model

**Per-repo DB**: `.entirecontext/db/local.db`
**Global DB**: `~/.entirecontext/db/ec.db`
**Schema version**: 15

Key tables: `projects`, `sessions`, `turns`, `turn_content`, `checkpoints`, `agents`, `events`, `assessments`, `assessment_relationships`, `attributions`, `embeddings`, `ast_symbols`, `sync_metadata`, `decisions`, `decision_candidates`, `decision_commits`, `decision_checkpoints`, `decision_files`, `decision_assessments`, `decision_outcomes`, `ranking_snapshots`

FTS5 virtual tables: `fts_turns`, `fts_events`, `fts_sessions`, `fts_ast_symbols`, `fts_decisions`, `fts_decision_candidates` (auto-synced via triggers)

Hybrid storage: SQLite for metadata/search, JSONL content files referenced by `turn_content.content_path`.

## Hook System

Claude Code hooks integration via stdin JSON protocol. Entry: `hooks/handler.py` → dispatches to handlers.

5 hook types: `SessionStart`, `UserPromptSubmit`, `Stop`, `PostToolUse`, `SessionEnd`

Return codes: 0=success, 2=block.

## Config

TOML deep merge: defaults ← `~/.entirecontext/config.toml` (global) ← `.entirecontext/config.toml` (per-repo)

Sections: `capture`, `capture.exclusions`, `search`, `sync`, `display`, `security`, `filtering.query_redaction`, `index`, `futures`, `decisions`, `decisions.ranking`, `decisions.quality`, `decisions.extraction`, `decisions.injection`

## Code Review Principles

Principles for automated code review (CI and agent review alike). These guide the reviewer, not the code author.

### Grounding
- Every finding must cite specific code location (file:line)
- Do not present inferences as facts; label hypotheses clearly
- Ground claims in repository context or tool outputs, not assumptions

### Confidence Threshold
- Only submit a finding if you can point to a specific code path that causes the issue
- Do not submit findings based on pattern-matching alone without tracing the actual call or data flow
- If confidence is low, omit the finding rather than labeling it a "suggestion"

### Severity
- Categorize findings: Critical (must fix) / Important (should fix) / Suggestion
- Critical: correctness bugs, data loss, security vulnerabilities
- Important: missing error handling, contract mismatches between docs and code, edge cases
- Suggestion: readability, naming, minor optimization

### Depth
- After first plausible issue, check second-order failures: empty-state handling, retries, stale state, rollback paths
- Verify contract consistency: if CLAUDE.md, docstrings, or specs state X, code must match

### False Positive Avoidance
- Do not flag pre-existing issues unrelated to the change
- Do not flag issues ruff, pytest, or other configured CI steps already enforce
- Do not flag intentional behavior changes that align with the PR's stated purpose
- Do not flag style preferences not codified in this file or ruff config

### Scope
- Review only the changed code and its immediate blast radius
- Do not suggest unrelated refactors or cleanup
