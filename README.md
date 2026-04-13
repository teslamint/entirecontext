# EntireContext

**Git-anchored decision memory for coding agents.**

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue) ![Version 0.1.0](https://img.shields.io/badge/version-0.1.0-green) ![Status Experimental](https://img.shields.io/badge/status-experimental-orange) ![License MIT](https://img.shields.io/badge/license-MIT-lightgrey)

> ⚠️ **Experimental** — API and data format may change without notice.

EntireContext captures AI coding work as it happens, distills decisions and lessons from it, and brings the right context back when similar code changes happen again.

## Why It Exists

AI coding tools generate changes quickly, but engineering judgment still gets buried in chat logs. Important decisions, rejected alternatives, and hard-won lessons disappear across sessions, repos, and agents, so teams keep rediscovering the same context.

EntireContext turns session history into reusable engineering memory tied to commits, diffs, checkpoints, and files instead of leaving it as raw transcript storage.

## Core Product Loop

- **Capture** — sessions, turns, tool calls, and checkpoints are recorded through hooks and anchored to git history
- **Distill** — assessments, feedback, and lessons convert raw session history into reusable judgment
- **Retrieve** — search, graph traversal, attribution, and rewind surface the most relevant prior context
- **Intervene** — agents and humans can apply past decisions before the next related change lands

## How Decision Memory Works

- **Decision** — reusable engineering intent (what was chosen, why, what was rejected), linked to files, checkpoints, and assessments
- **Assessment** — point-in-time evaluation of a diff or checkpoint (expand / narrow / neutral) using Tidy First framing
- **Lesson** — assessment + feedback distilled into guidance for future changes

Decisions accumulate during sessions. Assessments evaluate their impact. Feedback closes the loop and distills lessons that surface before the next related change.

## Staleness Policy

Decisions carry a `staleness_status` so old guidance can be prevented from dominating retrieval when the code or newer decisions no longer agree with it.

### The four states

| Status | Meaning | Who sets it |
|---|---|---|
| `fresh` | Current, actively applicable | Default on create |
| `stale` | Linked files changed since creation; may still apply | `ec decision stale` or session-end hook |
| `superseded` | Replaced by a newer decision | `ec decision supersede <old> <new>` |
| `contradicted` | Usage feedback shows the decision was wrong | Manual `ec decision stale --status contradicted`, or auto-promoted after ≥2 `contradicted` outcomes when they exceed `accepted` outcomes |

### Retrieval defaults per entry point

| Entry point | fresh | stale | superseded | contradicted |
|---|---|---|---|---|
| `ec_decision_related` / `rank_related_decisions` | shown | demoted 0.85× | hidden (successor substituted) | hidden |
| `ec_decision_search` / `fts_search_decisions` / `hybrid_search_decisions` | shown | shown | hidden | shown (v0.2.x) / hidden (v0.3.0) |
| `ec_decision_list` / `ec decision list` | shown | shown | shown | shown (inventory — explicit status filter) |
| `ec_decision_get(id)` | shown (no successor) | shown | shown + `successor` pointer | shown |
| Session-start hook | shown | shown | replaced by successor | hidden |

Opt in to include filtered decisions via flags:
- `include_stale` (default `True`) — stale decisions pass through with 0.85× demotion
- `include_superseded` (default `False`) — returns the original without chain collapse
- `include_contradicted` (default `False` in `rank_related_decisions`; `True` in FTS/hybrid during the v0.2.x deprecation window)

### Supersession chain behavior

When a decision is superseded, retrieval follows `superseded_by_id` to the terminal successor:

- **Terminal is usable** → ranking substitutes the terminal; the old ancestors are dropped.
- **Terminal is contradicted** → the entire chain is filtered out and reported in `filter_stats.by_reason["chain_terminal_contradicted"]`.
- **Cycle protection** — `supersede_decision` rejects inputs that would create a cycle; walks are also bounded by a depth cap (10 hops).
- **Debugging** — `ec decision chain <id>` prints the full walk (id, title, status) from origin to terminal.

### Auto-promotion from outcome tracking

`record_decision_outcome` recognizes usage feedback. When a decision accumulates ≥2 `contradicted` outcomes **and** contradicted > accepted, its `staleness_status` is automatically promoted to `contradicted`. This is a **one-way ratchet** — later accepted outcomes never auto-revert the status; a manual `ec decision stale --status fresh` is required to recover, and that manual reset also restarts the auto-promotion window so only post-reset outcomes count toward the next promotion.

Note: `decision_outcomes.outcome_type='contradicted'` (usage feedback) is distinct from `decision_assessments.relation_type='contradicts'` (metadata). The latter does not trigger auto-promotion.

Configure the threshold via `[decisions]` in `.entirecontext/config.toml`:

```toml
[decisions]
auto_promotion_contradicted_threshold = 2
```

### Deprecation window

During the v0.2.x release, `fts_search_decisions` / `hybrid_search_decisions` / `ec decision search` default to `include_contradicted=True` to preserve existing caller behavior. The default will flip to `False` in **v0.3.0**. Pass `include_contradicted=False` now (or `--no-include-contradicted` from the CLI) to opt into the future default.

## What Makes EntireContext Different

- **Git-anchored memory** — context is tied to commits, branches, diffs, and checkpoints
- **Decision-oriented, not chat-oriented** — the goal is reusable engineering judgment, not transcript hoarding
- **Built for coding agents** — native hook integration plus MCP access for in-session retrieval
- **Per-repo and cross-repo** — preserve local project context while allowing broader learning patterns

## Key Capabilities

### Core Capability: Decision Memory
- **Decision capture** — rationale, rejected alternatives, scope, and staleness tracking
- **Assessments and lessons** — futures evaluations, feedback loops, and distilled guidance
- **Proactive retrieval** — relevant past decisions surfaced when similar files or diffs appear

### Supporting Capabilities
- **Git time-travel** — checkpoints, rewind, blame, and attribution
- **Context retrieval** — regex, FTS5, semantic, and hybrid search across sessions and repos
- **Agent interfaces** — MCP tools for search, checkpoints, assessments, graph traversal, and trends
- **Operational tooling** — sync, filtering, consolidation, dashboarding, export, and migration

## Who It's For

- Engineers already using coding agents in day-to-day development
- Small teams that want decisions and lessons to accumulate instead of disappearing into chat history
- Repositories where historical intent matters as much as the final diff

## Agent Setup Templates

Templates for configuring agents to proactively reuse stored decisions and lessons.

- Maintainers: [entirecontext-maintainer-decision-reuse-template.md](docs/templates/entirecontext-maintainer-decision-reuse-template.md)
- Users: [entirecontext-user-decision-reuse-template.md](docs/templates/entirecontext-user-decision-reuse-template.md)
- Proactive guidance: [entirecontext-proactive-guidance.md](docs/templates/entirecontext-proactive-guidance.md) — broader memory reuse beyond decisions (assessments, lessons, checkpoints, attribution)

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

The sections below are reference material for the current CLI surface. They stay close to the implemented interface on purpose so the product narrative above does not drift from what the tool actually does.

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
| `ec sync [--no-filter]` | Export to shadow branch, then push with one automatic artifact-merge retry on non-fast-forward (skip secret filtering with `--no-filter`) |
| `ec pull` | Fetch latest `origin` shadow branch snapshot and import |
| `ec index [--semantic] [--force] [--model NAME]` | Rebuild FTS5 indexes, optionally generate embeddings |
| `ec dashboard [--since DATE] [--limit N]` | Show team dashboard: sessions, checkpoints, assessment trends |
| `ec graph [--session ID] [--since DATE] [--limit N]` | Show knowledge graph of git entities |
| `ec ast-search QUERY [--type TYPE] [--file PATH] [--limit N]` | Search indexed Python AST symbols |

### `ec session` Subcommands

| Command | Description |
|---------|-------------|
| `ec session list` | List sessions (with turn counts and status) |
| `ec session show SESSION_ID` | Show session details and turn summaries |
| `ec session current` | Show current active session |
| `ec session export ID [--output FILE]` | Export session as Markdown (YAML frontmatter + sections) |
| `ec session graph [--agent ID] [--session ID] [--depth N]` | Visualise multi-agent session graph |
| `ec session activate [--turn ID] [--session ID] [--hops N] [--limit N]` | Find related turns via spreading activation |
| `ec session consolidate [--before DATE] [--session ID] [--limit N] [--execute]` | Compress old turn content (dry-run by default) |

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
| `ec futures trend [--since DATE] [--limit N]` | Show cross-repo assessment trend analysis |
| `ec futures relate SRC TYPE TGT [--note TEXT]` | Add typed relationship between assessments |
| `ec futures relationships ID [--direction DIR]` | List relationships for an assessment |
| `ec futures unrelate SRC TYPE TGT` | Remove a typed relationship |
| `ec futures tidy-pr [--since DATE] [--limit N] [--output FILE]` | Generate tidy PR draft from narrow assessments |
| `ec futures report [--since DATE] [--limit N] [--output FILE]` | Generate team-shareable Markdown report |
| `ec futures worker-status` | Show background assessment worker status |
| `ec futures worker-stop` | Stop background assessment worker |
| `ec futures worker-launch [--diff TEXT]` | Launch background assessment worker |
| `ec decision create TITLE [--rationale TEXT] [--scope TEXT]` | Create a decision record |
| `ec decision list [--status STATUS] [--file PATH] [--limit N]` | List decisions (optional staleness/file filter) |
| `ec decision show DECISION_ID` | Show decision details and linked artifacts |
| `ec decision link DECISION_ID [--assessment ID\|--checkpoint ID\|--commit SHA\|--file PATH]` | Link decision to assessment/checkpoint/commit/file |
| `ec decision stale DECISION_ID --status STATUS` | Update decision staleness (`fresh\|stale\|superseded\|contradicted`) |

### LLM Backends (`ec futures assess`)

| Backend | Flag | Auth | Default Model |
|---------|------|------|---------------|
| `openai` | `-b openai` | `OPENAI_API_KEY` | `gpt-4o-mini` |
| `github` | `-b github` | `GITHUB_TOKEN` | `openai/gpt-4o-mini` |
| `ollama` | `-b ollama` | None (local) | `llama3` |
| `codex` | `-b codex` | CLI subprocess | — |
| `claude` | `-b claude` | CLI subprocess | — |

### `ec purge` Subcommands

| Command | Description |
|---------|-------------|
| `ec purge session SESSION_ID [--execute] [--force]` | Purge a session and all its turns (dry-run by default) |
| `ec purge turn TURN_ID... [--execute]` | Purge specific turns by ID |
| `ec purge match PATTERN [--execute] [--force]` | Purge turns matching a regex pattern |

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
| `--hybrid` | Use hybrid search (FTS5 + recency RRF reranking) |
| `--file PATH` | Filter by file path |
| `--commit HASH` | Filter by commit hash |
| `--agent TYPE` | Filter by agent type |
| `--since ISO8601` | Filter by date |
| `-t TARGET` | Search target: `turn` (default), `session`, `event`, `content` |

## MCP Server

EntireContext exposes the same retrieval and assessment primitives to coding agents over MCP so the memory loop can run inside active coding sessions, not only through the CLI.

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
| `ec_decision_create` | Create a decision record (title, rationale, rejected alternatives, scope) |
| `ec_decision_get` | Resolve decision by full or prefix ID |
| `ec_decision_related` | Rank linked decisions by file overlap, assessment relations, and diff text match |
| `ec_search` | Search turns/sessions with regex or FTS5. Filters: `file_filter`, `commit_filter`, `agent_filter`, `since` |
| `ec_checkpoint_list` | List checkpoints, optionally filtered by `session_id` and `since` |
| `ec_session_context` | Get session details with recent turns. Auto-detects current session if `session_id` omitted |
| `ec_attribution` | Get human/agent attribution for a file, with optional line range |
| `ec_rewind` | Show state at a specific checkpoint |
| `ec_related` | Find related sessions/turns by query text or file paths |
| `ec_turn_content` | Get full content for a specific turn (including JSONL content files) |
| `ec_assess` | Assess staged diff or checkpoint against roadmap via LLM |
| `ec_assess_create` | Create an assessment programmatically (verdict, impact, suggestion) |
| `ec_feedback` | Add agree/disagree feedback to an assessment |
| `ec_lessons` | Generate LESSONS.md from assessed changes with feedback |
| `ec_assess_trends` | Cross-repo assessment trend analysis (verdict distribution, feedback stats) |

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

[capture.exclusions]
enabled = false
content_patterns = []    # regex — skip turns matching these
file_patterns = []       # glob — exclude files from tracking
tool_names = []          # exact — skip tool usage recording
redact_patterns = []     # regex — replace matches with [FILTERED] before storage

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

[filtering.query_redaction]
enabled = false
patterns = []            # regex — redact matches in search/MCP results
replacement = "[FILTERED]"
```

### CLI Usage

```bash
ec config                              # show all config
ec config search.default_mode          # get a value
ec config search.default_mode fts      # set a value
ec config security.filter_secrets true # set a value
```

## Sync Policy

Shadow branch sync uses artifact-level merge only on `entirecontext/checkpoints/v1`.

- `ec sync` performs one automatic retry only, and only when the first push is rejected as non-fast-forward.
- The retry path fetches `origin/entirecontext/checkpoints/v1`, merges exported artifacts, creates a new commit, and pushes again.
- `ec pull` imports from the latest `origin/<shadow-branch>` remote-tracking snapshot, not from the local shadow branch.
- There is no git conflict UI and no general git 3-way merge support in this path.
- Artifact merge policy:
  - `manifest.json`: key union; higher `total_turns` wins for duplicate session entries.
  - `sessions/<id>/meta.json`: higher `total_turns` wins; ties preserve non-null fields; `started_at` uses earlier value; `ended_at` uses later value.
  - `sessions/<id>/transcript.jsonl`: deduplicate by turn `id`.
  - `checkpoints/*.json`: filename union.
- Malformed remote artifacts, missing remote shadow snapshots, and retry push failures are explicit sync errors.

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
  mcp_cmds       content_filter
  futures_cmds   purge
  import_cmds    export
  purge_cmds     report
  graph_cmds     tidy_pr
  ast_cmds       dashboard
  dashboard_cmds ast_index
               knowledge_graph
               agent_graph
               activation
               consolidation
               hybrid_search
               async_worker

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
| `assessment_relationships` | Typed links between assessments (causes/fixes/contradicts) |
| `attributions` | Per-line human/agent file attribution |
| `embeddings` | Semantic search vectors |
| `ast_symbols` | Python AST symbol index (functions, classes, methods) |
| `sync_metadata` | Shadow branch sync state |

FTS5 virtual tables: `fts_turns`, `fts_events`, `fts_sessions`, `fts_ast_symbols` — auto-synced via triggers.

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

