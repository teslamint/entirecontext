# EntireContext — Specification

> Time-travel searchable agent memory anchored to your codebase.

**Version**: 0.1.0-draft
**Status**: Design phase

---

## 1. Vision

Every agent context is anchored to git state. Every git state is enriched with searchable agent context. EntireContext provides a **code-connected, time-travelable, searchable agent memory**.

### Core Value Proposition

| Without EntireContext | With EntireContext |
|---|---|
| Agent sessions are ephemeral | Every session persists and is searchable |
| Git commits lack context on *why* | Every commit links to the agent conversation that produced it |
| Past debugging sessions are lost | Search "how did we fix the auth bug?" across all history |
| Multi-agent work is opaque | Full attribution: who (human/agent) changed what and why |
| Context resets every session | Agents can query their own history via MCP |

---

## 2. Architecture

### 2.1 System Layers

```
┌─────────────────────────────────────────────────┐
│                   User / Agent                   │
├─────────────┬───────────────────┬───────────────┤
│  CLI (ec)   │   Agent Hooks     │  MCP Server   │
│  (Typer)    │   (Claude Code)   │  (stdio)      │
├─────────────┴───────────────────┴───────────────┤
│                  Core Engine                      │
│  ┌──────────┬───────────┬──────────┬──────────┐ │
│  │ Capture  │ Checkpoint│  Search  │Attribution│ │
│  └──────────┴───────────┴──────────┴──────────┘ │
├─────────────────────────────────────────────────┤
│              Storage Layer                       │
│  ┌────────────────┐  ┌────────────────────────┐ │
│  │ SQLite (local + │  │ Git Shadow Branch      │ │
│  │ global DB)      │  │ (portable artifacts)   │ │
│  └────────────────┘  └────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

### 2.2 Dual Interface

- **CLI (`ec`)**: Human-facing. Typer-based. Commands for search, checkpoint management, blame, sync.
- **MCP Server**: Agent-facing. stdio transport. Tools for search, context retrieval, checkpoint listing.

### 2.3 Storage Strategy

**SQLite is the authoritative store.** Git shadow branch is the portable sync artifact.

| Store | Role | Location |
|---|---|---|
| Per-repo DB | Session/turn/checkpoint data for one repo | `.entirecontext/db/local.db` |
| Global DB | Cross-repo reference index | `~/.entirecontext/db/ec.db` |
| Shadow branch | Checkpoint manifests + session transcripts (JSONL) | `entirecontext/checkpoints/v1` (orphan branch) |

**Data flow**: Capture → SQLite (authoritative) → Shadow branch (export for sync). On `ec pull`, shadow branch → SQLite (import).

Turn content uses hybrid storage: metadata and summaries in SQLite, full JSONL content in external files under `.entirecontext/content/`.

---

## 3. Data Model

### 3.1 Entity Relationship

```
Project ──1:N──> Session ──1:N──> Turn
                   │                │
                   │                └── TurnContent (1:1, separated)
                   │
                   ├──1:N──> Checkpoint ──> git commit binding
                   │
                   └──N:1──> Agent (self-ref parent_agent_id)

Event ──M:N──> Session   (semantic grouping)
Event ──M:N──> Checkpoint (event-checkpoint link)

