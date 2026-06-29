# WhyDev — Rebrand & Positioning Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebrand EntireContext to WhyDev and reposition the project as the decision memory layer for agent-assisted development, with clear differentiation from the crowded agent-memory market.

**Architecture:** Same `capture→distill→retrieve→intervene→outcome` loop. The rebrand changes identity, naming, and packaging — not the core architecture. One new schema addition (`decided_by`) enhances the decision model with decision-maker attribution (shipped as a separate feature after the rebrand stabilizes, not bundled into the v1.0 release).

**Tech Stack:** Python 3.12+, uv, SQLite (WAL mode), Typer CLI (`wy`), MCP server

## Global Constraints

- All changes land in a single v1.0 release (no gradual migration)
- No backward compatibility with `ec` CLI or `entirecontext` PyPI package (alpha status)
- Existing data must be migratable via `wy migrate` command
- No new external dependencies
- All existing tests must pass after rename (adjusted imports)

## Name Verification (2026-06-29)

| Channel | Status | Notes |
|---------|--------|-------|
| PyPI | Available (404) | `whydev` not registered |
| GitHub | Clean | 3 small repos (1 archived, 2 personal); no dominant project |
| .com domain | Available (000) | Not registered |
| .ai domain | Available (000) | Not registered |
| Web search | Clean | No product/company named "whydev" |

Previous candidate `decidelog` was rejected: decidelog.com is an active site ("How engineering decisions really get made") with direct positioning overlap.

---

## 1. Rebrand Identity

### 1.1 Name Change

| Item | Current | New |
|------|---------|-----|
| Project name | EntireContext | WhyDev |
| PyPI package | `entirecontext` | `whydev` |
| CLI command | `ec` | `wy` |
| MCP tool prefix | `ec_*` | `wy_*` |
| MCP server name | `entirecontext` | `whydev` |
| GitHub repo | `entirecontext` | `whydev` |

### 1.2 Path Changes

| Item | Current | New |
|------|---------|-----|
| Per-repo DB dir | `.entirecontext/` | `.whydev/` |
| Global config/state | `~/.entirecontext/` | `~/.whydev/` |
| Config files | `.entirecontext/config.toml` | `.whydev/config.toml` |
| DB file | `.entirecontext/db/local.db` | `.whydev/db/local.db` |
| Global DB | `~/.entirecontext/db/ec.db` | `~/.whydev/db/wy.db` |

### 1.3 Migration Command

`wy migrate` handles the full transition from EntireContext to WhyDev:

**Per-repo migration:**
- Move `.entirecontext/` → `.whydev/` directory tree
- Update internal path references in the SQLite database (content_path columns, etc.)
- Update `.gitignore` entries

**Global migration:**
- Move `~/.entirecontext/` → `~/.whydev/` (config, state, global DB)
- Rename `ec.db` → `wy.db`
- Update cross-repo sync metadata (repo paths in sync tables)
- Migrate codex_notify state file paths

**External config guidance (cannot be auto-migrated):**
- Print instructions to update Claude Code MCP server registration (`mcp.json` or equivalent)
- Print instructions to update Codex `config.toml` notify hook references
- Print instructions to update CLAUDE.md / AGENTS.md tool references

One-time operation. Detects and migrates all repos with `.entirecontext/` directories.

### 1.4 Description & Tagline

- **One-liner:** "Decision memory for agent-assisted development"
- **Tagline:** "Remember why, not just what"
- **Full description:** "WhyDev records engineering decisions — who made them, why, what alternatives were rejected — and tracks their outcomes over time. Git-anchored, agent-agnostic, self-improving."

### 1.5 Scope of Non-Decision Features

WhyDev's codebase includes substantial non-decision capture infrastructure (turns, checkpoints, AST index, knowledge graph, dashboard). These remain as the foundation that powers the decision memory loop — capture feeds distill, checkpoints anchor assessments, AST enables file-level attribution. The "decision memory" positioning describes the product's value proposition, not a feature reduction. No existing capabilities are removed.

