# Test Coverage Analysis

**Date:** 2026-02-24
**Overall coverage:** 76.4% (4,390 / 5,747 statements)
**Tests:** 944 passed, 32 skipped

## Summary

The codebase has a solid testing foundation with 56 test files covering most of the core
functionality. However, several modules have significant coverage gaps, and some entire
subsystems are barely tested. This document identifies the top priority areas for
improvement, organized by impact and effort.

---

## Coverage by Layer

| Layer | Avg Coverage | Notes |
|-------|-------------|-------|
| core/ | ~85% | Well-tested overall, a few key gaps |
| cli/ | ~75% | Most commands tested, `futures_cmds` and `import_cmds` are major gaps |
| hooks/ | ~75% | Turn capture well-tested, handler dispatch and codex_ingest weak |
| db/ | ~80% | Connection/schema/migration lightly tested (but small modules) |
| sync/ | ~45% | Weakest layer — exporter, shadow_branch, auto_sync all low |
| mcp/ | ~4% | Essentially untested |

---

## Critical Gaps (Coverage < 35%)

### 1. `mcp/server.py` — 4% (334 lines missed of 348)

**What's untested:** All 9 MCP tool handlers (`search_turns`, `list_sessions`,
`get_session_detail`, `create_checkpoint`, etc.), cross-repo search, query redaction in
MCP context, error handling for JSON parsing and LLM responses.

**Why it matters:** MCP is the primary integration point for external tools consuming
EntireContext data. Regressions here silently break the API surface.

**Recommended tests:**
- Mock the MCP framework and test each tool handler with valid/invalid inputs
- Test cross-repo variants (passing `repos` parameter)
- Test error paths: missing sessions, malformed JSON, stale data
- Test query redaction is applied to MCP search results
- Test ImportError handling when optional dependencies are missing

**Effort:** High — requires MCP framework mocking infrastructure.

---

### 2. `sync/exporter.py` — 15% (53 lines missed of 62)

**What's untested:** `export_sessions()` file I/O, `export_checkpoints()` serialization,
`update_manifest()` merge logic.

**Why it matters:** Data export is a critical path for sync. Bugs here cause silent data
loss or corruption during cross-repo sync.

**Recommended tests:**
- Test `export_sessions()` creates correct directory structure and JSONL files
- Test `export_checkpoints()` serializes all checkpoint fields
- Test `update_manifest()` merges with existing manifest data
- Test edge cases: empty sessions list, manifest file doesn't exist yet, malformed existing manifest

**Effort:** Low — straightforward file I/O testing with `tmp_path`.

---

### 3. `sync/shadow_branch.py` — 28% (21 lines missed of 29)

**What's untested:** `init_shadow_branch()` orphan branch creation, `_run_git()` error
handling, branch-already-exists early return path.

**Why it matters:** Shadow branch is the foundation for sync. A broken init means sync
can never work for a repo.

**Recommended tests:**
- Test `init_shadow_branch()` creates orphan branch with correct structure
- Test early return when branch already exists
- Test `_run_git()` propagates subprocess errors
- Test branch switching restores original branch after init

**Effort:** Low-Medium — uses `git_repo` fixture, similar to existing sync tests.

---

### 4. `core/indexing.py` — 33% (39 lines missed of 58)

**What's untested:** `generate_embeddings()` full flow — model loading, vector encoding,
force mode (delete + regenerate), session embedding generation.

**Why it matters:** Embeddings power semantic search. Broken indexing silently degrades
search quality.

**Recommended tests:**
- Mock `SentenceTransformer` and test the full generation pipeline
- Test force=True deletes existing embeddings before regenerating
- Test skip logic when embeddings already exist
- Test handling of turns with None user_message/assistant_summary
- Test session embedding generation with None title/summary

**Effort:** Medium — requires mocking sentence-transformers.

---

### 5. `cli/futures_cmds.py` — 33% (231 lines missed of 345)

**What's untested:** CLI commands `futures_assess`, `futures_list`, `futures_feedback`,
`futures_lessons`, `futures_relate`, `futures_relationships`, `futures_unrelate`,
`futures_trend`, `futures_report`, `futures_tidy_pr`. Background worker management
(`futures_worker_status`, `futures_worker_stop`, `futures_worker_launch`). Internal helpers
`_get_staged_diff`, `_get_checkpoint_diff`, `_call_llm`, `_render_assessment`.

**Why it matters:** The futures system is one of the most feature-rich CLI surfaces.
Without tests, regressions in assessment workflows go undetected.

**Recommended tests:**
- CliRunner integration tests for each command with valid inputs
- Test `--verdict` filtering on `futures_list`
- Test `--since` filtering on `futures_report`
- Test relationship management (`relate`/`unrelate`)
- Test background worker PID file handling and stale process cleanup
- Mock LLM responses for assessment generation

**Effort:** High — many commands, LLM mocking needed, subprocess management.

---

### 6. `cli/import_cmds.py` — 22% (45 lines missed of 58)

**What's untested:** The `import_cmd()` CLI handler, `_import_from_aline()` workflow,
dry-run mode, skip-content mode, workspace filter, FTS rebuild after import, error
reporting.

**Why it matters:** Import is a one-shot operation users rely on for data migration. Bugs
can cause data loss or incomplete imports.

**Recommended tests:**
- Test import with a mock Aline database
- Test dry-run mode (no DB writes, shows summary)
- Test skip-content flag honored
- Test workspace filter applied
- Test error display when import partially fails
- Test FTS index rebuild triggered post-import

**Effort:** Medium — needs a small mock Aline DB fixture.

