# EntireContext

**Time-travel searchable agent memory anchored to your codebase.**

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue) ![Version 0.1.0](https://img.shields.io/badge/version-0.1.0-green) ![Status Experimental](https://img.shields.io/badge/status-experimental-orange) ![License MIT](https://img.shields.io/badge/license-MIT-lightgrey)

> ⚠️ **Experimental** — API and data format may change without notice.

EntireContext automatically captures every AI coding session — turns, checkpoints, tool calls — and anchors them to your git history. Search, rewind, blame, and sync your agent memory across repos and machines.

## Features

- **Auto session/turn capture** via Claude Code hooks — zero-friction recording
- **Git-anchored checkpoints** — snapshots tied to specific commits
- **3 search modes** — regex, FTS5 full-text, and semantic (sentence-transformers)
- **Per-line attribution** — `ec blame` shows human vs. agent authorship per file
- **Cross-repo search** — query across all registered repos with `-g`/`-r` flags
- **Shadow branch sync** — portable export/import via orphan git branch
- **Secret filtering** — configurable patterns strip credentials on export
- **MCP server** — 9 tools for AI agents to query context programmatically
- **Futures assessment** — LLM-powered code change evaluation based on "Tidy First?" philosophy
- **Data import** — migrate sessions from Aline databases
- **Event system** — group sessions by task, temporal period, or milestone

## Quick Start

Choose an install path first:

- **Local dependency** (inside a Python/uv project)
- **Global install (optional)** for using `ec` as a standalone CLI across any repo

Use **global install (optional)** when you want `ec` like an app/tool.
Use **local dependency** when you want to manage `entirecontext` in a Python project's dependencies.

```bash
# 1A. Local dependency (Python/uv project)
uv add entirecontext
# or: pip install entirecontext
```

```bash
# 1B. Global install (optional, recommended for non-Python repos)
uv tool install entirecontext
# alternative:
pipx install entirecontext
```

Use the same workflow after either install path:

```bash
# 2. Initialize in your repo
cd your-project
ec init

# 3. Install Claude Code hooks
ec enable

# 4. Use Claude Code as usual — sessions are captured automatically

# 5. Query your history
ec search "authentication"
ec search "refactor" --fts
ec session list
ec blame src/main.py
ec checkpoint list
```

### Windows Notes

- Install alternative (Python launcher): `py -m pip install entirecontext`
- PowerShell example:
  ```powershell
  ec init
  ec enable
  ec search "authentication"
  ```
- If `ec` is not recognized, open a new terminal (or sign out/in) so updated PATH is loaded.
- For `uv tool`/`pipx` installs, ensure the scripts directory is on PATH.

## CLI Reference

### Top-Level Commands

| Command | Description |
|---------|-------------|
| `ec init` | Initialize EntireContext in current git repo |
| `ec enable [--no-git-hooks]` | Install Claude Code hooks and git hooks (skip git hooks with `--no-git-hooks`) |
| `ec disable` | Remove Claude Code hooks |
| `ec status` | Show capture status (project, sessions, turns, active session) |
| `ec config [KEY] [VALUE]` | Get or set configuration (dotted keys) |
| `ec doctor` | Diagnose issues (schema, hooks, unsynced checkpoints) |
| `ec search QUERY` | Search across sessions, turns, and events |
| `ec blame FILE [-L START,END] [--summary]` | Show per-line human/agent attribution |
| `ec rewind CHECKPOINT_ID` | Show or restore code state at a checkpoint |
| `ec sync [--no-filter]` | Export to shadow branch and push (skip secret filtering with `--no-filter`) |
| `ec pull` | Fetch shadow branch and import |
| `ec index [--semantic] [--force] [--model NAME]` | Rebuild FTS5 indexes, optionally generate embeddings |

### `ec session` Subcommands

| Command | Description |
|---------|-------------|
| `ec session list` | List sessions (with turn counts and status) |
| `ec session show SESSION_ID` | Show session details and turn summaries |
| `ec session current` | Show current active session |

### `ec checkpoint` Subcommands

| Command | Description |
|---------|-------------|
| `ec checkpoint list` | List checkpoints (commit, branch, diff summary) |
| `ec checkpoint show CHECKPOINT_ID` | Show checkpoint details and file snapshot |
| `ec checkpoint diff ID1 ID2` | Diff between two checkpoints |

### `ec event` Subcommands

| Command | Description |
|---------|-------------|
| `ec event list` | List events (filter by `--status`, `--type`) |
| `ec event show EVENT_ID` | Show event details and linked sessions |
| `ec event create TITLE` | Create event (`--type task\|temporal\|milestone`) |
| `ec event link EVENT_ID SESSION_ID` | Link a session to an event |

### `ec futures` Subcommands

| Command | Description |
|---------|-------------|
| `ec futures assess [-c CHECKPOINT] [-r ROADMAP] [-m MODEL] [-b BACKEND]` | Assess staged diff or checkpoint against roadmap via LLM |
| `ec futures list [-v VERDICT] [-n LIMIT]` | List assessments (filter by `--verdict`) |
| `ec futures feedback ID FEEDBACK [-r REASON]` | Add agree/disagree feedback to an assessment |
| `ec futures lessons [-o OUTPUT] [-s SINCE]` | Generate LESSONS.md from assessed changes with feedback |

### LLM Backends (`ec futures assess`)

| Backend | Flag | Auth | Default Model |
|---------|------|------|---------------|
| `openai` | `-b openai` | `OPENAI_API_KEY` | `gpt-4o-mini` |
| `github` | `-b github` | `GITHUB_TOKEN` | `openai/gpt-4o-mini` |
| `ollama` | `-b ollama` | None (local) | `llama3` |
| `codex` | `-b codex` | CLI subprocess | — |
| `claude` | `-b claude` | CLI subprocess | — |

### `ec import` Command

| Command | Description |
|---------|-------------|
| `ec import --from-aline [PATH]` | Import sessions/turns/checkpoints from Aline DB |

Options: `--workspace`, `--dry-run`, `--skip-content`

### `ec repo` Subcommands

| Command | Description |
|---------|-------------|
| `ec repo list` | List all registered EntireContext projects |

### Common Flags

| Flag | Description |
|------|-------------|
| `-g`, `--global` | Search/list across all registered repos |
| `-r`, `--repo NAME` | Filter by repo name (repeatable) |
| `-n`, `--limit N` | Max results (default 20) |

### Search Options

| Flag | Description |
|------|-------------|
| `--fts` | Use FTS5 full-text search |
| `--semantic` | Use semantic search (requires `entirecontext[semantic]`) |
| `--file PATH` | Filter by file path |
| `--commit HASH` | Filter by commit hash |
| `--agent TYPE` | Filter by agent type |
| `--since ISO8601` | Filter by date |
| `-t TARGET` | Search target: `turn` (default), `session`, `event`, `content` |

## MCP Server

### Automatic Setup

`ec enable` automatically registers the MCP server in `~/.claude/settings.json` (user-level):

```bash
ec enable    # installs hooks AND configures MCP server
ec doctor    # verify MCP config is present
```

This is idempotent — running `ec enable` again skips the MCP entry if it already exists. `ec disable` removes hooks but preserves the MCP config (other repos may use it).

### Manual Setup

To configure manually, add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "entirecontext": {
      "command": "ec",
      "args": ["mcp", "serve"],
      "type": "stdio"
    }
  }
}
```

### Manual Removal

To remove the MCP server, delete the `entirecontext` key from `~/.claude/settings.json`:

```bash
# Remove MCP config (use jq or edit manually)
jq 'del(.mcpServers.entirecontext)' ~/.claude/settings.json > tmp.json && mv tmp.json ~/.claude/settings.json
```

### Standalone Server

To run the MCP server directly (e.g. for debugging):

```bash
ec mcp serve
```

### Available Tools

| Tool | Description |
|------|-------------|
| `ec_search` | Search turns/sessions with regex or FTS5. Filters: `file_filter`, `commit_filter`, `agent_filter`, `since` |
| `ec_checkpoint_list` | List checkpoints, optionally filtered by `session_id` and `since` |
| `ec_session_context` | Get session details with recent turns. Auto-detects current session if `session_id` omitted |
| `ec_attribution` | Get human/agent attribution for a file, with optional line range |
| `ec_rewind` | Show state at a specific checkpoint |
| `ec_related` | Find related sessions/turns by query text or file paths |
| `ec_turn_content` | Get full content for a specific turn (including JSONL content files) |
| `ec_assess` | Assess staged diff or checkpoint against roadmap via LLM |
| `ec_lessons` | Generate LESSONS.md from assessed changes with feedback |

All tools accept a `repos` parameter for cross-repo queries: `null` = current repo, `["*"]` = all repos, `["name"]` = specific repos.

## Hook System

`ec enable` installs two kinds of hooks automatically. No manual intervention required.

### Claude Code Hooks (`.claude/settings.local.json`)

| Hook Type | Trigger | Action |
|-----------|---------|--------|
| `SessionStart` | Claude Code session begins | Create/resume session record |
| `UserPromptSubmit` | User sends a message | Record turn start |
| `Stop` | Assistant completes response | Record turn end with summary |
| `PostToolUse` | Tool call completes | Track files touched and tools used |
| `SessionEnd` | Claude Code session ends | Finalize session, generate summary |

Hook protocol: stdin JSON, exit code 0 = success, 2 = block.

### Git Hooks (`.git/hooks/`)

| Hook | Trigger | Action |
|------|---------|--------|
| `post-commit` | `git commit` | Create checkpoint tied to the new commit if a session is active |
| `pre-push` | `git push` | Run `ec sync` if `auto_sync_on_push` is enabled |

Skip git hook installation with `ec enable --no-git-hooks`. Both hooks are removed by `ec disable`.

## Configuration

Config merges in order: **defaults** ← **global** (`~/.entirecontext/config.toml`) ← **per-repo** (`.entirecontext/config.toml`).

### Default Configuration

```toml
[capture]
auto_capture = true
checkpoint_on_commit = true

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
    '(?i)(api[_-]?key|secret|password|token)\s*[=:]\s*[\'"]?[\w-]+',
    '(?i)bearer\s+[\w.-]+',
    'ghp_[a-zA-Z0-9]{36}',
    'sk-[a-zA-Z0-9]{48}',
]
```

### CLI Usage

```bash
ec config                              # show all config
ec config search.default_mode          # get a value
ec config search.default_mode fts      # set a value
ec config security.filter_secrets true # set a value
```

## Architecture

Sessions, turns, and checkpoints flow from Claude Code hooks through the core business logic into SQLite, with optional export via shadow branch sync.

```
CLI (Typer)  →  core/  →  db/  →  hooks/  →  sync/
cli/             business    SQLite     Claude Code   shadow branch
  project_cmds   logic       schema     integration   export/import
  session_cmds   config      migration  turn capture  merge
  search_cmds    security    connection session lifecycle
  hook_cmds      cross_repo
  checkpoint_cmds attribution
  sync_cmds      event
  rewind_cmds    indexing
  repo_cmds      search
  event_cmds     futures
  blame_cmds     llm
  index_cmds     import_aline
  mcp_cmds
  futures_cmds
  import_cmds