## 2. Positioning

### 2.1 Value Proposition

WhyDev is the **decision memory layer** that sits beneath agent-native memory systems (Claude auto-memory, Codex session history, etc.) and above the git history.

- Agent auto-memory = preferences, patterns, corrections ("use `uv run pytest` not `pytest`")
- WhyDev = decisions, rationale, alternatives, outcomes ("chose SQLite over Redis because X; 3 months later: decision held, no perf issues")
- Git history = what changed, when, by whom

WhyDev fills the gap: **why** things were decided, not just **what** changed or **how** to do things.

### 2.2 Competitive Differentiation

| Capability | WhyDev | Mem0/OpenMemory | Claude Auto-Memory | Zep |
|------------|--------|-----------------|---------------------|-----|
| Memory target | Decisions + alternatives + rationale | Facts / preferences | Patterns / corrections | Conversation summaries |
| Outcome tracking | 5 types (accepted/ignored/contradicted/refined/replaced) + quality score | None | None | None |
| Temporal model | Git-anchored time-travel (rewind, blame, TQL planned) | None | Session-scoped | Decay only |
| Self-improvement | outcome→ranking→extraction feedback loop | Auto-extraction only | Dreaming consolidation | Auto-summarization |
| Agent compatibility | Claude/Codex/Gemini/any MCP client | MCP | Claude only | LangChain/MCP |
| Storage | Local SQLite (WAL) + git-anchored | Cloud or local | Cloud (Anthropic) | Cloud or self-hosted |

### 2.3 Relationship with Built-in Agent Memory

WhyDev is a **complement and infrastructure layer**, not a replacement:

1. Agent auto-memory handles the "how" (workflow preferences, tool usage patterns)
2. WhyDev handles the "why" (engineering decisions, their context, their outcomes)
3. Git history handles the "what" and "when"

Integration path: CLAUDE.md / AGENTS.md references `wy` commands so agents naturally leverage decision memory during their sessions.

## 3. Decision Attribution (`decided_by`) — Post-v1.0

**Scope decision:** `decided_by` is shipped as a separate feature release (v1.1 or later), not bundled with the v1.0 rebrand. Rationale: the v1.0 release is already a large mechanical change (rename everything); mixing a new schema column + inference logic increases risk. The rebrand should stabilize first.

### 3.1 Schema Addition (v1.1+)

New column on `decisions` table:

```sql
decided_by TEXT NOT NULL DEFAULT 'collaborative'
  CHECK (decided_by IN ('human', 'agent', 'collaborative'))
```

- **human**: Human explicitly made the decision; agent executed
- **agent**: Agent autonomously decided; human approved/ignored post-hoc
- **collaborative**: Decision emerged from human-agent dialogue (most common)

### 3.2 Recording Paths

| Path | Default `decided_by` | Override |
|------|---------------------|----------|
| `wy decision create` (CLI) | `human` | `--decided-by agent\|collaborative` |
| `wy_decision_create` (MCP) | `collaborative` | `decided_by` parameter |
| Auto-extraction (SessionEnd) | Inferred from turn context | N/A |
| `wy decision candidate confirm` | Inherited from candidate | Overridable |

### 3.3 Inference Logic (Auto-extraction)

When extracting decisions from session turns:
- Decision text found primarily in user messages → `human`
- Decision text found primarily in assistant messages without prior user directive → `agent`
- Decision emerged from back-and-forth dialogue → `collaborative`

Inference is best-effort; `collaborative` is the safe fallback. Attribution accuracy is validated qualitatively via dogfooding audit (manual review of N≥20 auto-extracted decisions), not a hard numeric target — the distribution is expected to skew heavily toward `collaborative`.

### 3.4 Dashboard / Analytics

- `wy dashboard` shows decision-maker distribution (human / agent / collaborative)
- Outcome comparison: "agent decisions accepted rate" vs "human decisions accepted rate"

## 4. v1.0 Transition Plan