Embedding ──> source_type + source_id (polymorphic ref)
Attribution ──> file + line range + agent/human origin
```

### 3.2 Schema (V1)

> **Requires SQLite 3.38.0+** (for JSON functions and generated columns).

#### `schema_version`

```sql
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now')),
    description TEXT
);
```

> **Migration strategy**: On startup, check current version → apply pending migrations sequentially via ALTER TABLE. Forward-only (no downgrade support).

#### `projects`

```sql
CREATE TABLE projects (
    id TEXT PRIMARY KEY,                -- UUID
    name TEXT NOT NULL,
    repo_path TEXT NOT NULL UNIQUE,     -- Absolute path to git repo root
    remote_url TEXT,                    -- Git remote origin URL
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    config TEXT                         -- JSON: project-level settings
);
```

#### `agents`

```sql
CREATE TABLE agents (
    id TEXT PRIMARY KEY,                -- UUID
    parent_agent_id TEXT,               -- Self-ref for hierarchy (NULL = top-level)
    agent_type TEXT NOT NULL,           -- 'claude', 'codex', 'gemini', 'custom'
    role TEXT,                          -- 'main', 'subagent', 'reviewer', etc.
    name TEXT,                          -- Human-readable name
    spawn_context TEXT,                 -- JSON: why/how this agent was spawned
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (parent_agent_id) REFERENCES agents(id)
);
CREATE INDEX idx_agents_parent ON agents(parent_agent_id);
CREATE INDEX idx_agents_type ON agents(agent_type);
```

#### `sessions`

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,                -- UUID (or session file stem)
    project_id TEXT NOT NULL,           -- FK → projects
    agent_id TEXT,                      -- FK → agents (which agent ran this session)
    session_type TEXT NOT NULL,         -- 'claude', 'codex', etc.
    workspace_path TEXT,                -- Working directory
    started_at TEXT NOT NULL,
    ended_at TEXT,
    last_activity_at TEXT NOT NULL,
    session_title TEXT,                 -- LLM-generated
    session_summary TEXT,               -- LLM-generated
    summary_updated_at TEXT,
    total_turns INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    metadata TEXT,                      -- JSON
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);
CREATE INDEX idx_sessions_project ON sessions(project_id);
CREATE INDEX idx_sessions_agent ON sessions(agent_id);
CREATE INDEX idx_sessions_activity ON sessions(last_activity_at DESC);
```

#### `turns`

```sql
CREATE TABLE turns (
    id TEXT PRIMARY KEY,                -- UUID
    session_id TEXT NOT NULL,           -- FK → sessions
    turn_number INTEGER NOT NULL,
    user_message TEXT,
    assistant_summary TEXT,             -- LLM-generated summary
    turn_status TEXT,                   -- 'completed', 'interrupted', 'error'
    model_name TEXT,
    git_commit_hash TEXT,               -- Commit created during/after this turn
    files_touched TEXT,                 -- JSON array of file paths
    tools_used TEXT,                    -- JSON array of tool names
    content_hash TEXT NOT NULL,         -- For deduplication
    timestamp TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(session_id, turn_number),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX idx_turns_session ON turns(session_id);
CREATE INDEX idx_turns_timestamp ON turns(timestamp DESC);
CREATE INDEX idx_turns_commit ON turns(git_commit_hash);
```

> **`content_hash` calculation**: MD5 hex digest of `f"{user_message}{assistant_summary}"`. Used for deduplication.

#### `turn_content`

```sql
CREATE TABLE turn_content (
    turn_id TEXT PRIMARY KEY,           -- FK → turns
    content_path TEXT NOT NULL,         -- Relative path to external JSONL file
    content_size INTEGER NOT NULL,
    content_hash TEXT NOT NULL,         -- MD5 for integrity verification
    FOREIGN KEY (turn_id) REFERENCES turns(id) ON DELETE CASCADE
);
```

#### `checkpoints`

```sql
CREATE TABLE checkpoints (
    id TEXT PRIMARY KEY,                -- UUID
    session_id TEXT NOT NULL,           -- FK → sessions
    git_commit_hash TEXT NOT NULL,      -- The anchoring commit
    git_branch TEXT,                    -- Branch name at checkpoint time
    parent_checkpoint_id TEXT,          -- Previous checkpoint in session
    files_snapshot TEXT,                -- JSON: {path: hash} of tracked files
    diff_summary TEXT,                  -- Human-readable diff summary
    agent_state TEXT,                   -- JSON: agent context at checkpoint time
    created_at TEXT DEFAULT (datetime('now')),
    metadata TEXT,                      -- JSON
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_checkpoint_id) REFERENCES checkpoints(id) ON DELETE SET NULL
);
CREATE INDEX idx_checkpoints_session ON checkpoints(session_id);
CREATE INDEX idx_checkpoints_commit ON checkpoints(git_commit_hash);
CREATE INDEX idx_checkpoints_created ON checkpoints(created_at DESC);
```

#### `events`

```sql
CREATE TABLE events (
    id TEXT PRIMARY KEY,                -- UUID
    title TEXT NOT NULL,
    description TEXT,
    event_type TEXT NOT NULL,           -- 'task', 'temporal', 'milestone'
    status TEXT NOT NULL DEFAULT 'active', -- 'active', 'frozen', 'archived'
    start_timestamp TEXT,
    end_timestamp TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    metadata TEXT                       -- JSON
);
```