mcp/server.py — MCP server interface (optional dependency)
```

### Data Model

| Table | Purpose |
|-------|---------|
| `projects` | Registered repos (name, path, remote URL) |
| `sessions` | Captured sessions (type, title, summary, turn count) |
| `turns` | Individual turns (user message, assistant summary, files touched) |
| `turn_content` | JSONL content file references for full turn data |
| `checkpoints` | Git-anchored snapshots (commit hash, branch, file snapshot, diff) |
| `agents` | Agent identities (type, role, parent agent) |
| `events` | Grouping mechanism (task / temporal / milestone) |
| `event_sessions` | Many-to-many link between events and sessions |
| `event_checkpoints` | Many-to-many link between events and checkpoints |
| `assessments` | Futures assessment results (verdict, impact, feedback) |
| `attributions` | Per-line human/agent file attribution |
| `embeddings` | Semantic search vectors |
| `sync_metadata` | Shadow branch sync state |

FTS5 virtual tables: `fts_turns`, `fts_events`, `fts_sessions` — auto-synced via triggers.

### Data Locations

| Path | Contents |
|------|----------|
| `.entirecontext/db/local.db` | Per-repo SQLite database |
| `.entirecontext/content/` | JSONL turn content files |
| `.entirecontext/config.toml` | Per-repo configuration |
| `~/.entirecontext/db/ec.db` | Global database (cross-repo registry) |
| `~/.entirecontext/config.toml` | Global configuration |

## Development

```bash
git clone https://github.com/teslamint/entirecontext.git
cd entirecontext
uv sync --extra dev
```

### Run Tests

```bash
uv run pytest                          # all tests
uv run pytest tests/test_core.py       # single file
uv run pytest -k "test_search"         # by name pattern
uv run pytest --cov=entirecontext      # with coverage
```

### Lint & Format

```bash
uv run ruff format .                   # format (line-length 120)
uv run ruff check . --fix              # lint + autofix
```

### Optional Extras

| Extra | Dependencies | Purpose |
|-------|-------------|---------|
| `dev` | pytest, pytest-cov, ruff | Testing and linting |
| `semantic` | sentence-transformers | Semantic search with embeddings |
| `mcp` | mcp | MCP server for AI agent integration |

Install extras: `uv sync --extra dev --extra semantic --extra mcp`

## Development Context
This project's entire AI development history is available
on the `entirecontext/checkpoints/v1` branch.

## Acknowledgments

EntireContext was inspired by:

- [entireio/cli](https://github.com/entireio/cli) — Git-integrated AI agent session capture and context management
- [TheAgentContextLab/OneContext](https://github.com/TheAgentContextLab/OneContext) — Agent self-managed context layer for unified AI agent memory
- The **Futures Assessment** feature (`ec futures`) is inspired by Kent Beck's [Earn *And* Learn](https://tidyfirst.substack.com/p/earn-and-learn) and the [Tidy First](https://tidyfirst.substack.com/) philosophy — analyzing whether each change expands or narrows your project's future options.

## License

[MIT](LICENSE)
