# EntireContext

**Git-anchored decision memory for coding agents.**

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue) ![Version 0.10.0](https://img.shields.io/badge/version-0.10.0-green) ![Status Experimental](https://img.shields.io/badge/status-experimental-orange) ![License MIT](https://img.shields.io/badge/license-MIT-lightgrey)

> ⚠️ **Experimental** — API and data format may change without notice.

EntireContext captures AI coding work as it happens, distills decisions and lessons from it, and brings the right context back when similar code changes happen again. It turns session history into memory tied to commits, diffs, checkpoints, and files instead of leaving it as raw transcript storage.

This README is the quick-start entry point. For exhaustive detail:

- [EntireContext Project Manual](docs/entirecontext-project-manual.md) — long-form architecture, agent integration, and troubleshooting guide
- [`docs/spec.md`](docs/spec.md) — compact CLI/MCP/config/data-model reference for the current implementation
- [`docs/decisions_outcomes.md`](docs/decisions_outcomes.md) — decision staleness and outcome vocabulary

## How It Works

- **Capture** — sessions, turns, tool calls, and checkpoints are recorded through hooks and anchored to git history
- **Distill** — assessments, feedback, and lessons convert raw session history into reusable judgment
- **Retrieve** — search, graph traversal, attribution, and rewind surface the most relevant prior context
- **Intervene** — agents and humans can apply past decisions before the next related change lands

The core record is the **Decision** — reusable engineering intent (what was chosen, why, what was rejected), linked to files, checkpoints, and **Assessments**. Decision usage feedback distills into a **Lesson** and can move a decision through its `staleness_status` (`fresh` → `stale` / `superseded` / `contradicted`), so old guidance stops dominating retrieval once code or newer decisions disagree with it. See `docs/decisions_outcomes.md` and manual §2.4/§11 for the full state machine.

## Quick Start

Choose an install path first:

- **Local dependency** (inside a Python/uv project)
- **Global install (optional)** for using `ec` as a standalone CLI across any repo

Use **global install (optional)** when you want `ec` like an app/tool.
Use **local dependency** when you want to manage `entirecontext` in a Python project's dependencies.

```bash
# 1A. Local dependency (Python/uv project)
uv add 'entirecontext[mcp]'
# or: pip install 'entirecontext[mcp]'
```

```bash
# 1B. Global install (optional, recommended for non-Python repos)
uv tool install --managed-python --python 3.13 'entirecontext[mcp]'
# alternative:
pipx install 'entirecontext[mcp]'
```

`--managed-python` keeps the tool environment bound to a uv-managed interpreter.
It avoids mutable system or Conda interpreter paths changing Python minor versions
behind an existing environment.

The `[mcp]` extra installs the MCP SDK that `ec mcp serve` needs. Install it before you run the default `ec init`, because `ec init` registers that server. `ec init --no-hooks` skips MCP registration, but it also skips hook installation.

`ec search --semantic` needs the `semantic` extra (`entirecontext[mcp,semantic]`), which installs `sentence-transformers` and PyTorch. The first embedding run downloads the `all-MiniLM-L6-v2` model (about 87 MB) into the Hugging Face cache. Search also needs stored embeddings: run `ec index --semantic` first, or set `index.auto_embed = true`. Without embeddings, semantic search returns no results.

Tagged GitHub releases also include the built wheel and source tarball as release assets. PyPI remains the primary install path.

Use the same workflow after either install path. After a local dependency install, run each command through `uv run` (for example, `uv run ec init`) or activate the project environment. After a global install, use `ec` directly.

```bash
# 2. Initialize in your repo — installs Claude Code hooks, git hooks, and MCP config
cd your-project
ec init

# 3. Use Claude Code as usual — sessions are captured automatically

# 4. Query your history
ec search "authentication"
ec search "refactor" --fts
ec session list
ec blame src/main.py
ec checkpoint list
```

Run `ec <command> --help` or see `docs/spec.md` §4.1 for the full CLI surface.

### Windows Notes

- Install alternative (Python launcher): `py -m pip install "entirecontext[mcp]"`
- PowerShell example:
  ```powershell
  ec init
  ec search "authentication"
  ```
- If `ec` is not recognized, open a new terminal (or sign out/in) so updated PATH is loaded.
- For `uv tool`/`pipx` installs, ensure the scripts directory is on PATH.

## MCP & Agent Integration

`ec init` automatically registers the MCP server in `~/.claude/settings.json`; `ec mcp serve` runs it standalone over stdio. Manual setup:

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

Decisions also surface without an explicit call. The `UserPromptSubmit` hook ranks and injects top decisions per prompt as `additionalContext`. When `decisions.surface_on_tool_use` is enabled, `PostToolUse` writes hits for just-edited files to `.entirecontext/decisions-context-tooluse-<session>.md`. When `decisions.show_related_on_start` is enabled (default `false`), `SessionStart` writes related decisions to `.entirecontext/decisions-context.md` if any exist. See manual §4.2–§4.4 for ranking, timeout, and dedup config.

### Available Tools

| Tool | Description |
|------|-------------|
| `ec_decision_context` | Proactive one-call decision retrieval from the current session (files, diff, latest checkpoint) |
| `ec_decision_create` | Create a decision record (title, rationale, rejected alternatives, scope) |
| `ec_decision_get` | Resolve decision by full or prefix ID |
| `ec_decision_list` | List decisions with optional filters (status, tags, files) |
| `ec_decision_outcome` | Record the outcome of a decision (accepted, ignored, contradicted, refined, or replaced) |
| `ec_decision_related` | Rank linked decisions by file overlap, assessment relations, and diff text match |
| `ec_decision_search` | Keyword search over decisions via FTS5, with optional hybrid ranking and staleness filters |
| `ec_decision_stale` | Check if a decision's linked files have changed recently (read-only staleness probe) |
| `ec_decision_candidate_list` | List candidate decisions; filter by session, status, confidence, or source type |
| `ec_decision_candidate_get` | Get a single candidate with full score breakdown |
| `ec_decision_candidate_confirm` | Promote a candidate to a real decision via atomic claim-then-promote |
| `ec_decision_candidate_reject` | Reject a candidate (leaves no trace in decisions) |
| `ec_search` | Search turns/sessions with regex or FTS5. Filters: `file_filter`, `commit_filter`, `agent_filter`, `since` |
| `ec_related` | Find related sessions/turns by query text or file paths |
| `ec_ast_search` | Search AST symbols by name, filtered by `symbol_type` and `file_filter` |
| `ec_activate` | Spread-activation retrieval from a seed turn/session with `max_hops` and `decay` |
| `ec_session_context` | Get session details with recent turns. Auto-detects current session if `session_id` omitted |
| `ec_turn_content` | Get full content for a specific turn (including JSONL content files) |
| `ec_attribution` | Get human/agent attribution for a file, with optional line range |
| `ec_context_apply` | Record how retrieved context was applied (`reference`, `decision_change`, `code_reuse`, or `lesson_applied`) linking back to a prior retrieval selection |
| `ec_checkpoint_list` | List checkpoints, optionally filtered by `session_id` and `since` |
| `ec_rewind` | Show state at a specific checkpoint |
| `ec_assess` | Assess staged diff or checkpoint against roadmap via LLM |
| `ec_assess_create` | Create an assessment programmatically (verdict, impact, suggestion) |
| `ec_feedback` | Add agree/disagree feedback to an assessment |
| `ec_lessons` | Return a bounded JSON lesson list for the resolved repository, using the configured verdict floor; does not write `LESSONS.md` |
| `ec_assess_trends` | Cross-repo assessment trend analysis (verdict distribution, feedback stats) |
| `ec_dashboard` | Dashboard statistics: session/turn/checkpoint activity over a `since` window |
| `ec_graph` | Build a knowledge graph (nodes/edges/stats) for a session or time window |

Tools that expose a `repos` parameter use `null` for the current repo, `["*"]` for all repos, and `["name"]` for specific repos. Tools without that parameter operate on the resolved current repository or their tool-specific scope.

## Agent Setup Templates

Templates for configuring agents to proactively reuse stored decisions and lessons. Adoption is optional; each project chooses and enforces its own requirements.

- Project policy: [entirecontext-project-decision-policy-template.md](docs/templates/entirecontext-project-decision-policy-template.md)
- Maintainers: [entirecontext-maintainer-decision-reuse-template.md](docs/templates/entirecontext-maintainer-decision-reuse-template.md)
- Users: [entirecontext-user-decision-reuse-template.md](docs/templates/entirecontext-user-decision-reuse-template.md)
- Proactive guidance: [entirecontext-proactive-guidance.md](docs/templates/entirecontext-proactive-guidance.md) — broader memory reuse beyond decisions (assessments, lessons, checkpoints, attribution)

## Development

```bash
git clone https://github.com/teslamint/entirecontext.git
cd entirecontext
uv sync --extra dev --extra semantic --extra mcp
uv run pytest
uv run ruff format . && uv run ruff check . --fix
```

This project's own AI development history is available on the `entirecontext/checkpoints/v1` branch. See [`CLAUDE.md`](CLAUDE.md) and manual §13 for contributor policy.

## Acknowledgments

EntireContext was inspired by:

- [Entire](https://entire.io) ([entireio/cli](https://github.com/entireio/cli)) — Developer platform for AI agents; its CLI captures agent sessions in the Git workflow, and the platform adds Git-compatible hosting for agents
- [OneContext](https://one-context.com) ([LastPieceAI/OneContext](https://github.com/LastPieceAI/OneContext)) — Agent self-managed context layer for unified AI agent memory
- The **Futures Assessment** feature (`ec futures`) is inspired by Kent Beck's [Earn *And* Learn](https://tidyfirst.substack.com/p/earn-and-learn) and the [Tidy First](https://tidyfirst.substack.com/) philosophy — analyzing whether each change expands or narrows your project's future options.

## License

[MIT](LICENSE)