#### `event_sessions` (M:N)

```sql
CREATE TABLE event_sessions (
    event_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    added_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (event_id, session_id),
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
```

#### `event_checkpoints` (M:N)

```sql
CREATE TABLE event_checkpoints (
    event_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    added_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (event_id, checkpoint_id),
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(id) ON DELETE CASCADE
);
```

#### `attributions`

```sql
CREATE TABLE attributions (
    id TEXT PRIMARY KEY,                -- UUID
    checkpoint_id TEXT NOT NULL,        -- FK → checkpoints
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    attribution_type TEXT NOT NULL,     -- 'human', 'agent'
    agent_id TEXT,                      -- FK → agents (NULL if human)
    session_id TEXT,                    -- FK → sessions
    turn_id TEXT,                       -- FK → turns (specific turn that made the change)
    confidence REAL DEFAULT 1.0,        -- 0.0-1.0
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL,
    FOREIGN KEY (turn_id) REFERENCES turns(id) ON DELETE SET NULL
);
CREATE INDEX idx_attributions_checkpoint ON attributions(checkpoint_id);
CREATE INDEX idx_attributions_file ON attributions(file_path);
CREATE INDEX idx_attributions_agent ON attributions(agent_id);
```

#### `embeddings`

```sql
CREATE TABLE embeddings (
    id TEXT PRIMARY KEY,                -- UUID
    source_type TEXT NOT NULL,          -- 'turn', 'session', 'checkpoint', 'event'
    source_id TEXT NOT NULL,            -- FK to source table
    model_name TEXT NOT NULL,           -- Embedding model identifier
    vector BLOB NOT NULL,              -- Raw embedding bytes (float32 array)
    dimensions INTEGER NOT NULL,
    text_hash TEXT NOT NULL,            -- Hash of source text (for staleness check)
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_embeddings_source ON embeddings(source_type, source_id);
CREATE INDEX idx_embeddings_model ON embeddings(model_name);
```

#### `sync_metadata`

```sql
CREATE TABLE sync_metadata (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Singleton row
    last_export_at TEXT,
    last_import_at TEXT,
    sync_status TEXT DEFAULT 'idle'     -- 'idle', 'exporting', 'importing', 'error'
);
```

#### FTS5 Virtual Tables

```sql
CREATE VIRTUAL TABLE fts_turns USING fts5(
    user_message,
    assistant_summary,
    content='turns',
    content_rowid='rowid'
);

CREATE VIRTUAL TABLE fts_events USING fts5(
    title,
    description,
    content='events',
    content_rowid='rowid'
);

CREATE VIRTUAL TABLE fts_sessions USING fts5(
    session_title,
    session_summary,
    content='sessions',
    content_rowid='rowid'
);
```

#### FTS5 Sync Triggers

```sql
-- fts_turns triggers
CREATE TRIGGER fts_turns_ai AFTER INSERT ON turns BEGIN
  INSERT INTO fts_turns(rowid, user_message, assistant_summary)
  VALUES (new.rowid, new.user_message, new.assistant_summary);
END;
CREATE TRIGGER fts_turns_ad AFTER DELETE ON turns BEGIN
  INSERT INTO fts_turns(fts_turns, rowid, user_message, assistant_summary)
  VALUES ('delete', old.rowid, old.user_message, old.assistant_summary);
END;
CREATE TRIGGER fts_turns_au AFTER UPDATE ON turns BEGIN
  INSERT INTO fts_turns(fts_turns, rowid, user_message, assistant_summary)
  VALUES ('delete', old.rowid, old.user_message, old.assistant_summary);
  INSERT INTO fts_turns(rowid, user_message, assistant_summary)
  VALUES (new.rowid, new.user_message, new.assistant_summary);
END;

-- fts_events triggers
CREATE TRIGGER fts_events_ai AFTER INSERT ON events BEGIN
  INSERT INTO fts_events(rowid, title, description)
  VALUES (new.rowid, new.title, new.description);
END;
CREATE TRIGGER fts_events_ad AFTER DELETE ON events BEGIN
  INSERT INTO fts_events(fts_events, rowid, title, description)
  VALUES ('delete', old.rowid, old.title, old.description);
END;
CREATE TRIGGER fts_events_au AFTER UPDATE ON events BEGIN
  INSERT INTO fts_events(fts_events, rowid, title, description)
  VALUES ('delete', old.rowid, old.title, old.description);
  INSERT INTO fts_events(rowid, title, description)
  VALUES (new.rowid, new.title, new.description);
END;

-- fts_sessions triggers
CREATE TRIGGER fts_sessions_ai AFTER INSERT ON sessions BEGIN
  INSERT INTO fts_sessions(rowid, session_title, session_summary)
  VALUES (new.rowid, new.session_title, new.session_summary);
END;
CREATE TRIGGER fts_sessions_ad AFTER DELETE ON sessions BEGIN
  INSERT INTO fts_sessions(fts_sessions, rowid, session_title, session_summary)
  VALUES ('delete', old.rowid, old.session_title, old.session_summary);
END;
CREATE TRIGGER fts_sessions_au AFTER UPDATE ON sessions BEGIN
  INSERT INTO fts_sessions(fts_sessions, rowid, session_title, session_summary)
  VALUES ('delete', old.rowid, old.session_title, old.session_summary);
  INSERT INTO fts_sessions(rowid, session_title, session_summary)
  VALUES (new.rowid, new.session_title, new.session_summary);
END;
```

