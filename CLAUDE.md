# EntireContext

Time-travel searchable agent memory anchored to git state. Python 3.12+, uv, SQLite (WAL mode), Typer CLI (`ec`).

## Build & Run

```bash
uv sync                          # install deps
uv sync --extra dev              # + dev tools (pytest, ruff)
uv sync --extra semantic         # + sentence-transformers
uv sync --extra mcp              # + MCP server support
uv run ec --help                 # CLI entry point
```

## Test

```bash
uv run pytest                    # all tests
uv run pytest tests/test_core.py # single file
uv run pytest -k "test_search"   # by name pattern
uv run pytest --cov=entirecontext # coverage
```

Tests use real git repos via fixtures (`git_repo`, `ec_repo`, `ec_db`, `isolated_global_db`). External deps are isolated with `monkeypatch`. See `tests/conftest.py`.

## Lint & Format

```bash
uv run ruff format .             # format (line-length 120)
uv run ruff check . --fix        # lint + autofix
```

## Architecture

```
CLI (Typer)  →  core/  →  db/  →  hooks/  →  sync/
cli/             business    SQLite     Claude Code   shadow branch
  project_cmds   logic       schema     integration   export/import
  session_cmds   config      migration  turn capture  merge
  search_cmds    security    connection session lifecycle
  hook_cmds      cross_repo
  checkpoint_cmds
  sync_cmds
  rewind_cmds
  repo_cmds
```

`mcp/server.py` — MCP server interface (optional dependency).

## Data Model

**Per-repo DB**: `.entirecontext/db/local.db`
**Global DB**: `~/.entirecontext/db/ec.db`

Key tables: `projects`, `sessions`, `turns`, `turn_content`, `checkpoints`, `agents`, `events`, `attributions`, `embeddings`, `sync_metadata`

FTS5 virtual tables: `fts_turns`, `fts_events`, `fts_sessions` (auto-synced via triggers)

Hybrid storage: SQLite for metadata/search, JSONL content files referenced by `turn_content.content_path`.

## Hook System

Claude Code hooks integration via stdin JSON protocol. Entry: `hooks/handler.py` → dispatches to handlers.

5 hook types: `SessionStart`, `UserPromptSubmit`, `Stop`, `PostToolUse`, `SessionEnd`

Return codes: 0=success, 2=block.

## Config

TOML deep merge: defaults ← `~/.entirecontext/config.toml` (global) ← `.entirecontext/config.toml` (per-repo)

Sections: `capture`, `search`, `sync`, `display`, `security`

## Code Conventions

- ruff formatter, line-length 120, target Python 3.12
- Type hints throughout (`from __future__ import annotations`)
- SQLite pragmas: WAL, foreign_keys=ON, busy_timeout=5000
