# Repository Guidelines

## Project Structure & Module Organization
- Source code lives in `src/entirecontext/`, organized by layer:
  - `cli/` (Typer commands), `core/` (business logic), `db/` (schema/migrations), `hooks/` (Claude hook handlers), `sync/` (shadow-branch export/import), `mcp/` (MCP server).
- Tests are in `tests/`, with both unit and end-to-end coverage (for example `tests/test_core.py`, `tests/test_e2e_search.py`).
- Documentation and research notes are in `docs/` and `docs/research/`.
- Build artifacts are output to `dist/`.

## Build, Test, and Development Commands
- `uv sync` : Install runtime dependencies.
- `uv sync --extra dev` : Install developer tools (`pytest`, `pytest-cov`, `ruff`).
- `uv run ec --help` : Verify CLI entrypoint and available commands.
- `uv run pytest` : Run full test suite.
- `uv run pytest --cov=entirecontext` : Run tests with coverage.
- `uv run ruff format .` : Format code (line length 120).
- `uv run ruff check . --fix` : Lint and auto-fix issues.
- `uv build` : Build distributable packages.

## Coding Style & Naming Conventions
- Python 3.12+ only (`requires-python >=3.12`).
- Use Ruff for formatting/linting; keep line length at 120.
- Follow existing naming patterns: snake_case for modules/functions, PascalCase for classes, descriptive command modules like `search_cmds.py`.
- Keep CLI concerns in `cli/` and domain logic in `core/`; avoid cross-layer shortcuts.

## Testing Guidelines
- Framework: `pytest` with shared fixtures in `tests/conftest.py`.
- Name tests as `test_*.py` and functions as `test_<behavior>`.
- Add/adjust tests for every behavior change, including edge and regression paths.
- Prefer real business logic execution; mock only external integrations when necessary.

## Commit & Pull Request Guidelines
- Commit style in history follows Conventional Commit-like prefixes: `feat(...)`, `fix(...)`, `refactor(...)`, `docs(...)`.
- Keep each commit focused on one change area and include scope when useful (example: `feat(search): add hybrid reranking`).
- PRs should include: purpose, key changes, test evidence (commands + results), and linked issue/task.
- Include CLI output snippets or screenshots when user-facing command behavior changes.

## Security & Configuration Tips
- Never commit secrets; use environment variables (for example `OPENAI_API_KEY`, `GITHUB_TOKEN`).
- Repo/local settings live under `.entirecontext/`; validate setup with `ec doctor` after config changes.

---

## Dogfooding: Using EntireContext During Development

This project's own features should be actively used during development sessions. Below are patterns for leveraging EntireContext's CLI and MCP tools as part of the development workflow.

### MCP Tools for In-Session Context

The EntireContext MCP server is registered in Claude Code and provides these tools during active sessions:

| MCP Tool | When to Use | Example |
|---|---|---|
| `ec_search` | Finding past implementations, debugging history | Search "how was filtering implemented" before adding new filters |
| `ec_session_context` | Understanding current session state | Check captured turns before session end |
| `ec_related` | Finding related code/discussions | Find turns that touched `exporter.py` |
| `ec_checkpoint_list` | Tracking progress snapshots | List checkpoints for current session |
| `ec_turn_content` | Reviewing full turn details | Get complete content of a specific turn |
| `ec_attribution` | Understanding code ownership | Check who wrote specific lines |
| `ec_rewind` | Time-travel to past states | View code at a specific checkpoint |
| `ec_assess` / `ec_assess_create` | Evaluating changes against roadmap | Assess current diff before committing |
| `ec_assess_trends` | Cross-session trend analysis | Review verdict distribution over time |
| `ec_lessons` | Learning from past assessments | Check distilled lessons before new work |

### CLI Commands for Development Workflow

#### Before Starting Work
```bash
ec status                        # Check current session/project state
ec doctor                        # Validate hooks and config
ec search "topic" --fts          # Find past work on similar topics
ec session list --limit 5        # Review recent sessions
```

#### During Development
```bash
ec checkpoint create             # Snapshot progress at meaningful points
ec blame src/path/file.py        # Check attribution for code being modified
ec ast-search "function_name"    # Find symbol definitions across codebase
```

#### After Implementation
```bash
ec dashboard                     # Review session stats and trends
ec futures assess                # Assess changes against roadmap
ec session export                # Export session as markdown doc
ec sync                          # Push to shadow branch
```

#### Debugging & Investigation
```bash
ec search "error pattern" --fts  # Find past encounters of similar errors
ec rewind <checkpoint_id>        # View code at a past checkpoint
ec graph --session <id>          # Visualize multi-agent session graph
ec session activate <query>      # Find related turns via spreading activation
```

### Configuration for Active Dogfooding

Enable these config keys in `.entirecontext/config.toml` for full dogfooding:

```toml
[capture]
auto_capture = true
checkpoint_on_commit = true
checkpoint_on_session_end = true
intent_summary = true            # LLM-based session intent summarization

[sync]
auto_sync_on_push = true         # Auto-sync on git push via pre-push hook

[index]
auto_embed = true                # Auto-generate embeddings on session end

[futures]
auto_distill = true              # Auto-distill lessons from assessments
```

### Development Patterns

#### Pattern: Context-Aware Implementation
Before implementing a feature, search for related past work:
1. Use `ec_search` or `ec search --fts` to find relevant past turns
2. Use `ec_related` with file paths being modified
3. Review `ec_lessons` for applicable learnings
4. Create checkpoints at meaningful milestones

#### Pattern: Assessment-Driven Development
After completing a feature:
1. Run `ec futures assess` to evaluate against roadmap
2. If assessment feedback exists, review with `ec futures feedback`
3. Check `ec_assess_trends` for pattern of verdicts over time

#### Pattern: Multi-Session Continuity
When resuming work across sessions:
1. `ec session list` to find the previous session
2. `ec session show <id>` to review what was done
3. `ec_session_context` to get the last session's summary
4. `ec search "specific topic"` to find exact implementation details

#### Pattern: Hook-Driven Automation
The hook system captures development activity automatically:
- **SessionStart** → creates/resumes session tracking
- **UserPromptSubmit** → captures each user prompt as a turn
- **PostToolUse** → tracks tools and files touched
- **Stop** → captures assistant response summary
- **SessionEnd** → generates summaries, triggers auto-sync/embed/distill
- **PostCommit** (git hook) → creates checkpoint on each commit
- **pre-push** (git hook) → triggers `ec sync --if-enabled`

### Adding New CLI Commands
When adding a new CLI command:
1. Create `cli/<name>_cmds.py` with `@app.command()` decorators
2. Import and register in `cli/__init__.py`
3. Keep business logic in `core/` — CLI layer handles args/output only
4. Add corresponding MCP tool in `mcp/server.py` if the feature is useful for in-session queries
5. Update `CLAUDE.md` architecture section if new module is added