#### Global DB Schema (`~/.entirecontext/db/ec.db`)

```sql
CREATE TABLE repo_index (
    repo_path TEXT PRIMARY KEY,
    repo_name TEXT,
    db_path TEXT NOT NULL,              -- Per-repo DB path
    last_indexed_at TEXT,
    session_count INTEGER DEFAULT 0,
    turn_count INTEGER DEFAULT 0
);
```

---

## 4. Agent Integration

### 4.1 Claude Code Hooks

EntireContext integrates with Claude Code via its hook system. Hook data is received via **stdin JSON protocol**.

| Hook | Trigger | stdin JSON Fields | Action |
|---|---|---|---|
| `SessionStart` | Session begins | `session_id`, `cwd`, `source` (startup/resume/clear/compact) | Create/resume session |
| `UserPromptSubmit` | User sends message | `session_id`, `transcript_path`, `cwd`, `prompt` | Record turn start |
| `Stop` | Agent completes | `session_id`, `transcript_path`, `cwd`, `stop_hook_active` | Record turn end, capture summary |
| `PostToolUse` | Tool executed | `session_id`, `transcript_path`, `tool_name`, `tool_input`, `tool_response` | Track tool usage |
| `SessionEnd` | Session ends | `session_id`, `cwd` | Set ended_at |

Hook configuration (`.claude/settings.json`):

```json
{
  "hooks": {
    "SessionStart": [{"command": "ec hook handle", "timeout": 5000}],
    "UserPromptSubmit": [{"command": "ec hook handle", "timeout": 5000}],
    "Stop": [{"command": "ec hook handle", "timeout": 10000}],
    "PostToolUse": [{"command": "ec hook handle", "timeout": 3000}],
    "SessionEnd": [{"command": "ec hook handle", "timeout": 5000}]
  }
}
```

> **Exit codes**: `0` = success, `2` = block action (PreToolUse only). Non-zero exits are logged but don't block by default.

### 4.2 Git Hooks

| Hook | Action |
|---|---|
| `post-commit` | Create checkpoint anchored to new commit |
| `pre-push` | Optional: sync checkpoints to shadow branch before push |

Installed via `ec init --hooks` or `ec enable`.

> Checkpoint creation only occurs when an active session exists. If no active session, `post-commit` hook is a no-op.

### 4.3 MCP Server

Transport: stdio. Registered in Claude Code MCP config. Implemented using Python FastMCP.

#### Tools

| Tool | Required Params | Optional Params | Returns |
|---|---|---|---|
| `ec_search` | `query: str` | `search_type: "regex"\|"fts"\|"semantic"`, `file_filter`, `commit_filter`, `agent_filter`, `since: ISO8601`, `limit: int=20` | Matching turns/sessions (id, summary, timestamp, relevance) |
| `ec_checkpoint_list` | — | `session_id`, `limit: int=20`, `since: ISO8601` | Checkpoint list (id, commit_hash, branch, created_at, diff_summary) |
| `ec_session_context` | — | `session_id` | Session summary + recent 10 turns. Returns session_id for subsequent calls |
| `ec_attribution` | `file_path: str` | `start_line: int`, `end_line: int` | Per-line attribution (type, agent_name, session_id, turn_id, confidence) |
| `ec_rewind` | `checkpoint_id: str` | — | Checkpoint files_snapshot + diff_summary + session context |
| `ec_related` | — | `query: str`, `files: list[str]` | Related sessions/turns sorted by relevance |