### 4.1 Prerequisites (Complete Before Rebrand)

- [ ] Current ROADMAP v1.0 gate met: `capture→distill→retrieve→intervene→outcome` loop completes autonomously
- [ ] `auto_extract` default true with production verification
- [ ] Migration command tested across multiple repos (resume, chessqueen, stockbot, entirecontext worktree)

### 4.2 v1.0 Release Checklist

- [ ] Rename Python package: `entirecontext` → `whydev` (pyproject.toml, src/ directory)
- [ ] Rename CLI entry point: `ec` → `wy`
- [ ] Rename all MCP tools: `ec_*` → `wy_*`
- [ ] Update all import paths: `entirecontext.*` → `whydev.*`
- [ ] Update all path constants: `.entirecontext/` → `.whydev/`
- [ ] Add `wy migrate` command for data migration (per-repo + global + guidance for external configs)
- [ ] Update README, CLAUDE.md, AGENTS.md with new identity
- [ ] Update GitHub repo name and description
- [ ] Publish `whydev` to PyPI
- [ ] Tag v1.0.0

### 4.3 What Does NOT Change

- Core architecture (`capture→distill→retrieve→intervene→outcome`)
- Database schema version (rename only, no column additions in v1.0)
- Hook system (Claude Code hooks integration)
- Config TOML format and sections
- Test structure and fixtures (adjusted imports only)
- Git-anchored temporal model

## 5. Post-v1.0 Roadmap Direction

### 5.1 Decision Attribution (v1.1)

`decided_by` field as described in Section 3. Separate release after rebrand stabilizes.

### 5.2 Retroactive Archaeology (Cold Start Solution)

`wy archaeologize` — extract decision corpus from existing git history:
- Parse `git log --patch` for decision-indicating patterns
- Extract PR descriptions and review comments for rationale
- Generate `source:inferred` decisions with `decided_by:collaborative` default
- Eliminates the largest adoption barrier (empty database on first use)

Existing brainstorm: `docs/brainstorms/retroactive-git-archaeology.md`

### 5.3 Decision Packs + Team

Reusable decision bundles by domain:
- `wy pack create testing` — bundle testing-related decisions for reuse
- `wy pack apply <pack-name>` — apply a decision pack to a new repo
- Team sharing: export/import packs across repos and team members
- v1.x track: team-scoped decision visibility (surfacing only, no enforcement)

### 5.4 Other Exploration Items (Unchanged)

These remain in the exploration backlog with adjusted naming:
- Temporal Query Language (TQL): `wy query --at <ref>`
- Decision-Annotated Git Blame: `wy blame <file>`
- Alive Session Memory (Rolling WAL Capture)
- Pre-Compaction Session Snapshot

## 6. Non-Goals (Reinforced)

- NOT a generic knowledge management system or RAG platform
- NOT policy enforcement / governance / ACL
- NOT agent behavior analysis / monitoring
- NOT code generation or change suggestion
- NOT agent-to-agent communication layer
- NOT a replacement for Claude auto-memory or Codex session history

## 7. Success Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| Name collision | Zero | No search result overlap on "whydev" for competing products |
| PyPI package available | Yes | `pip install whydev` works |
| Cold start time (with archaeology) | < 5 min for typical repo | Time from `wy init` + `wy archaeologize` to first surfaced decision |
| Existing user migration | < 2 min | Time to run `wy migrate` on a typical repo |
| Multi-repo migration | All repos migrated | resume, chessqueen, stockbot, entirecontext worktree all functional post-migrate |
| External config guidance | Complete | `wy migrate` prints actionable instructions for MCP registration and hook updates |

## References

- [Agent Memory Landscape Research](../../research/agent-memory-landscape.md)
- [Product Roadmap Ideation](../../ideation/2026-04-27-product-roadmap-ideation.md)
- [Retroactive Git Archaeology Brainstorm](../../brainstorms/retroactive-git-archaeology.md)
- [Project Direction Interview (2026-06-02)](memory: project-direction-2026-06-02)