---

## Moderate Gaps (Coverage 35%–70%)

### 7. `core/llm.py` — 44% (46 lines missed of 82)

**What's untested:** All four LLM backends (`OpenAIBackend`, `CLIBackend`,
`OllamaBackend`, `GitHubModelsBackend`), `strip_markdown_fences()`, environment variable
validation, HTTP error handling.

**Recommended tests:**
- Mock `urlopen` for OpenAI/GitHub/Ollama backends
- Mock `subprocess.run` for CLI backend
- Test missing API key errors (OPENAI_API_KEY, GITHUB_TOKEN)
- Test HTTP errors (401, 500, timeout)
- Test `strip_markdown_fences()` with various formats (```json, ```python, no fences)
- Test bad JSON response handling

**Effort:** Low-Medium — straightforward mocking.

---

### 8. `hooks/handler.py` — 54% (21 lines missed of 46)

**What's untested:** `read_stdin_json()` error handling (empty stdin, malformed JSON),
handler dispatch for all 5 hook types, exception handling in handlers, unknown hook type
handling.

**Recommended tests:**
- Test `read_stdin_json()` with empty input, invalid JSON, valid JSON
- Test `handle_hook()` dispatches to correct handler for each hook type
- Test exception in handler is caught and returns error code
- Test unknown hook type returns 0 (success, no-op)

**Effort:** Low — small module, straightforward unit tests.

---

### 9. `core/search.py` — 67% (53 lines missed of 162)

**What's untested:** `_apply_query_redaction()`, `_regex_search_content()` (file content
search via grep patterns), JSON parsing of `files_touched`, content file loading, FTS
search with various filter combinations.

**Recommended tests:**
- Test query redaction with configured patterns
- Test `_regex_search_content()` against actual JSONL content files
- Test file filter combinations
- Test `--since` timestamp filtering
- Test graceful handling of missing content files
- Test null fields in search results

**Effort:** Medium — some tests need content files on disk.

---

### 10. `sync/auto_sync.py` — 63% (34 lines missed of 92)

**What's untested:** `run_sync()` and `run_pull()` entry points, lock
acquisition/release, error logging to DB, stale lock cleanup, background subprocess
spawning.

**Recommended tests:**
- Test `run_sync()` acquires lock, calls `perform_sync`, releases lock
- Test `run_pull()` acquires lock, calls `perform_pull`, releases lock
- Test lock contention (second sync attempt while first holds lock)
- Test stale lock detection (PID no longer running)
- Test error logged to `sync_metadata` on failure
- Test `should_sync()` / `should_pull()` cooldown logic

**Effort:** Medium — subprocess/lock testing requires care.

---

## Noteworthy Mid-Range Gaps

| Module | Coverage | Key Gap |
|--------|----------|---------|
| `cli/rewind_cmds.py` | 69% | Rewind execution flow, safety checks |
| `hooks/codex_ingest.py` | 72% | Codex transcript parsing, multi-turn extraction |
| `core/embedding.py` | 76% | Cosine similarity search, model loading errors |
| `core/config.py` | 79% | TOML deep merge, global config loading |
| `core/import_aline.py` | 80% | Multi-table import, error recovery |
| `core/project.py` | 80% | Project creation edge cases, path resolution |
| `cli/checkpoint_cmds.py` | 81% | Checkpoint restore flow, diff display |
| `hooks/session_lifecycle.py` | 81% | Session end handling, cleanup logic |

---

## Qualitative Observations

### What's tested well
- **Core business logic** (turns, events, sessions, exports) has strong coverage
- **CLI integration tests** use `CliRunner` effectively for most commands
- **Fixtures** (`git_repo`, `ec_repo`, `ec_db`, `isolated_global_db`) are well-designed
  and reusable
- **FTS search** is well-tested through multiple test files
- **Cross-repo operations** have good coverage at 92%

### Structural test gaps
1. **No error/exception path testing** for most modules. Happy paths are tested but
   failure modes (network errors, corrupt data, permission issues) are rarely exercised.
2. **No tests for LLM integration** — all LLM-backed features (futures assessment, tidy
   PR, codex ingest analysis) lack mocked LLM response tests.
3. **Background worker/subprocess management** is entirely untested across all modules
   that spawn subprocesses.
4. **Resource cleanup** — the ResourceWarning about unclosed database connections in test
   output suggests some fixtures don't properly close DB connections.

### Recommendations by priority

**Priority 1 — Quick wins (low effort, high value):**
- `hooks/handler.py` — add 4-5 unit tests for dispatch and error paths
- `core/llm.py` — add mock tests for each backend
- `sync/exporter.py` — add file I/O tests with `tmp_path`
- `sync/shadow_branch.py` — add git operation tests using `git_repo` fixture
- Fix ResourceWarning by ensuring DB connections are closed in fixtures

**Priority 2 — Medium effort, high value:**
- `core/search.py` — add content search and redaction tests
- `cli/import_cmds.py` — add integration tests with mock Aline DB
- `core/indexing.py` — add embedding generation tests with mocked model
- `sync/auto_sync.py` — add entry point and lock management tests

**Priority 3 — High effort, strategic value:**
- `mcp/server.py` — build MCP testing infrastructure, test all tool handlers
- `cli/futures_cmds.py` — comprehensive CLI tests for all futures commands
- Add error path / exception testing across all modules
- Add background worker lifecycle tests

**Target:** Reaching 85% overall coverage by addressing Priority 1 and 2 items would
cover the most impactful gaps. Reaching 90%+ would require the Priority 3 items,
particularly the MCP server tests.