> Current session detection: if `session_id` is omitted, the server queries `sessions ORDER BY last_activity_at DESC LIMIT 1`.

---

## 5. Search

### 5.1 Search Modes

#### Regex Search (Default)

Pattern matching on turn content, session summaries, event descriptions. Follows Aline's proven hierarchical model.

```bash
ec search "authentication.*fix"
ec search "TODO" -t content        # Search in full turn content
ec search "login" -t session       # Search in session summaries
```

#### FTS5 Search

SQLite full-text search for fast keyword matching:

```bash
ec search "password reset flow" --fts
```

#### Semantic Search

Embedding-based similarity search using local models:

```bash
ec search "how did we handle rate limiting?" --semantic
```

Requires `entirecontext[semantic]` extra. Uses `sentence-transformers` (default model: `all-MiniLM-L6-v2`).

#### Structured Filters

Combine with any search mode:

```bash
ec search "bug" --file src/auth.py    # Only turns touching this file
ec search "refactor" --commit abc123  # Only turns near this commit
ec search "test" --agent claude       # Only Claude agent sessions
ec search "deploy" --since 2025-01-01 # Date range
```

### 5.2 Search Pipeline

```
Query → Parse filters → Route to search mode(s)
  ├── Regex  → scan turns/sessions/events
  ├── FTS5   → query virtual tables
  └── Semantic → embed query → cosine similarity on embeddings table
       ↓
  Merge + rank results → Format output
```

---

## 6. Git Shadow Branch

### 6.1 Branch Structure

Orphan branch: `entirecontext/checkpoints/v1`

```
entirecontext/checkpoints/v1
├── manifest.json                     # Index of all checkpoints
├── sessions/
│   ├── <session-id>/
│   │   ├── meta.json                 # Session metadata
│   │   └── transcript.jsonl          # Full turn transcript
│   └── ...
└── checkpoints/
    ├── <checkpoint-id>.json          # Checkpoint manifest
    └── ...
```

### 6.2 Conflict Avoidance

- **Append-only**: Each checkpoint is a separate file (no shared mutable state)
- **Manifest merge**: `manifest.json` uses checkpoint-ID-keyed entries; merge = union
- **Session transcripts**: Append-only JSONL; merge = concatenate + deduplicate by turn ID

### 6.3 Sync Workflow

```bash
ec sync          # Export local DB → shadow branch, push
ec pull          # Fetch shadow branch, import → local DB
```

```
ec sync workflow:
1. git fetch origin entirecontext/checkpoints/v1
2. App-level merge (NOT git 3-way merge):
   - manifest.json: JSON key union (checkpoint ID based)
   - sessions/*.jsonl: line append + turn_id dedup
   - checkpoints/*.json: file-level (same ID → skip, idempotent)
3. git add + commit on shadow branch
4. git push (fail → retry from step 1, max 3 attempts)
```

---

## 7. CLI Commands

### 7.1 Project Management

```bash
ec init              # Initialize EntireContext in current git repo
ec enable            # Enable auto-capture (install hooks)
ec disable           # Disable auto-capture (remove hooks)
ec status            # Show capture status, session info, DB stats
ec config [key] [val]  # Get/set configuration
ec doctor            # Diagnose issues (DB integrity, hook status, etc.)
                     # Includes warning for unsynced checkpoints:
                     #   'N checkpoints not synced to shadow branch.'
```

### 7.2 Search

```bash
ec search "query"              # Regex search (default)
ec search "query" --semantic   # Semantic search
ec search "query" --fts        # FTS5 search
ec search "query" --file PATH  # Filter by file
ec search "query" --commit HASH  # Filter by commit
ec search "query" --agent TYPE # Filter by agent type
ec search "query" -t TYPE      # Search target: turn|session|event|content
```

### 7.3 Checkpoints

```bash
ec checkpoint list             # List checkpoints (current session or all)
ec checkpoint show <id>        # Show checkpoint details
ec checkpoint diff <id1> <id2> # Diff between checkpoints
```

### 7.4 Rewind

```bash
ec rewind <checkpoint>         # Show code state at checkpoint
ec rewind <checkpoint> --restore  # Restore working tree to checkpoint state
```

> `ec rewind --restore` requires a clean working tree. If uncommitted changes exist, the command aborts with: 'Commit or stash your changes first.'

### 7.5 Sessions

```bash
ec session list                # List sessions
ec session show <id>           # Show session details + turn summaries
ec session current             # Show current active session
```

### 7.6 Events

```bash
ec event list                  # List events
ec event show <id>             # Show event details + linked sessions
ec event create "title"        # Create a new event
ec event link <event> <session>  # Link session to event
```

### 7.7 Attribution

```bash
ec blame <file>                # Show human/agent attribution per line
ec blame <file> --summary      # Aggregated attribution stats
ec blame <file> -L 10,20       # Specific line range
```

### 7.8 Sync

```bash
ec sync                        # Export to shadow branch + push
ec sync --no-filter            # Skip secret filtering
ec pull                        # Fetch shadow branch + import
```

### 7.9 Maintenance

```bash
ec index                       # Build/rebuild search indexes
ec index --semantic            # Generate embeddings for semantic search
```

---

## 8. Configuration

### 8.1 File Locations

| Path | Purpose |
|---|---|
| `~/.entirecontext/config.toml` | Global configuration |
| `~/.entirecontext/db/ec.db` | Global cross-repo index |
| `.entirecontext/config.toml` | Per-repo configuration |
| `.entirecontext/db/local.db` | Per-repo database |
| `.entirecontext/content/<session-id>/<turn-id>.jsonl` | Turn full content (external files) |

### 8.2 Configuration Keys

```toml
# ~/.entirecontext/config.toml

[capture]
auto_capture = true          # Auto-capture turns via hooks
checkpoint_on_commit = true  # Auto-checkpoint on git commit

[search]
default_mode = "regex"       # "regex" | "fts" | "semantic"
semantic_model = "all-MiniLM-L6-v2"

[sync]
auto_sync = false               # Auto-sync on push (disabled by default)
auto_sync_on_push = false       # Alias
shadow_branch = "entirecontext/checkpoints/v1"

[security]
filter_secrets = true
patterns = [
    '(?i)(api[_-]?key|secret|password|token)\s*[=:]\s*[''"]?[\w-]+',
    '(?i)bearer\s+[\w.-]+',
    'ghp_[a-zA-Z0-9]{36}',
    'sk-[a-zA-Z0-9]{48}'
]

[display]
max_results = 20
color = true
```

---

## 9. Implementation Phases

### Phase 1: Foundation (MVP)

**Goal**: Basic capture and search works.

- [x] Project structure, pyproject.toml, CLI skeleton
- [ ] SQLite schema (projects, sessions, turns, turn_content)
- [ ] Claude Code hooks: `UserPromptSubmit` → turn start, `Stop` → turn end
- [ ] Turn capture: parse Claude Code JSONL, extract user message + assistant summary
- [ ] Regex search across turns and sessions
- [ ] FTS5 on turns and sessions
- [ ] CLI: `ec init`, `ec enable`, `ec disable`, `ec status`, `ec search`, `ec session list/show`

**Deliverable**: `ec init` in a repo, use Claude Code, `ec search "query"` finds past turns.

### Phase 2: Git Integration

**Goal**: Checkpoints anchored to git commits.

- [ ] Checkpoints table + creation logic
- [ ] `post-commit` git hook → auto-checkpoint
- [ ] Shadow branch read/write (orphan branch management)
- [ ] CLI: `ec checkpoint list/show/diff`, `ec rewind`, `ec sync`, `ec pull`

**Deliverable**: Every git commit has a linked checkpoint. `ec rewind` shows what the agent was doing at any commit.

### Phase 3: Semantic Search & MCP

**Goal**: Agents can query their own history.

- [ ] Embedding pipeline (sentence-transformers, background indexing)
- [ ] Semantic search: query embedding → cosine similarity
- [ ] MCP server: `ec_search`, `ec_checkpoint_list`, `ec_session_context`, `ec_related`
- [ ] CLI: `ec search --semantic`, `ec index --semantic`

**Deliverable**: Agent uses MCP tool to search "how did we handle X?" and gets relevant past turns.

> Embedding model change: `ec index --semantic --force` for full re-indexing. Model name stored in embeddings table; mismatched model_name entries excluded from queries.

### Phase 4: Attribution & Multi-Agent

**Goal**: Know who changed what.

- [ ] Agent hierarchy tracking (parent_agent_id)
- [ ] Hunk-level attribution (git diff → agent/human mapping)
- [ ] Line-level attribution refinement
- [ ] CLI: `ec blame`

**Deliverable**: `ec blame src/auth.py` shows which lines were written by human vs. agent, with links to the session/turn.

> Multi-agent concurrency details to be specified in Phase 4.

### Phase 5: Sharing & Cross-Repo

**Goal**: Context travels across machines and repos.

- [ ] Cross-machine sync workflow (shadow branch push/pull)
- [ ] Global DB: cross-repo search index
- [ ] Event sharing between repos
- [ ] CLI: `ec event create/link`, enhanced `ec sync`

**Deliverable**: Search across all repos. Share context between team members via git.

---

## 10. Tech Stack

| Component | Choice | Rationale |
|---|---|---|
| Language | Python 3.12+ | Primary language, Aline ecosystem compatibility |
| Package manager | uv | Already in use |
| CLI framework | Typer + Rich | Consistent with Aline, good DX |
| Database | SQLite | Local-first, zero server, proven at Aline scale |
| Embedding storage | SQLite BLOB | Simple, sufficient for agent session scale |
| Embedding model | sentence-transformers (local) | No API key needed, privacy-preserving |
| MCP transport | stdio | Claude Code standard |
| Git integration | Shadow branch (orphan) | Entire.io-proven pattern, portable |
| Configuration | TOML | Python ecosystem standard |

---

## 11. Open Questions

### 11.1 Embedding Cold-Start

**Question**: On first `ec search --semantic`, should we index all history or start lazy?

**Recommendation**: Lazy by default. `ec index --semantic` for backfill. New turns are embedded on capture. Rationale: initial embedding of large history can take minutes; users expect search to be fast.

### 11.2 Shadow Branch Conflicts

**Question**: Multi-machine push conflicts on shadow branch?

**Recommendation**: Append-only structure (one file per checkpoint). Manifest uses checkpoint-ID keys for easy merge. JSONL transcripts are append-only. In worst case, `ec pull --force` rebuilds from shadow branch files.

### 11.3 Attribution Granularity

**Question**: Line-level vs hunk-level attribution for MVP?

**Recommendation**: Start with hunk-level (git diff hunks mapped to turns). Refine to line-level in Phase 4. Hunk-level is much simpler and still very useful.

### 11.4 Token Usage Tracking

**Question**: Track token usage per turn?

**Recommendation**: Parse from Claude Code JSONL if available. Store in turn metadata as optional field. Don't block on this — it's a nice-to-have.

### 11.5 Global DB Sync

**Question**: How does the global DB sync across machines?

**Recommendation**: Global DB is local-only (rebuilt from per-repo data). Each repo's shadow branch is the sync unit. On `ec pull`, global DB is updated. No separate global sync mechanism needed.

---

## Appendix A: Aline Migration Path

EntireContext can import existing Aline data:

1. Read Aline SQLite DB (`~/.aline/db/aline.db`)
2. Map: Aline sessions → EC sessions, Aline turns → EC turns, Aline events → EC events
3. Generate checkpoints retroactively from turns with `git_commit_hash`
4. Backfill turn_content from Aline JSONL files

CLI: `ec import --from-aline [path]`

## Appendix B: Data Size Estimates

For a typical project with 6 months of AI-assisted development:

| Data | Estimate |
|---|---|
| Sessions | ~200 |
| Turns | ~5,000 |
| Checkpoints | ~1,000 (one per commit) |
| Turn content (JSONL) | ~500MB |
| SQLite DB (metadata) | ~50MB |
| Embeddings | ~100MB (5K turns × 384-dim × 4 bytes × 2 for overhead) |
| Shadow branch | ~200MB (compressed transcripts) |

All comfortably within single-machine storage limits.
